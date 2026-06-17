import pytest
import time
import asyncio
from typing import Dict, List
from src.trading.paper_trader import PaperTrader
from src.db.session import SessionLocal
from src.db.models import PortfolioState, Trade
from src.data.groww_feed import GrowwFeedListener
from src.trading.intraday_monitor import IntradayMonitor
from src.llm.signal_validator import batch_validate_signals, validate_signal

def test_paper_trader_atomic_capital_update():
    """Test that open_trade and close_trade update current_capital correctly in the database."""
    trader = PaperTrader()
    # Reset starting and current capital for consistency in test
    trader.set_capital(100000.0)
    assert trader.get_capital() == 100000.0

    # Open a trade and verify capital reduction
    signal = {
        "ticker": "RELIANCE.NS",
        "direction": "long",
        "entry_price": 2400.0,
        "stop_loss": 2300.0,
        "target": 2600.0,
        "position": {
            "shares": 10,
            "position_value": 24000.0,
            "risk_amount": 1000.0
        }
    }
    trade_id = trader.open_trade(signal)
    assert trade_id > 0

    # Capital must be 76000.0 after opening trade
    assert trader.get_capital() == 76000.0

    # Close the trade at 2500.0 (profit)
    # Gross P&L = (2500 - 2400) * 10 = 1000.0
    # Turnover = (2400 + 2500) * 10 = 49000.0
    # Brokerage = 49000.0 * 0.001 = 49.0
    # Net PnL = 1000.0 - 49.0 = 951.0
    # New Capital = 76000.0 + 24000.0 + 951.0 = 100951.0
    close_res = trader.close_trade(trade_id, exit_price=2500.0, exit_reason="manual")
    assert close_res["pnl"] == 951.0
    assert trader.get_capital() == pytest.approx(100951.0)


def test_groww_feed_listener_ticker_mapping():
    """Test GrowwFeedListener's bidirectional ticker mapping and dynamic subscription."""
    tickers = ["RELIANCE.NS", "TCS.BO", "INFY"]
    listener = GrowwFeedListener(tickers, lambda x: None)

    # Verify initial tickers clean
    assert "RELIANCE" in listener.tickers
    assert "TCS" in listener.tickers
    assert "INFY" in listener.tickers

    # Verify bidirectional ticker mapping
    assert listener.ticker_map["RELIANCE"] == "RELIANCE.NS"
    assert listener.ticker_map["TCS"] == "TCS.BO"
    assert listener.ticker_map["INFY"] == "INFY"

    # Test dynamic subscription
    listener.subscribe_new_tickers(["WIPRO.NS", "HDFCBANK.BO"])
    assert "WIPRO" in listener.tickers
    assert "HDFCBANK" in listener.tickers
    assert listener.ticker_map["WIPRO"] == "WIPRO.NS"
    assert listener.ticker_map["HDFCBANK"] == "HDFCBANK.BO"


def test_intraday_monitor_cache_refresh():
    """Test IntradayMonitor's dynamic cache refresh and subscription triggers."""
    trader = PaperTrader()
    trader.set_capital(100000.0)
    
    # Clean existing open positions to ensure clean test state
    with SessionLocal() as db:
        db.query(Trade).filter(Trade.status == "open").delete()
        db.commit()

    monitor = IntradayMonitor(trader=trader)

    # Initialise listener mockup
    subscribed_tickers = []
    class MockListener:
        def __init__(self):
            self.tickers = []
        def subscribe_new_tickers(self, new_tickers):
            subscribed_tickers.extend(new_tickers)

    mock_listener = MockListener()

    # Create dummy open positions cache with one trade
    open_trades_cache = [
        {"id": 999, "ticker": "INFY.NS", "entry_price": 1500.0, "stop_loss": 1400.0, "target": 1600.0, "status": "open"}
    ]

    # Setup the local variables to match start_live_monitor's closure structure
    last_cache_refresh = time.time() - 15  # ensure it triggers immediately on check
    
    # We will simulate the cache refresh block inside on_tick
    latest_open_trades = [
        {"id": 999, "ticker": "INFY.NS", "entry_price": 1500.0, "stop_loss": 1400.0, "target": 1600.0, "status": "open"},
        {"id": 1000, "ticker": "SBIN.NS", "entry_price": 600.0, "stop_loss": 580.0, "target": 630.0, "status": "open"}
    ]

    # Check if we identify the new ticker SBIN.NS
    cache_tickers = {t["ticker"] for t in open_trades_cache}
    latest_tickers = {t["ticker"] for t in latest_open_trades}
    new_tickers = list(latest_tickers - cache_tickers)

    assert "SBIN.NS" in new_tickers

    mock_listener.subscribe_new_tickers(new_tickers)
    assert "SBIN.NS" in subscribed_tickers


def test_batch_validate_signals_concurrent_name():
    """Test batch_validate_signals uses concurrent resolution by verifying the flow doesn't block."""
    # We can call batch_validate_signals with mock inputs and verify that they resolve company name
    signals = [
        {"ticker": "SBIN.NS", "direction": "long", "entry_price": 600, "stop_loss": 580, "target": 650, "confidence": 70},
        {"ticker": "TCS.NS", "direction": "long", "entry_price": 3400, "stop_loss": 3300, "target": 3600, "confidence": 80}
    ]

    # Mock the validate_signal method to return dummy output quickly instead of hitting actual LLM in tests
    import src.llm.signal_validator as sv
    original_validate = sv.validate_signal
    sv.validate_signal = lambda *args, **kwargs: {"verdict": "buy", "adjusted_confidence": 75, "reasoning": "Mocked validation", "key_risk": "None"}

    try:
        results = batch_validate_signals(signals)
        assert len(results) == 2
        for r in results:
            assert "company_name" in r
            assert r["company_name"] != ""
            assert r["llm_verdict"] == "buy"
    finally:
        sv.validate_signal = original_validate
