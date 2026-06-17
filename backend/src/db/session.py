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

from sqlalchemy import event
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """Create all tables if they don't exist"""
    Base.metadata.create_all(bind=engine)
    
    # Run simple SQLite migrations for the trades table
    with engine.begin() as conn:
        cursor = conn.exec_driver_sql("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        if columns:
            if "llm_verdict" not in columns:
                conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN llm_verdict VARCHAR")
            if "llm_reasoning" not in columns:
                conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN llm_reasoning TEXT")
            if "cons" not in columns:
                conn.exec_driver_sql("ALTER TABLE trades ADD COLUMN cons TEXT")

def get_db():
    """Dependency for FastAPI routes to get a DB session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
