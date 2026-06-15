import os
import json
import sys
from datetime import datetime

# Add src to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.session import init_db, SessionLocal
from src.db.models import Signal
from src.utils.helpers import get_data_dir

def migrate_signals():
    print("Initializing Database...")
    init_db()  # Ensures the 'signals' table is created in portfolio.db
    print("Database initialized.")

    signals_path = os.path.join(get_data_dir(), "signals.json")
    if not os.path.exists(signals_path):
        print("No signals.json found. Nothing to migrate.")
        return

    with open(signals_path, "r") as f:
        data = json.load(f)

    if not data or not data.get("data"):
        print("signals.json is empty or invalid.")
        return

    timestamp_str = data.get("timestamp")
    try:
        if timestamp_str:
            timestamp = datetime.fromisoformat(timestamp_str)
        else:
            timestamp = datetime.now()
    except Exception:
        timestamp = datetime.now()

    signals_list = data.get("data", [])
    
    with SessionLocal() as db:
        # Check if we already migrated
        existing = db.query(Signal).first()
        if existing:
            print("Signals table already has data. Skipping migration to avoid duplicates.")
            return

        for sig in signals_list:
            new_signal = Signal(
                ticker=sig.get("ticker"),
                signal=sig.get("direction", "long"),
                confidence=sig.get("confidence", 0),
                entry_price=sig.get("entry_price"),
                stop_loss=sig.get("stop_loss"),
                target=sig.get("target"),
                reasoning=json.dumps(sig),
                date=timestamp,
                executed=False
            )
            db.add(new_signal)
        
        db.commit()
        print(f"Successfully migrated {len(signals_list)} signals to the database.")

if __name__ == "__main__":
    migrate_signals()
