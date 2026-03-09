"""
Worker credentials and assignment logic.

Workers are stored in workers.json (username -> password, department).
By default there are 2 workers per department; assignment uses round-robin
within the department.
"""

import json
from pathlib import Path
from typing import Dict

from fastapi import Request


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKERS_PATH = PROJECT_ROOT / "workers.json"


def _load_workers() -> Dict[str, Dict[str, str]]:
    """Load workers from workers.json. Format: username -> { password, department }."""
    if WORKERS_PATH.exists():
        with WORKERS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


WORKERS: Dict[str, Dict[str, str]] = _load_workers()
WORKER_SESSIONS: Dict[str, Dict[str, str]] = {}


def get_workers_for_department(department: str) -> list[str]:
    """Return list of worker usernames for the given department (order preserved for round-robin)."""
    return [u for u, d in WORKERS.items() if d.get("department") == department]


def assign_worker(db, department: str) -> str | None:
    """
    Pick the next worker for this department using round-robin:
    count how many complaints are already assigned to each worker in this department,
    then assign to the one with the fewest (or first if tie).
    Returns worker username or None if no workers for department.
    """
    from models import Complaint

    usernames = get_workers_for_department(department)
    if not usernames:
        return None

    # Count current assignments per worker in this department
    counts = {}
    for u in usernames:
        counts[u] = (
            db.query(Complaint)
            .filter(
                Complaint.department == department,
                Complaint.assigned_to == u,
                Complaint.status != "CANCELLED",
            )
            .count()
        )

    # Assign to worker with smallest count (first in list if tie)
    return min(usernames, key=lambda u: counts[u])


def get_worker_session(request: Request) -> dict | None:
    """Return current worker session from cookie, or None if not logged in."""
    token = request.cookies.get("worker_session")
    if not token:
        return None
    return WORKER_SESSIONS.get(token)
