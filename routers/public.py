import os
import random
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from helpers.email_utils import send_email
from models import Complaint, ComplaintStatus


PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "templates"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Render the main complaint submission form.
    """
    return templates.TemplateResponse("index.html", {"request": request})


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

    if complaint.status != ComplaintStatus.RESOLVED.value:
        return JSONResponse({"detail": "Verification can only be requested for resolved complaints."}, status_code=400)

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
    elif complaint.status != ComplaintStatus.RESOLVED.value:
        if complaint.status == ComplaintStatus.CLOSED.value:
            result_message = "This complaint has already been confirmed as resolved."
        elif complaint.status == ComplaintStatus.ESCALATED.value:
            result_message = "This complaint has already been escalated to higher command."
        else:
            result_message = "This complaint cannot be verified in its current status."
    elif not pin or not pin.strip():
        result_message = "A 4-digit PIN is required to verify this complaint."
    elif complaint.verification_pin != pin.strip():
        result_message = "The PIN you entered is incorrect. Please request a new PIN and try again."
    else:
        if action == "confirm":
            complaint.status = ComplaintStatus.CLOSED.value
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
            complaint.status = ComplaintStatus.ESCALATED.value
            result_message = (
                "Your complaint has been re-opened and escalated to higher command. "
                "A department officer will review it again."
            )
            send_email(
                to_email=complaint.email,
                subject="Complaint re-opened and escalated",
                body=(
                    "Dear citizen,\n\n"
                    f"Your complaint (Ticket ID: {complaint.ticket_id}) has been re-opened and escalated to higher command.\n\n"
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
    3. Set status to "PENDING" and created_at automatically via the ORM model.
    4. Return a simple JSON success message.
    """

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
        email=email,
        image_path=image_path_value,
    )

    # Persist complaint to database
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

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

