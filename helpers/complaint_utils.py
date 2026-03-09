from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from models import Complaint, ComplaintStatus


def generate_ticket_id(db: Session) -> str:
    """
    Generate the next ticket ID in the form CMP0001, CMP0002, ...

    The sequence is based on how many complaints already have a ticket_id.
    """
    count_with_ticket = db.query(Complaint).filter(Complaint.ticket_id.isnot(None)).count()
    next_number = count_with_ticket + 1
    return f"CMP{next_number:04d}"


def escalate_overdue_complaints(db: Session) -> None:
    """
    Escalate complaints that have been pending for more than 48 hours.

    A complaint is eligible for escalation if:
      - It has a ticket_id (i.e. was accepted for processing).
      - Its status is still PENDING.
      - created_at is older than 48 hours from now.

    Escalation is represented by setting status = ESCALATED.
    """
    cutoff = datetime.utcnow() - timedelta(hours=48)
    overdue = (
        db.query(Complaint)
        .filter(
            Complaint.ticket_id.isnot(None),
            Complaint.status == ComplaintStatus.PENDING.value,
            Complaint.created_at <= cutoff,
        )
        .all()
    )

    if not overdue:
        return

    for complaint in overdue:
        complaint.status = ComplaintStatus.ESCALATED.value

    db.commit()

