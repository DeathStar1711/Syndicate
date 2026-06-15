import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Base

# We point the DB to the existing legacy location to inherit trade history seamlessly.
from src.utils.helpers import get_data_dir
DB_PATH = os.path.join(get_data_dir(), "trades", "portfolio.db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables if they don't exist"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """Dependency for FastAPI routes to get a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
