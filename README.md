# SmartGov – RPA Bot for Public Complaint Registration

A minimal local complaint registration system for citizens, with RPA-style processing and department-specific admin views. Runs on **localhost only**; no production deployment assumed.

---

## Tech stack

| Layer      | Technology                    |
|-----------|-------------------------------|
| Backend   | Python, FastAPI, SQLite, SQLAlchemy, Uvicorn |
| Frontend  | Plain HTML, minimal CSS, vanilla JavaScript   |
| Email     | SMTP (configurable via `.env`)                |

---

## Project structure

```
rpaProject/
├── main.py              # FastAPI app, startup, static mounts, routers
├── database.py          # SQLite engine, session, get_db
├── migrations.py        # SQLite ALTER TABLE for older complaint DBs
├── models.py            # Complaint model, ComplaintStatus enum
├── classifier.py        # Keyword-based department classifier
├── admin_users.json     # Admin credentials (username → password, department)
├── workers.json         # Worker credentials (username → password, department), 2 per department
├── .env                 # SMTP and other env config (not committed)
├── requirements.txt     # Python dependencies
├── complaints.db        # SQLite DB (created on first run)
├── uploads/             # Uploaded complaint images
├── uploads/proofs/      # Proof-of-work images uploaded by workers
├── routers/
│   ├── public.py        # Citizen form, submit, track
│   ├── rpa.py           # RPA process, assign worker
│   ├── admin.py         # Admin login, complaints, cancel
│   └── worker.py        # Worker login, tasks, complete (proof + description)
├── helpers/
│   ├── admin_utils.py   # Admin sessions, cancel reasons
│   ├── worker_utils.py  # Worker load, assignment (round-robin)
│   ├── complaint_utils.py
│   └── email_utils.py
└── templates/
    ├── index.html           # Citizen complaint form
    ├── admin_login.html     # Admin login page
    ├── admin_complaints.html # Department complaints + cancel actions
    ├── worker_login.html    # Worker login page
    ├── worker_tasks.html    # Worker’s assigned tasks list
    └── worker_complete.html # Complete task: proof image + description
```

---

## Setup and run

### 1. Prerequisites

- Python 3.10+
- Virtual environment (recommended)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

Or manually:

```bash
pip install fastapi uvicorn sqlalchemy python-multipart jinja2 python-dotenv
```

### 3. Configure environment

Copy or create a `.env` file in the **same directory as `main.py`** with:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_USE_TLS=1
FROM_EMAIL=your_email@gmail.com
```

- For **Gmail**: use an [App Password](https://support.google.com/accounts/answer/185833) (2-Step Verification must be on).
- If `.env` is missing or SMTP vars are empty, the app still runs but skips sending emails (logs “Email not configured”).

### 4. Start the server

```bash
uvicorn main:app --reload
```

### 5. Open in browser

| Page            | URL                        |
|-----------------|----------------------------|
| Citizen form    | http://localhost:8000      |
| Track status    | http://localhost:8000/track?ticket_id=*CMP0001* (use your ticket ID) |
| Admin login     | http://localhost:8000/admin/login |
| Worker login    | http://localhost:8000/worker/login |
| API docs        | http://localhost:8000/docs |

---

## Database

- **File:** `complaints.db` (SQLite, created in project root on first run).
- **Table:** `complaints`

| Column          | Type     | Description |
|-----------------|----------|-------------|
| id              | integer  | Primary key, auto-increment |
| subject         | string   | Complaint subject |
| description     | text     | Complaint description |
| location        | string   | Location |
| email           | string   | Citizen email (for notifications) |
| image_path      | string   | Optional path under `uploads/` |
| ticket_id       | string   | e.g. CMP0001 (set after RPA process) |
| department      | string   | Set by classifier when processed |
| rpa_processed   | boolean  | Default false |
| status          | string   | PENDING, IN_PROGRESS, RESOLVED, CLOSED, CANCELLED |
| cancel_reason   | string   | Set when admin cancels |
| assigned_to     | string   | Worker username (set when RPA processes complaint) |
| proof_image_path| string   | Path under uploads/proofs/ (set when worker completes task) |
| proof_description | text  | Worker’s completion notes |
| created_at      | datetime | Auto-set on insert |

Startup migration in `migrations.py` adds missing columns (e.g. `ticket_id`, `department`, `rpa_processed`, `cancel_reason`, `email`, `assigned_to`, `proof_image_path`, `proof_description`) if the table already existed from an older version.

---

## Flows

### 1. Citizen submits complaint

1. User opens **http://localhost:8000** and fills the form (subject, description, location, **email**, optional image).
2. **POST /submit-complaint** saves the complaint with `status=PENDING`, `rpa_processed=false`.
3. **Email 1** is sent (if SMTP is configured): *“Your complaint has been received… You will receive another email once your complaint is accepted for processing.”*

### 2. RPA bot processes complaints

1. Bot calls **GET /rpa/unprocessed-complaints** → list of complaints with `rpa_processed=false`.
2. For each complaint, bot calls **POST /rpa/process-complaint?id=&lt;id&gt;**.
3. Backend:
   - Classifies **department** from subject via `classifier.classify_department(subject)`.
   - If department is **General Department** (no keyword match):
     - Sets `status=CANCELLED`, `cancel_reason="Doesn't belong to the department"`, `rpa_processed=true`.
     - **Email 2a** (rejection): *“Your complaint could not be accepted… doesn’t match any specific department.”*
     - Returns `{"status": "REJECTED", "reason": "..."}`.
   - If department is a real one (Public Works, Sanitation, etc.):
     - Generates **ticket_id** (CMP0001, CMP0002, …), sets `department`, `rpa_processed=true`.
     - **Assigns a worker** from that department (round-robin via `workers.json`); sets `complaint.assigned_to`.
     - **Email 2b** (acceptance): *“Your complaint has been accepted… Ticket ID: CMP000x… will be resolved soon.”*
     - Returns `{"ticket_id": "CMP000x", "department": "..."}`.

### 3. Workers and assignment

- **Workers** are stored in **workers.json** (same folder as `main.py`). Format: `"username": { "password": "...", "department": "Department Name" }`.
- By default there are **2 workers per department** (e.g. `publicworks1`, `publicworks2` for Public Works; same for Sanitation, Water Department, Electricity, General Department).
- When the RPA **processes** a complaint (accepts it and sets ticket + department), the backend **assigns** it to a worker in that department using **round-robin** (the worker with the fewest currently assigned complaints gets the new one).

### 4. Worker login and tasks

- Workers open **http://localhost:8000/worker/login** and sign in with credentials from `workers.json`.
- After login they are redirected to **/worker/tasks**, which shows **only complaints assigned to them** (`assigned_to` = their username) that are not yet RESOLVED or CANCELLED.
- Each task has a **Complete** link that goes to the completion form.

### 5. Completing work

- On **GET /worker/complete/{complaint_id}**, the worker sees the complaint details and a form to:
  - **Upload an image** as proof of work (optional but recommended).
  - **Write a description** (completion notes), required.
- On **POST /worker/complete/{complaint_id}**:
  - The proof image is saved under `uploads/proofs/` with a unique filename; `proof_image_path` and `proof_description` are stored on the complaint.
  - Complaint **status** is set to **RESOLVED**.
  - An **email is sent to the citizen** (the complaint’s `email` field) informing them that their complaint has been resolved.

### 6. Department admin views and cancels

1. Admin opens **http://localhost:8000/admin/login** and signs in (credentials in `admin_users.json`).
2. **GET /admin/complaints** shows only complaints whose `department` matches the admin’s department.
3. Admin can **cancel** a complaint (if not already cancelled) by choosing a reason and submitting:
   - **POST /admin/complaints/{complaint_id}/cancel** with form field `reason`.
   - Allowed reasons: *“Doesn't belong to the department”*, *“Unable to accept image”*, *“Rejected by the authorities”*.
   - Sets `status=CANCELLED` and `cancel_reason`.

---

## API endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET    | `/` | Citizen complaint form (HTML) |
| GET    | `/track?ticket_id=<id>` | Check status by ticket ID (e.g. CMP0001). Without query: search form; with `ticket_id`: complaint details, status, and (when resolved) the worker’s proof image and completion comment (HTML). |
| POST   | `/submit-complaint` | Submit complaint (form: subject, description, location, email, optional image). Sends “received” email. |
| GET    | `/admin/login` | Admin login form (HTML) |
| POST   | `/admin/login` | Admin login (form: username, password). Redirects to `/admin/complaints`. |
| GET    | `/admin/logout` | Clear session, redirect to login |
| GET    | `/admin/complaints` | Department complaints page (HTML). Requires admin session. |
| POST   | `/admin/complaints/{id}/cancel` | Cancel complaint with reason (form: reason). Requires admin session. |
| GET    | `/worker/login` | Worker login form (HTML). |
| POST   | `/worker/login` | Worker login (form: username, password). Redirects to `/worker/tasks`. |
| GET    | `/worker/logout` | Clear worker session, redirect to login. |
| GET    | `/worker/tasks` | List tasks assigned to the logged-in worker (HTML). Requires worker session. |
| GET    | `/worker/complete/{id}` | Form to upload proof image and completion description. Requires worker session; complaint must be assigned to worker. |
| POST   | `/worker/complete/{id}` | Submit proof + description; set status=RESOLVED; send resolution email to citizen. Requires worker session. |
| GET    | `/rpa/unprocessed-complaints` | JSON list of complaints with `rpa_processed=false` (for RPA bot). |
| POST   | `/rpa/process-complaint?id=&lt;id&gt;` | Process one complaint: assign ticket + department + worker or reject. Sends acceptance/rejection email. |
| GET    | `/complaints` | JSON list of all complaints (debug). |

---

## Department classifier

`classifier.classify_department(subject)` uses **keyword rules** (case-insensitive) on the subject:

| Keywords       | Department      |
|----------------|-----------------|
| pothole, road  | Public Works    |
| garbage, trash | Sanitation      |
| water, leak    | Water Department|
| street light   | Electricity     |
| (no match)     | General Department → complaint **rejected** by RPA (not assigned to a department) |

---

## Admin accounts

Stored in **admin_users.json** (same folder as `main.py`). Format:

```json
{
  "username": { "password": "...", "department": "Department Name" }
}
```

Demo accounts (change in production):

| Username     | Password   | Department       |
|-------------|------------|------------------|
| publicworks | public123  | Public Works     |
| sanitation  | clean123   | Sanitation       |
| water       | water123   | Water Department |
| electricity | power123   | Electricity      |
| general     | general123 | General Department |

Session is kept in memory and via `admin_session` cookie (no database).

---

## Worker accounts

Stored in **workers.json** (same folder as `main.py`). Format:

```json
{
  "username": { "password": "...", "department": "Department Name" }
}
```

By default there are **2 workers per department**. Demo accounts (change in production):

| Username      | Password | Department       |
|---------------|----------|------------------|
| publicworks1  | pw1      | Public Works     |
| publicworks2  | pw2      | Public Works     |
| sanitation1   | s1       | Sanitation       |
| sanitation2   | s2       | Sanitation       |
| water1        | w1       | Water Department |
| water2        | w2       | Water Department |
| electricity1  | e1       | Electricity      |
| electricity2  | e2       | Electricity      |
| general1      | g1       | General Department |
| general2      | g2       | General Department |

Worker session is kept in memory and via `worker_session` cookie.

---

## Email notifications

- **When:** Sent automatically by the backend (no extra API calls needed).
- **Config:** `.env` in the same directory as `main.py`; loaded at startup via `python-dotenv`.
- **Variables:** `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `FROM_EMAIL`.
- **If not configured:** Requests still succeed; “Email not configured; skipping email to …” is printed and no email is sent.

| Event              | Email content |
|--------------------|---------------|
| Complaint submitted| “Request received. You will receive another email once your complaint is accepted for processing.” |
| Complaint accepted | “Your complaint has been accepted. Ticket ID: CMP000x. Department: … Will be resolved soon.” |
| Complaint rejected | “Your complaint could not be accepted. It does not match any specific department.” |
| Complaint resolved | “Your complaint (Ticket ID: CMP000x) has been resolved. Our team has completed the work.” |

---

## Status and cancellation

- **Status enum** (`models.ComplaintStatus`): `PENDING`, `IN_PROGRESS`, `RESOLVED`, `CLOSED`, `CANCELLED`.
- New complaints start as **PENDING**. RPA sets **CANCELLED** when department is “General Department”; admin can set **CANCELLED** with a reason via the admin UI.
- **Cancel reasons** (fixed list): “Doesn't belong to the department”, “Unable to accept image”, “Rejected by the authorities”.

---

## Security notes

- **.env** and **admin_users.json** must not be committed with real credentials; add them to `.gitignore` if needed.
- App is intended for **localhost**; no HTTPS or production hardening included.
- Admin auth is session-cookie based; sessions are in-memory and lost on restart.

---

## Troubleshooting

- **“Email not configured”**  
  Ensure `.env` exists next to `main.py` and contains `SMTP_HOST` and `FROM_EMAIL`. Restart the server after changing `.env`.

- **SSL handshake timeout when sending email**  
  The app uses `ssl.create_default_context()` and a 30s timeout for SMTP. If it still times out, check firewall/VPN or try another network (e.g. mobile hotspot).

- **Admin login fails**  
  Check `admin_users.json` syntax and that the username/password match. Ensure the file is in the same directory as `main.py`.

- **Complaints not in admin list**  
  Complaints appear for an admin only if `complaint.department` equals that admin’s department. Ensure the RPA has processed the complaint (so `department` is set) and that the classifier did not assign “General Department” (those are rejected, not shown to a department).
