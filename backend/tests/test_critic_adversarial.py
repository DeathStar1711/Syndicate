import os
import math
import json
import sqlite3
import tempfile
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from src.ml.mistake_journal import MistakeJournal
import src.llm.signal_validator as sv
from src.api.routes.signals import sanitize_floats
from src.strategy.position_sizing import calculate_position_size

# ==============================================================================
# 1. Mistake history querying is robust and returns exactly the latest 5 mistakes.
# ==============================================================================
def test_mistake_history_returns_latest_5():
    """Verify that MistakeJournal.get_ticker_mistake_history returns exactly the latest 5 mistakes chronologically."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_mistakes_critic.db")
        journal = MistakeJournal(db_path=db_path)
        
        ticker = "CRITIC_TEST.NS"
        
        # 0 mistakes case
        history_0 = journal.get_ticker_mistake_history(ticker)
        assert history_0 == "No past mistakes recorded for this ticker."
        
        # Record 8 mistakes for the ticker
        mistake_ids = []
        base_time = datetime(2026, 6, 1, 12, 0, 0)
        for i in range(1, 9):
            trade_res = {
                "trade_id": i,
                "ticker": ticker,
                "entry_date": f"2026-06-01T12:00:{i:02d}",
                "exit_date": f"2026-06-01T13:00:{i:02d}",
                "entry_price": 100.0 + i,
                "exit_price": 95.0 + i,
                "stop_loss": 96.0 + i,
                "pnl": -500.0 * i,
                "pnl_pct": -5.0,
                "exit_reason": "stop_loss"
            }
            # Record it
            m_id = journal.record_mistake(trade_res)
            mistake_ids.append(m_id)
            
            # Manually update created_at in DB to establish strict ordering
            created_at = (base_time + timedelta(minutes=i)).isoformat()
            conn = sqlite3.connect(db_path)
            conn.execute("UPDATE mistakes SET created_at = ? WHERE id = ?", (created_at, m_id))
            conn.commit()
            conn.close()
            
        history_str = journal.get_ticker_mistake_history(ticker)
        
        # Verify exactly 5 mistakes are returned by counting "Mistake #" headers
        assert history_str.count("Mistake #") == 5
        
        # Verify trade_id 1, 2, 3 (formatted P&L: ₹-500.00, ₹-1,000.00, ₹-1,500.00) are not present.
        assert "₹-500.00" not in history_str
        assert "₹-1,000.00" not in history_str
        assert "₹-1,500.00" not in history_str
        
        # Verify trade_id 8, 7, 6, 5, 4 (formatted P&L: -4000, -3500, -3000, -2500, -2000) are present.
        assert "₹-4,000.00" in history_str
        assert "₹-3,500.00" in history_str
        assert "₹-3,000.00" in history_str
        assert "₹-2,500.00" in history_str
        assert "₹-2,000.00" in history_str


# ==============================================================================
# 2. Signal validation auto-loads mistakes correctly when no history is provided.
# ==============================================================================
@patch("src.llm.signal_validator.validate_signal")
@patch("src.data.groww_mcp.GrowwMCPClient.get_instance")
def test_batch_validate_signals_auto_loads_mistakes(mock_mcp_get_instance, mock_validate_signal, tmp_path):
    """Verify that batch_validate_signals auto-loads mistake history when mistake_histories is not provided."""
    db_path = str(tmp_path / "test_mistakes_autoload_critic.db")
    journal = MistakeJournal(db_path=db_path)
    
    # Populate a mistake
    ticker = "AAPL.NS"
    journal.record_mistake(
        {"ticker": ticker, "entry_date": "2026-01-01", "pnl_pct": -2.5},
        {"trend": "bearish"}
    )
    
    # Mock GrowwMCPClient instance
    mock_mcp_instance = MagicMock()
    mock_mcp_instance.run_coroutine.return_value = ["No OI data", "No historical patterns", "Apple Inc."]
    mock_mcp_get_instance.return_value = mock_mcp_instance
    
    # Mock validate_signal return
    mock_validate_signal.return_value = {
        "verdict": "hold",
        "adjusted_confidence": 50,
        "reasoning": "Neutral",
        "key_risk": "None"
    }
    
    signals = [{"ticker": ticker, "entry_price": 100, "stop_loss": 90, "target": 110, "confidence": 50}]
    
    with patch("src.ml.mistake_journal.MistakeJournal", return_value=journal):
        results = sv.batch_validate_signals(signals, market_context="Test market", mistake_histories=None)
        
        # Verify validate_signal was called and mistake_history was populated from the db
        mock_validate_signal.assert_called_once()
        call_args, call_kwargs = mock_validate_signal.call_args
        assert "mistake_history" in call_kwargs
        assert "AAPL.NS" in call_kwargs["mistake_history"]
        assert "-2.50%" in call_kwargs["mistake_history"]


# ==============================================================================
# 3. Web search query extraction works on various LLM conversational styles and search loops terminate without leaving raw 'SEARCH: ...' text.
# ==============================================================================
def test_web_search_query_extraction_and_termination():
    """Verify query extraction from various conversational styles and check search loop termination without leaving raw 'SEARCH: ...' text."""
    class MockLLMClient:
        def __init__(self, response):
            self.response = response
        def is_healthy(self):
            return True
        def generate(self, prompt, system=None):
            return self.response

    base_state = {
        "signal": {"ticker": "AAPL.NS", "company_name": "Apple Inc"},
        "sentiment_search_history": "",
        "market_context": "Market Context",
        "news_context": "News Context",
        "tech_analysis": "Tech Analysis",
        "sentiment_analysis": "Sentiment Analysis",
        "mistake_history": "Mistake History",
        "risk_search_history": ""
    }

    # Style 1: Standard
    with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
        mock_get_client.return_value = MockLLMClient("SEARCH: Apple Inc stock news")
        state = base_state.copy()
        res = sv.sentiment_node(state)
        assert res["sentiment_analysis"] == "SEARCH: Apple Inc stock news"

    # Style 2: Quotes around query
    with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
        mock_get_client.return_value = MockLLMClient("SEARCH: \"Apple Inc stock news\"")
        state = base_state.copy()
        res = sv.sentiment_node(state)
        assert res["sentiment_analysis"] == "SEARCH: Apple Inc stock news"

    # Style 3: Conversational text followed by SEARCH:
    with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
        mock_get_client.return_value = MockLLMClient("Let me check the web. SEARCH: 'Apple Inc earnings'")
        state = base_state.copy()
        res = sv.sentiment_node(state)
        assert res["sentiment_analysis"] == "SEARCH: Apple Inc earnings"

    # Test Search Loop Termination (Cap at 2 searches)
    with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
        mock_get_client.return_value = MockLLMClient("SEARCH: Apple Inc news again")
        
        state_exceeded = base_state.copy()
        state_exceeded["sentiment_search_history"] = "Query: Apple Inc stock news\nResults: ...\nQuery: Apple Inc earnings\nResults: ...\n"
        res = sv.sentiment_node(state_exceeded)
        
        # Verify loop terminates and leaves no raw 'SEARCH: ...' text
        assert "SEARCH:" not in res["sentiment_analysis"]
        assert "Maximum web search limit reached" in res["sentiment_analysis"]

    # Test same for Risk Manager Node
    with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
        mock_get_client.return_value = MockLLMClient("SEARCH: US interest rates")
        state_risk = base_state.copy()
        state_risk["risk_search_history"] = "Query: inflation\nResults: ...\nQuery: rates\nResults: ...\n"
        res = sv.risk_manager_node(state_risk)
        assert "SEARCH:" not in res["risk_analysis"]
        assert "Maximum web search limit reached" in res["risk_analysis"]


# ==============================================================================
# 4. Type-safe casting in verdict node handles all non-numeric output forms and case-insensitive verdicts.
# ==============================================================================
def test_verdict_node_type_safe_casting():
    """Verify that verdict_node handles case-insensitive verdicts and all kinds of non-numeric formats for adjusted_confidence."""
    class MockLLMClient:
        def __init__(self, response_dict):
            self.response_dict = response_dict
        def is_healthy(self):
            return True
        def generate_json(self, prompt, system=None):
            return self.response_dict

    state_template = {
        "signal": {"ticker": "AAPL.NS", "confidence": 60},
        "tech_analysis": "...",
        "sentiment_analysis": "...",
        "risk_analysis": "...",
        "news_fallback": False
    }

    # Case 1: Case-insensitive verdicts
    for verdict in ["STRONG_BUY", "  buy  ", "Hold", "AVOID"]:
        with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
            mock_get_client.return_value = MockLLMClient({
                "verdict": verdict,
                "reasoning": "Testing",
                "adjusted_confidence": 75,
                "key_risk": "None"
            })
            res = sv.verdict_node(state_template)
            assert res["final_result"]["verdict"] == verdict.strip().lower()

    # Case 2: Non-numeric and weird adjusted_confidence formats
    test_cases = [
        ("95%", 95),
        ("  80 confidence score ", 80),
        ("confidence: 45", 45),
        ("no digits here", 50),  # Should fallback to 50
        (None, 60),  # Should fallback to base signal confidence (60)
        (120, 100),  # Should be capped at 100
        (-10, 0),    # Should be capped at 0
        (75.8, 75),  # Float conversion
    ]
    for raw_conf, expected_conf in test_cases:
        with patch("src.llm.signal_validator.get_llm_client") as mock_get_client:
            mock_get_client.return_value = MockLLMClient({
                "verdict": "buy",
                "reasoning": "Testing",
                "adjusted_confidence": raw_conf,
                "key_risk": "None"
            })
            res = sv.verdict_node(state_template)
            assert res["final_result"]["adjusted_confidence"] == expected_conf


# ==============================================================================
# 5. Recursively sanitizing float outputs works on deep dict/list structures containing NaN/Inf and doesn't crash on standard types.
# ==============================================================================
def test_sanitize_floats_robustness():
    """Verify that sanitize_floats replaces NaN/Inf with None recursively and handles standard types without crashing."""
    
    # 1. Standard types check
    assert sanitize_floats(5) == 5
    assert sanitize_floats("hello") == "hello"
    assert sanitize_floats(True) is True
    assert sanitize_floats(None) is None
    
    # 2. Basic float checks
    assert sanitize_floats(3.14) == 3.14
    assert sanitize_floats(float("nan")) is None
    assert sanitize_floats(float("inf")) is None
    assert sanitize_floats(float("-inf")) is None

    # 3. Deeply nested structures
    deep_structure = {
        "ticker": "AAPL.NS",
        "metrics": {
            "pe_ratio": float("nan"),
            "market_cap": 3000000000000.0,
            "ebitda": float("inf"),
            "debt": float("-inf"),
            "ratios": [1.2, float("nan"), 4.5]
        },
        "signals": [
            {"type": "MACD", "score": float("nan")},
            {"type": "RSI", "score": 45.2}
        ]
    }
    
    sanitized = sanitize_floats(deep_structure)
    
    # Verify values
    assert sanitized["metrics"]["pe_ratio"] is None
    assert sanitized["metrics"]["market_cap"] == 3000000000000.0
    assert sanitized["metrics"]["ebitda"] is None
    assert sanitized["metrics"]["debt"] is None
    assert sanitized["metrics"]["ratios"] == [1.2, None, 4.5]
    assert sanitized["signals"][0]["score"] is None
    assert sanitized["signals"][1]["score"] == 45.2

    # 4. Caveat Check: tuple containing float('nan')
    tup = (1.0, float("nan"))
    sanitized_tup = sanitize_floats(tup)
    assert isinstance(sanitized_tup, tuple)
    assert math.isnan(sanitized_tup[1])  # NOT sanitized! This is a documented caveat/limitation.


# ==============================================================================
# 6. Kelly Criterion negative expectation correctly halts/rejects the trade.
# ==============================================================================
def test_kelly_criterion_rejection():
    """Verify that Kelly Criterion negative expectation correctly rejects the trade."""
    capital = 100000.0
    entry_price = 100.0
    stop_loss = 90.0  # Risk per share is 10.0
    
    # Case 1: Negative Expectation
    # win_prob = 0.3, risk_reward = 1.5
    # kelly = 0.3 - (0.7 / 1.5) = 0.3 - 0.467 = -0.167 <= 0
    res_neg = calculate_position_size(
        capital=capital,
        entry_price=entry_price,
        stop_loss=stop_loss,
        win_probability=0.3,
        risk_reward=1.5
    )
    assert res_neg["shares"] == 0
    assert res_neg["position_value"] == 0.0
    assert res_neg["error"] == "Negative or zero expectation"
    assert "Negative or zero expectation" in res_neg["reason"]
    
    # Case 2: Zero Expectation (Theoretical)
    # Let's test with exact zero expectation: win_prob = 0.5, risk_reward = 1.0
    # kelly = 0.5 - (0.5 / 1.0) = 0.0
    res_zero = calculate_position_size(
        capital=capital,
        entry_price=entry_price,
        stop_loss=stop_loss,
        win_probability=0.5,
        risk_reward=1.0
    )
    assert res_zero["shares"] == 0
    assert res_zero["position_value"] == 0.0
    assert res_zero["error"] == "Negative or zero expectation"
