import json
from pathlib import Path
from typing import Dict

from fastapi import Request


# Project root is one level above this helpers package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADMIN_USERS_PATH = PROJECT_ROOT / "admin_users.json"


def _load_admin_users() -> Dict[str, Dict[str, str]]:
    """
    Load admin users from the JSON file.

    Format:
      {
        "username": { "password": "...", "department": "..." },
        ...
      }
    """
    if ADMIN_USERS_PATH.exists():
        with ADMIN_USERS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# In-memory admin user store and session store.
ADMIN_USERS: Dict[str, Dict[str, str]] = _load_admin_users()
ADMIN_SESSIONS: Dict[str, Dict[str, str]] = {}

# Fixed set of reasons an admin can select when cancelling a complaint.
CANCEL_REASONS = [
    "Doesn't belong to the department",
    "Unable to accept image",
    "Rejected by the authorities",
]


def get_admin_session(request: Request) -> dict | None:
    """
    Helper to retrieve the current admin session data from the cookie.
    Returns None if the user is not logged in.
    """
    token = request.cookies.get("admin_session")
    if not token:
        return None
    return ADMIN_SESSIONS.get(token)

