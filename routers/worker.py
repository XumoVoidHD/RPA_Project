"""
Worker portal: login, view assigned tasks, complete work with proof upload.

Workers see only complaints assigned to them (assigned_to = username).
When they complete a task they upload a proof image and description;
complaint status moves to RESOLUTION_PENDING_CONFIRMATION and the citizen receives an email.
"""

import os
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from helpers.email_utils import send_email
from helpers.worker_utils import WORKER_SESSIONS, WORKERS, get_worker_session
from models import Complaint, ComplaintStatus, WORKER_ALLOWED_STATUSES


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
PROOFS_DIR = PROJECT_ROOT / "uploads" / "proofs"
os.makedirs(PROOFS_DIR, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


def _parse_estimated_resolution_at(value: str | None) -> datetime | None:
    """Parse the datetime-local field used by the worker update form."""
    if value is None:
        return None

    cleaned = value.strip()
    if not cleaned:
        return None

    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid estimated resolution time") from exc


WORKER_UPDATE_STATUS_CHOICES = [
    ComplaintStatus.ASSIGNED.value,
    ComplaintStatus.VISIT_SCHEDULED.value,
    ComplaintStatus.VISIT_IN_PROGRESS.value,
    ComplaintStatus.VISIT_COMPLETED.value,
    ComplaintStatus.WORK_PLANNED.value,
    ComplaintStatus.WORK_IN_PROGRESS.value,
    ComplaintStatus.PARTIALLY_RESOLVED.value,
    ComplaintStatus.WAITING_FOR_MATERIALS.value,
    ComplaintStatus.WAITING_FOR_APPROVAL.value,
    ComplaintStatus.WAITING_FOR_BUDGET.value,
    ComplaintStatus.WAITING_FOR_OTHER_DEPARTMENT.value,
    ComplaintStatus.WAITING_FOR_CITIZEN_RESPONSE.value,
    ComplaintStatus.WAITING_FOR_ACCESS.value,
    ComplaintStatus.WEATHER_DELAY.value,
    ComplaintStatus.VENDOR_PENDING.value,
    ComplaintStatus.FOLLOW_UP_REQUIRED.value,
]


def _format_status_label(value: str) -> str:
    """Convert enum-like values into friendly labels for templates."""
    return value.replace("_", " ").title()


@router.get("/worker/login", response_class=HTMLResponse)
async def worker_login_form(request: Request):
    """Render the worker login page."""
    return templates.TemplateResponse(
        "worker_login.html",
        {"request": request, "error": None},
    )


@router.post("/worker/login")
async def worker_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """Validate worker credentials, set session cookie, redirect to tasks."""
    user = WORKERS.get(username)
    if user is None or user["password"] != password:
        return templates.TemplateResponse(
            "worker_login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )

    token = uuid4().hex
    WORKER_SESSIONS[token] = {
        "username": username,
        "department": user["department"],
    }

    response = RedirectResponse(url="/worker/tasks", status_code=303)
    response.set_cookie("worker_session", token, httponly=True)
    return response


@router.get("/worker/logout")
async def worker_logout(request: Request):
    """Clear worker session and redirect to login."""
    token = request.cookies.get("worker_session")
    if token:
        WORKER_SESSIONS.pop(token, None)

    response = RedirectResponse(url="/worker/login", status_code=303)
    response.delete_cookie("worker_session")
    return response


@router.get("/worker/tasks", response_class=HTMLResponse)
async def worker_tasks(request: Request, db: Session = Depends(get_db)):
    """List complaints assigned to the logged-in worker that are still active."""
    session = get_worker_session(request)
    if session is None:
        return RedirectResponse(url="/worker/login", status_code=303)

    username = session["username"]

    tasks = (
        db.query(Complaint)
        .filter(
            Complaint.assigned_to == username,
            Complaint.status.notin_(
                [
                    ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
                    ComplaintStatus.RESOLVED.value,
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
            ),
        )
        .order_by(Complaint.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "worker_tasks.html",
        {
            "request": request,
            "username": username,
            "department": session["department"],
            "tasks": tasks,
            "format_status_label": _format_status_label,
        },
    )


@router.get("/worker/complete/{complaint_id}", response_class=HTMLResponse)
async def worker_complete_form(
    request: Request,
    complaint_id: int,
    db: Session = Depends(get_db),
):
    """Show progress update and completion controls for a complaint."""
    session = get_worker_session(request)
    if session is None:
        return RedirectResponse(url="/worker/login", status_code=303)

    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.assigned_to != session["username"]:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if complaint.status in {
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
    }:
        raise HTTPException(status_code=400, detail="Complaint already resolved")
    if complaint.status in {
        ComplaintStatus.REJECTED.value,
        ComplaintStatus.CANCELLED.value,
        ComplaintStatus.ESCALATED.value,
        ComplaintStatus.REOPENED.value,
        ComplaintStatus.ON_HOLD.value,
        ComplaintStatus.DUPLICATE.value,
        ComplaintStatus.TRANSFERRED.value,
        ComplaintStatus.UNSERVICEABLE.value,
        ComplaintStatus.CLOSED.value,
    }:
        raise HTTPException(status_code=400, detail="Complaint can no longer be updated")

    return templates.TemplateResponse(
        "worker_complete.html",
        {
            "request": request,
            "complaint": complaint,
            "status_choices": WORKER_UPDATE_STATUS_CHOICES,
            "format_status_label": _format_status_label,
        },
    )


@router.post("/worker/update/{complaint_id}")
async def worker_update_progress(
    request: Request,
    complaint_id: int,
    status: str = Form(...),
    progress_note: str = Form(...),
    estimated_resolution_at: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Allow a worker to update the complaint's progress while work is underway.
    """
    session = get_worker_session(request)
    if session is None:
        return RedirectResponse(url="/worker/login", status_code=303)

    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.assigned_to != session["username"]:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if complaint.status in {
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
        ComplaintStatus.REJECTED.value,
        ComplaintStatus.CANCELLED.value,
        ComplaintStatus.ESCALATED.value,
        ComplaintStatus.REOPENED.value,
        ComplaintStatus.ON_HOLD.value,
        ComplaintStatus.DUPLICATE.value,
        ComplaintStatus.TRANSFERRED.value,
        ComplaintStatus.UNSERVICEABLE.value,
        ComplaintStatus.CLOSED.value,
    }:
        raise HTTPException(status_code=400, detail="Complaint can no longer be updated")

    if status not in WORKER_ALLOWED_STATUSES or status == ComplaintStatus.RESOLVED.value:
        raise HTTPException(status_code=400, detail="Invalid worker status")

    cleaned_note = progress_note.strip()
    if not cleaned_note:
        raise HTTPException(status_code=400, detail="Progress update cannot be empty")

    complaint.progress_note = cleaned_note
    complaint.estimated_resolution_at = _parse_estimated_resolution_at(estimated_resolution_at)
    complaint.status = status

    db.commit()

    return RedirectResponse(url="/worker/tasks", status_code=303)


@router.post("/worker/complete/{complaint_id}")
async def worker_complete_submit(
    request: Request,
    complaint_id: int,
    description: str = Form(...),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """
    Save proof image and description, move status to awaiting verification, and send a verification email to the citizen.
    """
    session = get_worker_session(request)
    if session is None:
        return RedirectResponse(url="/worker/login", status_code=303)

    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")
    if complaint.assigned_to != session["username"]:
        raise HTTPException(status_code=403, detail="Not assigned to you")
    if complaint.status in {
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
    }:
        raise HTTPException(status_code=400, detail="Complaint already resolved")
    if complaint.status in {
        ComplaintStatus.REJECTED.value,
        ComplaintStatus.CANCELLED.value,
        ComplaintStatus.ESCALATED.value,
        ComplaintStatus.REOPENED.value,
        ComplaintStatus.ON_HOLD.value,
        ComplaintStatus.DUPLICATE.value,
        ComplaintStatus.TRANSFERRED.value,
        ComplaintStatus.UNSERVICEABLE.value,
        ComplaintStatus.CLOSED.value,
    }:
        raise HTTPException(status_code=400, detail="Complaint can no longer be resolved")

    proof_image_path_value = None
    if image and image.filename:
        ext = Path(image.filename).suffix
        unique_name = f"{uuid4().hex}{ext}"
        save_path = PROOFS_DIR / unique_name
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        proof_image_path_value = f"uploads/proofs/{unique_name}"

    complaint.proof_image_path = proof_image_path_value
    complaint.proof_description = description
    complaint.progress_note = "Work completed. Awaiting citizen verification."
    complaint.estimated_resolution_at = None
    complaint.status = ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value

    db.commit()
    db.refresh(complaint)

    verification_base = str(request.base_url).rstrip("/")
    confirm_url = f"{verification_base}/track/verify?ticket_id={complaint.ticket_id}&action=confirm"
    reject_url = f"{verification_base}/track/verify?ticket_id={complaint.ticket_id}&action=reject"

    send_email(
        to_email=complaint.email,
        subject="Your complaint is ready for verification",
        body=(
            "Dear citizen,\n\n"
            f"Your complaint (Ticket ID: {complaint.ticket_id}) has been marked as completed by the assigned team.\n\n"
            "Please verify that the issue has been addressed: \n"
            f"Confirm resolution: {confirm_url}\n"
            f"If the problem is still not resolved, report it here: {reject_url}\n\n"
            "If you do not take any action, the complaint will remain pending your verification.\n\n"
            "Thank you for using SmartGov.\n"
        ),
    )

    return RedirectResponse(url="/worker/tasks", status_code=303)
