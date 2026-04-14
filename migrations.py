"""
SQLite additive migrations for existing databases.

SQLAlchemy's create_all() creates missing tables but does not ALTER existing
tables. These statements add columns that were introduced after the initial
schema; if a column already exists, SQLite raises and we ignore the error.
"""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_complaints_table_columns(engine: Engine) -> None:
    statements = [
        "ALTER TABLE complaints ADD COLUMN ticket_id VARCHAR(50)",
        "ALTER TABLE complaints ADD COLUMN department VARCHAR(100)",
        "ALTER TABLE complaints ADD COLUMN rpa_processed BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN cancel_reason VARCHAR(255)",
        "ALTER TABLE complaints ADD COLUMN email VARCHAR(255) NOT NULL DEFAULT ''",
        "ALTER TABLE complaints ADD COLUMN assigned_to VARCHAR(100)",
        "ALTER TABLE complaints ADD COLUMN progress_percent INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE complaints ADD COLUMN progress_note TEXT",
        "ALTER TABLE complaints ADD COLUMN estimated_resolution_at DATETIME",
        "ALTER TABLE complaints ADD COLUMN proof_image_path VARCHAR(255)",
        "ALTER TABLE complaints ADD COLUMN proof_description TEXT",
        "ALTER TABLE complaints ADD COLUMN verification_pin VARCHAR(10)",
        "ALTER TABLE complaints ADD COLUMN verification_pin_sent_at DATETIME",
    ]

    with engine.begin() as conn:
        for sql in statements:
            try:
                conn.execute(text(sql))
            except Exception:
                pass
