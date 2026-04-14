from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from database import Base


class ComplaintStatus(str, Enum):
    """
    Enumeration for complaint status values.
    Centralised here so the rest of the codebase can refer to a
    single source of truth instead of hard-coding strings.
    """

    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    ASSIGNED = "ASSIGNED"
    VISIT_SCHEDULED = "VISIT_SCHEDULED"
    VISIT_IN_PROGRESS = "VISIT_IN_PROGRESS"
    VISIT_COMPLETED = "VISIT_COMPLETED"
    WORK_PLANNED = "WORK_PLANNED"
    WORK_IN_PROGRESS = "WORK_IN_PROGRESS"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    WAITING_FOR_MATERIALS = "WAITING_FOR_MATERIALS"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    WAITING_FOR_BUDGET = "WAITING_FOR_BUDGET"
    WAITING_FOR_OTHER_DEPARTMENT = "WAITING_FOR_OTHER_DEPARTMENT"
    WAITING_FOR_CITIZEN_RESPONSE = "WAITING_FOR_CITIZEN_RESPONSE"
    WAITING_FOR_ACCESS = "WAITING_FOR_ACCESS"
    WEATHER_DELAY = "WEATHER_DELAY"
    VENDOR_PENDING = "VENDOR_PENDING"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    RESOLUTION_PENDING_CONFIRMATION = "RESOLUTION_PENDING_CONFIRMATION"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"
    REOPENED = "REOPENED"
    ON_HOLD = "ON_HOLD"
    DUPLICATE = "DUPLICATE"
    TRANSFERRED = "TRANSFERRED"
    UNSERVICEABLE = "UNSERVICEABLE"


WORKER_ALLOWED_STATUSES = {
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
}


ADMIN_ALLOWED_STATUSES = {
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
}


FINAL_STATUSES = {
    ComplaintStatus.CLOSED.value,
    ComplaintStatus.CANCELLED.value,
    ComplaintStatus.REJECTED.value,
}


ADMIN_EXCEPTION_STATUSES = {
    ComplaintStatus.REJECTED.value,
    ComplaintStatus.CANCELLED.value,
    ComplaintStatus.ESCALATED.value,
    ComplaintStatus.REOPENED.value,
}


class Complaint(Base):
    """
    ORM model for the complaints table.
    Stores basic complaint details and metadata.

    Extended with fields used by the RPA bot integration.
    """

    __tablename__ = "complaints"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    location = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    image_path = Column(String(255), nullable=True)

    # RPA-related fields
    ticket_id = Column(String(50), unique=True, nullable=True)
    department = Column(String(100), nullable=True)
    rpa_processed = Column(Boolean, nullable=False, default=False)

    status = Column(String(50), nullable=False, default=ComplaintStatus.SUBMITTED.value)
    cancel_reason = Column(String(255), nullable=True)

    # Worker assignment and proof of work
    assigned_to = Column(String(100), nullable=True)  # worker username
    progress_percent = Column(Integer, nullable=False, default=0)
    progress_note = Column(Text, nullable=True)
    estimated_resolution_at = Column(DateTime, nullable=True)
    proof_image_path = Column(String(255), nullable=True)
    proof_description = Column(Text, nullable=True)

    # Citizen verification PIN for resolved complaints
    verification_pin = Column(String(10), nullable=True)
    verification_pin_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CitizenComplaintLink(Base):
    """
    Persistent mapping between a citizen email address and complaint records.
    """

    __tablename__ = "citizen_complaint_links"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, index=True)
    complaint_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CitizenLoginOTP(Base):
    """
    One-time login codes issued to citizen email addresses.
    """

    __tablename__ = "citizen_login_otps"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String(255), nullable=False, index=True)
    otp_code = Column(String(10), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
