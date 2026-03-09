"""
SmartGov – RPA Bot for Public Complaint Registration (Minimal Prototype)

HOW TO RUN THIS PROJECT
-----------------------
1. Install dependencies (preferably in a virtual environment):
   pip install -r requirements.txt
   # or, equivalently:
   pip install fastapi uvicorn sqlalchemy python-multipart jinja2

2. Start the development server:
   uvicorn main:app --reload

3. Open the application in your browser:
   http://localhost:8000

This application is intentionally minimal and meant to run only on localhost.
It exposes:
  - GET  /                -> HTML complaint submission form
  - POST /submit-complaint -> Accepts form data, stores complain in SQLite, saves optional image
"""

import json
import os
import shutil
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

from fastapi import FastAPI
from sqlalchemy import text

from database import Base, engine
from routers import admin, public, rpa


# Base directory of this project file (same folder as .env)
BASE_DIR = Path(__file__).resolve().parent

# Load .env from same directory as main.py so SMTP_* and FROM_EMAIL are available
load_dotenv(BASE_DIR / ".env")

# FastAPI application instance
app = FastAPI(title="SmartGov – RPA Bot for Public Complaint Registration")

def _ensure_additional_columns() -> None:
    """
    Very small, manual migration step for SQLite.

    Ensures that the complaints table has the extra columns required
    for RPA processing. If the columns already exist, errors are
    ignored so the app can start normally.
    """
    statements = [
        "ALTER TABLE complaints ADD COLUMN ticket_id VARCHAR(50)",
        "ALTER TABLE complaints ADD COLUMN department VARCHAR(100)",
        "ALTER TABLE complaints ADD COLUMN rpa_processed BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN cancel_reason VARCHAR(255)",
        "ALTER TABLE complaints ADD COLUMN email VARCHAR(255) NOT NULL DEFAULT ''",
    ]

    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception:
                # Column likely already exists; ignore the error.
                pass


@app.on_event("startup")
def on_startup() -> None:
    """
    Application startup hook.

    - Creates all database tables (if they do not already exist).
    - Applies a tiny manual migration to add RPA-related columns.
    """
    Base.metadata.create_all(bind=engine)
    _ensure_additional_columns()


# Include routers grouped by area
app.include_router(public.router)
app.include_router(rpa.router)
app.include_router(admin.router)

