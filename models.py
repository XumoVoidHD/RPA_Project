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

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ESCALATED = "ESCALATED"


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

    status = Column(String(50), nullable=False, default=ComplaintStatus.PENDING.value)
    cancel_reason = Column(String(255), nullable=True)

    # Worker assignment and proof of work
    assigned_to = Column(String(100), nullable=True)  # worker username
    proof_image_path = Column(String(255), nullable=True)
    proof_description = Column(Text, nullable=True)

    # Citizen verification PIN for resolved complaints
    verification_pin = Column(String(10), nullable=True)
    verification_pin_sent_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

