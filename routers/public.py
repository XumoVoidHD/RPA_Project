import os
import random
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from helpers.email_utils import send_email
from models import CitizenComplaintLink, CitizenLoginOTP, Complaint, ComplaintStatus


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()

CITIZEN_SESSIONS: dict[str, dict[str, str]] = {}


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _get_citizen_session(request: Request) -> dict | None:
    token = request.cookies.get("citizen_session")
    if not token:
        return None
    return CITIZEN_SESSIONS.get(token)


def _format_status_label(value: str) -> str:
    return value.replace("_", " ").title()


def _sync_citizen_links(db: Session, email: str) -> None:
    """
    Ensure the citizen link table reflects complaints already stored with this email.
    """
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return

    linked_ids = {
        row.complaint_id
        for row in db.query(CitizenComplaintLink)
        .filter(CitizenComplaintLink.email == normalized_email)
        .all()
    }

    complaints = (
        db.query(Complaint)
        .filter(func.lower(Complaint.email) == normalized_email)
        .order_by(Complaint.id)
        .all()
    )

    created = False
    for complaint in complaints:
        if complaint.id in linked_ids:
            continue
        db.add(
            CitizenComplaintLink(
                email=normalized_email,
                complaint_id=complaint.id,
            )
        )
        created = True

    if created:
        db.commit()


def _get_grouped_citizen_complaints(db: Session, email: str) -> list[tuple[str, list[Complaint]]]:
    normalized_email = _normalize_email(email)
    _sync_citizen_links(db, normalized_email)

    complaint_ids = [
        row.complaint_id
        for row in db.query(CitizenComplaintLink)
        .filter(CitizenComplaintLink.email == normalized_email)
        .order_by(CitizenComplaintLink.created_at.desc())
        .all()
    ]

    if not complaint_ids:
        return []

    complaints = (
        db.query(Complaint)
        .filter(Complaint.id.in_(complaint_ids))
        .order_by(Complaint.created_at.desc(), Complaint.id.desc())
        .all()
    )

    complaints_by_status: dict[str, list[Complaint]] = {}
    for complaint in complaints:
        complaints_by_status.setdefault(complaint.status, []).append(complaint)

    preferred_order = [
        ComplaintStatus.SUBMITTED.value,
        ComplaintStatus.UNDER_REVIEW.value,
        ComplaintStatus.ACCEPTED.value,
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
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
        ComplaintStatus.REOPENED.value,
        ComplaintStatus.ESCALATED.value,
        ComplaintStatus.REJECTED.value,
        ComplaintStatus.CANCELLED.value,
        ComplaintStatus.CLOSED.value,
        ComplaintStatus.ON_HOLD.value,
        ComplaintStatus.DUPLICATE.value,
        ComplaintStatus.TRANSFERRED.value,
        ComplaintStatus.UNSERVICEABLE.value,
    ]
    status_order = {status: index for index, status in enumerate(preferred_order)}
    ordered_statuses = list(complaints_by_status.keys())
    ordered_statuses.sort(key=lambda status: status_order.get(status, 999))
    return [(status, complaints_by_status[status]) for status in ordered_statuses]


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Render the main complaint submission form.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/citizen/login", response_class=HTMLResponse)
async def citizen_login_form(request: Request):
    """Render the citizen email login page."""
    return templates.TemplateResponse(
        "citizen_login.html",
        {
            "request": request,
            "message": None,
            "error": None,
            "email": "",
        },
    )


@router.post("/citizen/login", response_class=HTMLResponse)
async def citizen_login_send_otp(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    """Issue an OTP to the citizen's email address."""
    normalized_email = _normalize_email(email)
    if not normalized_email:
        return templates.TemplateResponse(
            "citizen_login.html",
            {
                "request": request,
                "message": None,
                "error": "Please enter a valid email address.",
                "email": "",
            },
            status_code=400,
        )

    _sync_citizen_links(db, normalized_email)

    otp = f"{random.randint(100000, 999999):06d}"
    db.query(CitizenLoginOTP).filter(
        CitizenLoginOTP.email == normalized_email,
        CitizenLoginOTP.consumed.is_(False),
    ).update({"consumed": True}, synchronize_session=False)
    db.add(
        CitizenLoginOTP(
            email=normalized_email,
            otp_code=otp,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            consumed=False,
        )
    )
    db.commit()

    send_email(
        to_email=normalized_email,
        subject="Your SmartGov login OTP",
        body=(
            "Dear citizen,\n\n"
            "Use the following one-time password to sign in to your SmartGov complaint dashboard:\n"
            f"{otp}\n\n"
            "This OTP will expire in 10 minutes.\n"
        ),
    )

    return templates.TemplateResponse(
        "citizen_login.html",
        {
            "request": request,
            "message": "We sent a 6-digit OTP to your email address.",
            "error": None,
            "email": normalized_email,
        },
    )


@router.post("/citizen/verify")
async def citizen_verify_otp(
    request: Request,
    email: str = Form(...),
    otp: str = Form(...),
    db: Session = Depends(get_db),
):
    """Validate the citizen OTP and create a simple cookie-based session."""
    normalized_email = _normalize_email(email)
    cleaned_otp = (otp or "").strip()

    record = (
        db.query(CitizenLoginOTP)
        .filter(
            CitizenLoginOTP.email == normalized_email,
            CitizenLoginOTP.consumed.is_(False),
        )
        .order_by(CitizenLoginOTP.created_at.desc())
        .first()
    )

    if (
        record is None
        or record.otp_code != cleaned_otp
        or record.expires_at < datetime.utcnow()
    ):
        return templates.TemplateResponse(
            "citizen_login.html",
            {
                "request": request,
                "message": None,
                "error": "Invalid or expired OTP. Please request a new one.",
                "email": normalized_email,
            },
            status_code=400,
        )

    record.consumed = True
    _sync_citizen_links(db, normalized_email)
    db.commit()

    token = uuid4().hex
    CITIZEN_SESSIONS[token] = {"email": normalized_email}

    response = RedirectResponse(url="/citizen/complaints", status_code=303)
    response.set_cookie("citizen_session", token, httponly=True)
    return response


@router.get("/citizen/complaints", response_class=HTMLResponse)
async def citizen_complaints_dashboard(request: Request, db: Session = Depends(get_db)):
    """Show all complaints linked to the logged-in citizen email."""
    session = _get_citizen_session(request)
    if session is None:
        return RedirectResponse(url="/citizen/login", status_code=303)

    email = session["email"]
    grouped_complaints = _get_grouped_citizen_complaints(db, email)

    return templates.TemplateResponse(
        "citizen_dashboard.html",
        {
            "request": request,
            "email": email,
            "grouped_complaints": grouped_complaints,
            "format_status_label": _format_status_label,
        },
    )


@router.get("/citizen/logout")
async def citizen_logout(request: Request):
    """Clear citizen login session."""
    token = request.cookies.get("citizen_session")
    if token:
        CITIZEN_SESSIONS.pop(token, None)

    response = RedirectResponse(url="/citizen/login", status_code=303)
    response.delete_cookie("citizen_session")
    return response


@router.get("/track", response_class=HTMLResponse)
async def track_complaint(
    request: Request,
    ticket_id: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Page for citizens to enter a ticket ID and view their complaint details.
    GET /track shows the form; GET /track?ticket_id=CMP0001 shows the result.
    """
    complaint = None
    if ticket_id and ticket_id.strip():
        complaint = (
            db.query(Complaint)
            .filter(Complaint.ticket_id == ticket_id.strip().upper())
            .first()
        )
    return templates.TemplateResponse(
        "track.html",
        {
            "request": request,
            "ticket_id": ticket_id or "",
            "complaint": complaint,
            "result_message": None,
        },
    )


@router.get("/track/send-pin")
async def send_verification_pin(
    request: Request,
    ticket_id: str | None = None,
    action: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Send a one-time 4-digit PIN to the citizen's email for verification.
    """
    if not ticket_id or not ticket_id.strip():
        return JSONResponse({"detail": "Ticket ID is required."}, status_code=400)

    if action not in {"confirm", "reject"}:
        return JSONResponse({"detail": "Invalid verification action."}, status_code=400)

    complaint = (
        db.query(Complaint)
        .filter(Complaint.ticket_id == ticket_id.strip().upper())
        .first()
    )

    if complaint is None:
        return JSONResponse({"detail": "Complaint not found."}, status_code=404)

    if complaint.status not in {
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
    }:
        return JSONResponse(
            {"detail": "Verification can only be requested for complaints awaiting confirmation."},
            status_code=400,
        )

    pin = f"{random.randint(1000, 9999):04d}"
    complaint.verification_pin = pin
    complaint.verification_pin_sent_at = datetime.utcnow()
    db.commit()
    db.refresh(complaint)

    send_email(
        to_email=complaint.email,
        subject="Your SmartGov verification PIN",
        body=(
            "Dear citizen,\n\n"
            f"A 4-digit verification PIN has been requested for Ticket ID: {complaint.ticket_id}.\n"
            f"Please use this PIN to verify your response: {pin}\n\n"
            "If you did not request this, please ignore this message.\n"
        ),
    )

    return JSONResponse({"message": "PIN sent to your registered email address."})


@router.get("/track/verify", response_class=HTMLResponse)
async def verify_complaint(
    request: Request,
    ticket_id: str | None = None,
    action: str | None = None,
    pin: str | None = None,
    db: Session = Depends(get_db),
):
    """
    Handle verification actions after the citizen enters their 4-digit PIN.

    If the user confirms the resolution, the complaint is closed.
    If the user reports the issue as still not resolved, the complaint is escalated.
    """
    result_message = None
    complaint = None

    if ticket_id and ticket_id.strip():
        complaint = (
            db.query(Complaint)
            .filter(Complaint.ticket_id == ticket_id.strip().upper())
            .first()
        )

    if complaint is None:
        result_message = "No complaint found for the provided ticket ID."
        return templates.TemplateResponse(
            "track.html",
            {
                "request": request,
                "ticket_id": ticket_id or "",
                "complaint": None,
                "result_message": result_message,
            },
        )

    if action not in {"confirm", "reject"}:
        result_message = "Invalid verification action."
    elif complaint.status not in {
        ComplaintStatus.RESOLUTION_PENDING_CONFIRMATION.value,
        ComplaintStatus.RESOLVED.value,
    }:
        if complaint.status == ComplaintStatus.CLOSED.value:
            result_message = "This complaint has already been confirmed as resolved."
        elif complaint.status == ComplaintStatus.ESCALATED.value:
            result_message = "This complaint has already been escalated to higher command."
        elif complaint.status == ComplaintStatus.REOPENED.value:
            result_message = "This complaint has been re-opened and is awaiting department review."
        else:
            result_message = "This complaint cannot be verified in its current status."
    elif not pin or not pin.strip():
        result_message = "A 4-digit PIN is required to verify this complaint."
    elif complaint.verification_pin != pin.strip():
        result_message = "The PIN you entered is incorrect. Please request a new PIN and try again."
    else:
        if action == "confirm":
            complaint.status = ComplaintStatus.CLOSED.value
            complaint.progress_note = "Citizen confirmed that the issue has been resolved."
            complaint.estimated_resolution_at = None
            result_message = "Thank you. Your complaint has been confirmed as resolved and is now closed."
            send_email(
                to_email=complaint.email,
                subject="Complaint verified and closed",
                body=(
                    "Dear citizen,\n\n"
                    f"We have received your confirmation for Ticket ID: {complaint.ticket_id}.\n"
                    "Your complaint is now marked as closed.\n\n"
                    "Thank you for verifying the resolution.\n"
                ),
            )
        elif action == "reject":
            complaint.status = ComplaintStatus.REOPENED.value
            complaint.progress_note = (
                "Citizen reported that the issue is still not resolved. Complaint re-opened for admin review."
            )
            complaint.estimated_resolution_at = None
            result_message = (
                "Your complaint has been re-opened. "
                "A department officer will review it again."
            )
            send_email(
                to_email=complaint.email,
                subject="Complaint re-opened for review",
                body=(
                    "Dear citizen,\n\n"
                    f"Your complaint (Ticket ID: {complaint.ticket_id}) has been re-opened for administrative review.\n\n"
                    "We will review the issue again and keep you updated.\n\n"
                    "Thank you for your feedback.\n"
                ),
            )
        complaint.verification_pin = None
        complaint.verification_pin_sent_at = None
        db.commit()
        db.refresh(complaint)

    return templates.TemplateResponse(
        "track.html",
        {
            "request": request,
            "ticket_id": ticket_id or "",
            "complaint": complaint,
            "result_message": result_message,
        },
    )


@router.post("/submit-complaint")
async def submit_complaint(
    subject: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
    email: str = Form(...),
    image: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    """
    Handle complaint form submission.

    Steps:
    1. Optionally save uploaded image with a unique filename inside /uploads.
    2. Store complaint data in the SQLite database.
    3. Set status to "SUBMITTED" and created_at automatically via the ORM model.
    4. Return a simple JSON success message.
    """

    normalized_email = _normalize_email(email)
    image_path_value: str | None = None

    # Save the uploaded file (if provided) to the uploads directory
    if image is not None and image.filename:
        original_extension = Path(image.filename).suffix
        unique_name = f"{uuid4().hex}{original_extension}"
        save_path = UPLOAD_DIR / unique_name

        # Persist the file to disk
        with save_path.open("wb") as buffer:
            shutil.copyfileobj(image.file, buffer)

        # Store a relative path to keep the DB value simple
        image_path_value = f"uploads/{unique_name}"

    # Create Complaint object; status and created_at use model defaults
    complaint = Complaint(
        subject=subject,
        description=description,
        location=location,
        email=normalized_email,
        image_path=image_path_value,
    )

    # Persist complaint to database
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    db.add(
        CitizenComplaintLink(
            email=normalized_email,
            complaint_id=complaint.id,
        )
    )
    db.commit()

    # Send an acknowledgement email to the citizen.
    send_email(
        to_email=complaint.email,
        subject="Your complaint has been received",
        body=(
            "Dear citizen,\n\n"
            "Your complaint has been received by the SmartGov system.\n"
            "You will receive another email once your complaint is accepted "
            "for processing and a ticket ID has been generated.\n\n"
            "Thank you."
        ),
    )

    # Response is intentionally minimal JSON as requested
    return {"message": "Complaint submitted successfully"}

