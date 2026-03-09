from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# SQLite database URL (file will be created automatically if it does not exist)
DATABASE_URL = "sqlite:///./complaints.db"

# For SQLite, check_same_thread=False is needed when using the same connection in multiple threads
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)

# Session factory used for each request
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for our ORM models
Base = declarative_base()


def get_db():
    """
    FastAPI dependency that provides a database session.
    Each request gets its own session which is closed automatically.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

