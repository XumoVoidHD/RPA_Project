from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from classifier import classify_department
from database import get_db
from helpers.complaint_utils import generate_ticket_id
from helpers.email_utils import send_email
from helpers.worker_utils import assign_worker
from models import Complaint, ComplaintStatus


router = APIRouter()


@router.get("/rpa/unprocessed-complaints")
def get_unprocessed_complaints(db: Session = Depends(get_db)):
    """
    Endpoint for the RPA bot.

    Returns complaints that have not yet been processed by RPA
    (rpa_processed = False).
    """
    complaints = (
        db.query(Complaint)
        .filter(Complaint.rpa_processed.is_(False))
        .order_by(Complaint.id)
        .all()
    )

    return [
        {
            "id": c.id,
            "subject": c.subject,
            "description": c.description,
            "location": c.location,
        }
        for c in complaints
    ]


@router.post("/rpa/process-complaint")
def process_complaint(id: int, db: Session = Depends(get_db)):
    """
    Simulate the work done by an RPA bot for a single complaint.

    Steps:
    1. Fetch complaint by id.
    2. Generate ticket_id.
    3. Classify department.
    4. Mark complaint as processed.
    """
    complaint = db.get(Complaint, id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found")

    # If already processed, return existing ticket/department (idempotent behavior)
    if complaint.rpa_processed and complaint.ticket_id and complaint.department:
        return {"ticket_id": complaint.ticket_id, "department": complaint.department}

    ticket_id = generate_ticket_id(db)
    department = classify_department(complaint.subject)

    # If the classifier cannot confidently map to a concrete department,
    # keep the complaint in admin review instead of auto-rejecting it.
    if department == "General Department":
        complaint.department = department
        complaint.rpa_processed = True
        complaint.status = ComplaintStatus.UNDER_REVIEW.value
        complaint.progress_note = (
            "This complaint could not be mapped to a specific operational department and requires admin review."
        )
        complaint.estimated_resolution_at = None
        complaint.assigned_to = None
        complaint.ticket_id = ticket_id
        complaint.rpa_processed = True

        db.commit()
        db.refresh(complaint)

        send_email(
            to_email=complaint.email,
            subject="Your complaint is under review",
            body=(
                "Dear citizen,\n\n"
                "Your complaint has been received and is currently under administrative review.\n"
                f"Temporary Ticket ID: {complaint.ticket_id}\n"
                "Our team could not automatically assign it to a specific department, "
                "so an administrator will review it and decide the next action.\n\n"
                "Thank you for your patience."
            ),
        )

        return {
            "ticket_id": complaint.ticket_id,
            "department": complaint.department,
            "status": complaint.status,
        }

    complaint.ticket_id = ticket_id
    complaint.department = department
    complaint.rpa_processed = True

    # Assign to a worker in this department (round-robin)
    worker = assign_worker(db, department)
    if worker:
        complaint.assigned_to = worker
        complaint.status = ComplaintStatus.ASSIGNED.value
        complaint.progress_percent = 0
        complaint.progress_note = "Complaint accepted and assigned to the department team."
        complaint.estimated_resolution_at = None
    else:
        complaint.status = ComplaintStatus.ACCEPTED.value
        complaint.progress_note = "Complaint accepted, but no worker is currently available for assignment."
        complaint.estimated_resolution_at = None

    db.commit()
    db.refresh(complaint)

    # Notify citizen that the complaint has been accepted and a ticket created.
    send_email(
        to_email=complaint.email,
        subject="Your complaint has been accepted",
        body=(
            "Dear citizen,\n\n"
            "Your complaint has been accepted for processing.\n"
            f"Ticket ID: {complaint.ticket_id}\n"
            f"Department: {complaint.department}\n\n"
            "The complaint has been assigned to the department team.\n\n"
            "Thank you."
        ),
    )

    return {"ticket_id": ticket_id, "department": department}


@router.get("/complaints")
def list_complaints(db: Session = Depends(get_db)):
    """
    Debugging endpoint.

    Returns all complaints along with ticket and department information.
    """
    complaints = db.query(Complaint).order_by(Complaint.id).all()

    result = []
    for c in complaints:
        result.append(
            {
                "id": c.id,
                "subject": c.subject,
                "description": c.description,
                "location": c.location,
                "ticket_id": c.ticket_id,
                "department": c.department,
                "status": c.status,
                "progress_percent": c.progress_percent,
                "progress_note": c.progress_note,
                "estimated_resolution_at": (
                    c.estimated_resolution_at.isoformat()
                    if c.estimated_resolution_at
                    else None
                ),
                "cancel_reason": c.cancel_reason,
                "rpa_processed": c.rpa_processed,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )

    return result

