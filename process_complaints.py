"""
Small CLI script to process complaints from the SQLite database.

Usage:
    python process_complaints.py           # process all unprocessed complaints
    python process_complaints.py --id 3    # process a single complaint by id
"""

import argparse

from classifier import classify_department
from database import SessionLocal
from helpers.complaint_utils import generate_ticket_id
from helpers.worker_utils import assign_worker
from models import Complaint, ComplaintStatus


def process_single_complaint(db, complaint: Complaint) -> dict:
    """Apply the same complaint-processing rules used by the RPA route."""
    if complaint.rpa_processed:
        return {
            "id": complaint.id,
            "status": "SKIPPED",
            "message": "Complaint already processed.",
            "ticket_id": complaint.ticket_id,
            "department": complaint.department,
        }

    department = classify_department(complaint.subject)
    ticket_id = generate_ticket_id(db)

    if department == "General Department":
        complaint.ticket_id = ticket_id
        complaint.department = department
        complaint.rpa_processed = True
        complaint.status = ComplaintStatus.UNDER_REVIEW.value
        complaint.progress_note = (
            "This complaint could not be mapped to a specific operational department and requires admin review."
        )
        complaint.estimated_resolution_at = None
        db.commit()
        db.refresh(complaint)
        return {
            "id": complaint.id,
            "status": complaint.status,
            "ticket_id": complaint.ticket_id,
            "department": complaint.department,
        }

    complaint.ticket_id = ticket_id
    complaint.department = department
    complaint.rpa_processed = True

    worker = assign_worker(db, department)
    if worker:
        complaint.assigned_to = worker
        complaint.status = ComplaintStatus.ASSIGNED.value
        complaint.progress_percent = 0
        complaint.progress_note = "Complaint accepted and assigned to the department team."
        complaint.estimated_resolution_at = None
    else:
        complaint.status = ComplaintStatus.ACCEPTED.value

    db.commit()
    db.refresh(complaint)

    return {
        "id": complaint.id,
        "status": "PROCESSED",
        "ticket_id": complaint.ticket_id,
        "department": complaint.department,
        "assigned_to": complaint.assigned_to,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Process complaints from complaints.db")
    parser.add_argument("--id", type=int, help="Process one complaint by numeric ID")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.id is not None:
            complaint = db.get(Complaint, args.id)
            if complaint is None:
                print(f"Complaint with id={args.id} not found.")
                return

            result = process_single_complaint(db, complaint)
            print(result)
            return

        complaints = (
            db.query(Complaint)
            .filter(Complaint.rpa_processed.is_(False))
            .order_by(Complaint.id)
            .all()
        )

        if not complaints:
            print("No unprocessed complaints found.")
            return

        for complaint in complaints:
            print(process_single_complaint(db, complaint))
    finally:
        db.close()


if __name__ == "__main__":
    main()
