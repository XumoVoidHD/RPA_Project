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

from pathlib import Path

from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import Base, engine
from migrations import ensure_complaints_table_columns
from routers import admin, public, rpa, worker


# Base directory of this project file (same folder as .env)
BASE_DIR = Path(__file__).resolve().parent

# Load .env from same directory as main.py so SMTP_* and FROM_EMAIL are available
load_dotenv(BASE_DIR / ".env")

# FastAPI application instance
app = FastAPI(title="SmartGov – RPA Bot for Public Complaint Registration")


@app.on_event("startup")
def on_startup() -> None:
    """
    Application startup hook.

    - Creates all database tables (if they do not already exist).
    - Applies SQLite additive migrations for older complaint DB files.
    """
    Base.metadata.create_all(bind=engine)
    ensure_complaints_table_columns(engine)


# Serve uploaded complaint images and worker proof images
app.mount("/uploads", StaticFiles(directory=BASE_DIR / "uploads"), name="uploads")

# Include routers grouped by area
app.include_router(public.router)
app.include_router(rpa.router)
app.include_router(admin.router)
app.include_router(worker.router)

