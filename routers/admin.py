from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from helpers.admin_utils import ADMIN_SESSIONS, ADMIN_USERS, CANCEL_REASONS, get_admin_session
from helpers.complaint_utils import escalate_overdue_complaints
from models import ADMIN_ALLOWED_STATUSES, Complaint, ComplaintStatus


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

ADMIN_STATUS_CHOICES = [
    ComplaintStatus.UNDER_REVIEW.value,
    ComplaintStatus.ACCEPTED.value,
    ComplaintStatus.REJECTED.value,
    ComplaintStatus.CANCELLED.value,
    ComplaintStatus.ESCALATED.value,
    ComplaintStatus.REOPENED.value,
    ComplaintStatus.ON_HOLD.value,
    ComplaintStatus.DUPLICATE.value,
    ComplaintStatus.TRANSFERRED.value,
    ComplaintStatus.UNSERVICEABLE.value,
    ComplaintStatus.CLOSED.value,
]


def _format_status_label(value: str) -> str:
    return value.replace("_", " ").title()


@router.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    """
    Render the admin login page.

    Different admin accounts correspond to different departments.
    """
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": None},
    )


@router.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Handle admin login.

    If credentials are valid, a simple session token is created and
    stored in memory, and a cookie is set so only logged-in admins
    can access the department complaints page.
    """
    user = ADMIN_USERS.get(username)
    if user is None or user["password"] != password:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )

    from uuid import uuid4

    token = uuid4().hex
    ADMIN_SESSIONS[token] = {
        "username": username,
        "department": user["department"],
    }

    response = RedirectResponse(url="/admin/complaints", status_code=303)
    response.set_cookie("admin_session", token, httponly=True)
    return response


@router.get("/admin/logout")
async def admin_logout(request: Request):
    """
    Clear admin session and redirect back to the login page.
    """
    token = request.cookies.get("admin_session")
    if token:
        ADMIN_SESSIONS.pop(token, None)

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


@router.get("/admin/complaints", response_class=HTMLResponse)
async def admin_complaints(request: Request, db: Session = Depends(get_db)):
    """
    Web page for department admins.

    Shows only the complaints that belong to the admin's department.
    """
    session = get_admin_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=303)

    department = session["department"]

    # Before showing the list, escalate any overdue complaints.
    escalate_overdue_complaints(db)

    complaints = (
        db.query(Complaint)
        .filter(Complaint.department == department)
        .order_by(Complaint.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "admin_complaints.html",
        {
            "request": request,
            "username": session["username"],
            "department": department,
            "complaints": complaints,
            "cancel_reasons": CANCEL_REASONS,
            "admin_status_choices": ADMIN_STATUS_CHOICES,
            "format_status_label": _format_status_label,
        },
    )


@router.post("/admin/complaints/{complaint_id}/cancel")
async def cancel_complaint(
    complaint_id: int,
    request: Request,
    reason: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Allow an admin to cancel a complaint with a fixed reason.

    The complaint's status is set to CANCELLED and the reason is stored
    in the cancel_reason field.
    """
    session = get_admin_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=303)

    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # Ensure the complaint belongs to the admin's department before allowing cancellation.
    if complaint.department != session["department"]:
        raise HTTPException(status_code=403, detail="Cannot cancel complaints in another department")

    if reason not in CANCEL_REASONS:
        raise HTTPException(status_code=400, detail="Invalid cancellation reason")

    complaint.status = ComplaintStatus.CANCELLED.value
    complaint.cancel_reason = reason
    complaint.progress_note = f"Admin updated complaint status to Cancelled. Reason: {reason}"
    complaint.estimated_resolution_at = None

    db.commit()
    db.refresh(complaint)

    return RedirectResponse(url="/admin/complaints", status_code=303)


@router.post("/admin/complaints/{complaint_id}/status")
async def update_complaint_status(
    complaint_id: int,
    request: Request,
    status: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Allow admins to apply exception and administrative statuses.
    """
    session = get_admin_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=303)

    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    if complaint.department != session["department"]:
        raise HTTPException(status_code=403, detail="Cannot update complaints in another department")

    if status not in ADMIN_ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid admin status")

    cleaned_reason = reason.strip()
    complaint.status = status
    complaint.estimated_resolution_at = None

    if cleaned_reason:
        complaint.cancel_reason = cleaned_reason
        complaint.progress_note = (
            f"Admin updated complaint status to {_format_status_label(status)}. Reason: {cleaned_reason}"
        )
    elif status in {
        ComplaintStatus.REJECTED.value,
        ComplaintStatus.CANCELLED.value,
        ComplaintStatus.ESCALATED.value,
        ComplaintStatus.REOPENED.value,
    }:
        complaint.progress_note = f"Admin updated complaint status to {_format_status_label(status)}."

    db.commit()
    db.refresh(complaint)

    return RedirectResponse(url="/admin/complaints", status_code=303)


@router.get("/admin/escalated", response_class=HTMLResponse)
async def admin_escalated_complaints(request: Request, db: Session = Depends(get_db)):
    """
    Page for senior officers / department admins to view escalated complaints.

    Shows complaints in the admin's department where status = ESCALATED.
    Escalation is based on complaints that have been pending for more
    than 48 hours after receiving a ticket ID.
    """
    session = get_admin_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=303)

    department = session["department"]

    # Ensure escalation status is up to date.
    escalate_overdue_complaints(db)

    complaints = (
        db.query(Complaint)
        .filter(
            Complaint.department == department,
            Complaint.status == ComplaintStatus.ESCALATED.value,
        )
        .order_by(Complaint.created_at)
        .all()
    )

    return templates.TemplateResponse(
        "admin_escalated.html",
        {
            "request": request,
            "username": session["username"],
            "department": department,
            "complaints": complaints,
            "format_status_label": _format_status_label,
        },
    )
