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
    Escalate active complaints that have been open for more than 48 hours.

    A complaint is eligible for escalation if:
      - It has a ticket_id (i.e. was accepted for processing).
      - Its status is still in an active worker/admin state.
      - created_at is older than 48 hours from now.

    Escalation is represented by setting status = ESCALATED.
    """
    cutoff = datetime.utcnow() - timedelta(hours=48)
    overdue = (
        db.query(Complaint)
        .filter(
            Complaint.ticket_id.isnot(None),
            Complaint.status.in_(
                [
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
                    ComplaintStatus.REOPENED.value,
                ]
            ),
            Complaint.created_at <= cutoff,
        )
        .all()
    )

    if not overdue:
        return

    for complaint in overdue:
        complaint.status = ComplaintStatus.ESCALATED.value
        if not complaint.progress_note:
            complaint.progress_note = "Complaint automatically escalated after exceeding the expected response window."
        complaint.estimated_resolution_at = None

    db.commit()

