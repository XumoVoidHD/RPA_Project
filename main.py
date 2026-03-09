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
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session

from classifier import classify_department
from database import Base, engine, get_db
from models import Complaint, ComplaintStatus


# Base directory of this project file
BASE_DIR = Path(__file__).resolve().parent

# Directory where uploaded images will be stored
UPLOAD_DIR = BASE_DIR / "uploads"

# Ensure the uploads directory exists at startup
os.makedirs(UPLOAD_DIR, exist_ok=True)

# FastAPI application instance
app = FastAPI(title="SmartGov – RPA Bot for Public Complaint Registration")

# Jinja2 templates configuration (for serving the HTML form)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Path to JSON file holding admin credentials and departments.
ADMIN_USERS_PATH = BASE_DIR / "admin_users.json"


def _load_admin_users() -> dict:
    """
    Load admin users from a JSON file.

    This keeps credentials out of the source code.
    """
    if ADMIN_USERS_PATH.exists():
        with ADMIN_USERS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# In-memory admin user store and session store.
ADMIN_USERS = _load_admin_users()
ADMIN_SESSIONS: dict = {}


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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """
    Render the main complaint submission form.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_form(request: Request):
    """
    Render the admin login page.

    Different admin accounts correspond to different departments.
    """
    return templates.TemplateResponse(
        "admin_login.html",
        {"request": request, "error": None},
    )


@app.post("/admin/login")
async def admin_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    """
    Handle admin login.

    If credentials are valid, a simple session token is created and
    stored in memory, and a cookie is set so only logged-in admins
    can access the department complaints page.
    """
    user = ADMIN_USERS.get(username)
    if user is None or user["password"] != password:
        return templates.TemplateResponse(
            "admin_login.html",
            {"request": request, "error": "Invalid username or password."},
            status_code=401,
        )

    token = uuid4().hex
    ADMIN_SESSIONS[token] = {
        "username": username,
        "department": user["department"],
    }

    response = RedirectResponse(url="/admin/complaints", status_code=303)
    response.set_cookie("admin_session", token, httponly=True)
    return response


@app.get("/admin/logout")
async def admin_logout(request: Request):
    """
    Clear admin session and redirect back to the login page.
    """
    token = request.cookies.get("admin_session")
    if token:
        ADMIN_SESSIONS.pop(token, None)

    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie("admin_session")
    return response


@app.post("/submit-complaint")
async def submit_complaint(
    subject: str = Form(...),
    description: str = Form(...),
    location: str = Form(...),
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
        image_path=image_path_value,
    )

    # Persist complaint to database
    db.add(complaint)
    db.commit()
    db.refresh(complaint)

    # Response is intentionally minimal JSON as requested
    return {"message": "Complaint submitted successfully"}


def _generate_ticket_id(db: Session) -> str:
    """
    Generate the next ticket ID in the form CMP0001, CMP0002, ...

    The sequence is based on how many complaints already have a ticket_id.
    """
    count_with_ticket = db.query(Complaint).filter(Complaint.ticket_id.isnot(None)).count()
    next_number = count_with_ticket + 1
    return f"CMP{next_number:04d}"


@app.get("/rpa/unprocessed-complaints")
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


def _get_admin_session(request: Request):
    """
    Helper to retrieve the current admin session data from the cookie.
    Returns None if the user is not logged in.
    """
    token = request.cookies.get("admin_session")
    if not token:
        return None
    return ADMIN_SESSIONS.get(token)


@app.post("/rpa/process-complaint")
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

    ticket_id = _generate_ticket_id(db)
    department = classify_department(complaint.subject)

    complaint.ticket_id = ticket_id
    complaint.department = department
    complaint.rpa_processed = True

    db.commit()
    db.refresh(complaint)

    return {"ticket_id": ticket_id, "department": department}


@app.get("/complaints")
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
                "rpa_processed": c.rpa_processed,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
        )

    return result


@app.get("/admin/complaints", response_class=HTMLResponse)
async def admin_complaints(request: Request, db: Session = Depends(get_db)):
    """
    Web page for department admins.

    Shows only the complaints that belong to the admin's department.
    """
    session = _get_admin_session(request)
    if session is None:
        return RedirectResponse(url="/admin/login", status_code=303)

    department = session["department"]

    complaints = (
        db.query(Complaint)
        .filter(Complaint.department == department)
        .order_by(Complaint.id.desc())
        .all()
    )

    return templates.TemplateResponse(
        "admin_complaints.html",
        {
            "request": request,
            "username": session["username"],
            "department": department,
            "complaints": complaints,
        },
    )

