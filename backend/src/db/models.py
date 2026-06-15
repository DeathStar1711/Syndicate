import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base
from src.utils.helpers import now_ist

Base = declarative_base()

class PortfolioState(Base):
    __tablename__ = "portfolio_state"
    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=False)

class DailySnapshot(Base):
    __tablename__ = "daily_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, unique=True, index=True, nullable=False)
    total_capital = Column(Float, nullable=False)
    invested_capital = Column(Float, nullable=False)
    available_capital = Column(Float, nullable=False)
    open_positions = Column(Integer, nullable=False)
    daily_pnl = Column(Float, default=0.0)
    cumulative_pnl = Column(Float, default=0.0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    total_trades = Column(Integer, default=0)

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    direction = Column(String, default="long", nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    target = Column(Float, nullable=False)
    shares = Column(Integer, nullable=False)
    position_value = Column(Float, nullable=False)
    risk_amount = Column(Float, nullable=False)
    risk_reward = Column(Float, nullable=False)
    confidence = Column(Integer, nullable=False)
    reasons = Column(Text, nullable=True) # JSON list
    entry_date = Column(String, nullable=False)
    exit_price = Column(Float, nullable=True)
    exit_date = Column(String, nullable=True)
    exit_reason = Column(String, nullable=True)
    pnl = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    status = Column(String, default="open", nullable=False)
    metadata_json = Column("metadata", Text, nullable=True)

class Signal(Base):
    __tablename__ = "signals"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String, index=True, nullable=False)
    signal = Column(String, nullable=False) # BUY, SELL, HOLD
    confidence = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    target = Column(Float, nullable=True)
    reasoning = Column(Text, nullable=False)
    date = Column(DateTime, default=datetime.datetime.utcnow)
    executed = Column(Boolean, default=False)
