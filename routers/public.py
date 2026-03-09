import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from helpers.email_utils import send_email
from models import Complaint


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
        {"request": request, "ticket_id": ticket_id or "", "complaint": complaint},
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

