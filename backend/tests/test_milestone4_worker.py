import pytest
import sys
import math
from unittest.mock import MagicMock
from src.api.routes.signals import sanitize_floats
import src.llm.signal_validator as sv
from src.strategy.position_sizing import calculate_position_size
from src.data.groww_mcp import GrowwMCPClient

def test_sanitize_floats():
    """Test recursive float sanitization that replaces NaN and Inf with None."""
    data = {
        "nan_val": float("nan"),
        "inf_val": float("inf"),
        "neg_inf_val": float("-inf"),
        "normal_val": 42.5,
        "nested_dict": {
            "nan": float("nan"),
            "list": [1.0, float("nan"), 3.0]
        }
    }
    sanitized = sanitize_floats(data)
    assert sanitized["nan_val"] is None
    assert sanitized["inf_val"] is None
    assert sanitized["neg_inf_val"] is None
    assert sanitized["normal_val"] == 42.5
    assert sanitized["nested_dict"]["nan"] is None
    assert sanitized["nested_dict"]["list"] == [1.0, None, 3.0]


def test_batch_validate_signals_auto_mistake():
    """Test that batch_validate_signals automatically queries mistake history when None/empty."""
    # Mock yfinance
    mock_yf = MagicMock()
    mock_ticker = MagicMock()
    mock_ticker.info = {"shortName": "M4 Test Company"}
    mock_yf.Ticker.return_value = mock_ticker
    sys.modules["yfinance"] = mock_yf

    # Mock GrowwMCPClient async calls
    mcp_client = GrowwMCPClient.get_instance()
    orig_oi = mcp_client._get_open_interest_analysis_async
    orig_patterns = mcp_client._get_historical_candlestick_patterns_async
    
    async def mock_oi(*args, **kwargs):
        return "mocked_oi"
    async def mock_patterns(*args, **kwargs):
        return "mocked_patterns"
        
    mcp_client._get_open_interest_analysis_async = mock_oi
    mcp_client._get_historical_candlestick_patterns_async = mock_patterns

    original_validate = sv.validate_signal
    calls = []
    
    def mock_validate(sig, market_context, mistake_history, oi_analysis, historical_patterns):
        calls.append(mistake_history)
        return {"verdict": "buy", "adjusted_confidence": 75, "reasoning": "Mocked validation", "key_risk": "None"}
        
    sv.validate_signal = mock_validate

    try:
        signals = [{"ticker": "M4_TEST.NS"}]
        results = sv.batch_validate_signals(signals, mistake_histories=None)
        assert len(results) == 1
        assert len(calls) == 1
        assert calls[0] == "No past mistakes recorded for this ticker."
    finally:
        sv.validate_signal = original_validate
        mcp_client._get_open_interest_analysis_async = orig_oi
        mcp_client._get_historical_candlestick_patterns_async = orig_patterns
        if "yfinance" in sys.modules:
            del sys.modules["yfinance"]


def test_verdict_node_type_safety():
    """Test verdict normalization and safe parsing of confidence score in verdict_node."""
    class MockLLMClient:
        def __init__(self, response_json):
            self.response_json = response_json
        def is_healthy(self):
            return True
        def generate_json(self, prompt, system=None):
            return self.response_json
            
    orig_get_client = sv.get_llm_client
    
    try:
        # Case 1: verdict needs normalization and adjusted_confidence is a string with non-digits
        mock_client = MockLLMClient({
            "verdict": " STRONG_BUY  ",
            "reasoning": "Looks great",
            "adjusted_confidence": "  85% confidence ",
            "key_risk": "None"
        })
        sv.get_llm_client = lambda: mock_client
        
        state = {
            "signal": {"ticker": "AAPL.NS", "confidence": 50},
            "tech_analysis": "...",
            "sentiment_analysis": "...",
            "risk_analysis": "...",
            "news_fallback": False
        }
        res = sv.verdict_node(state)
        assert res["final_result"]["verdict"] == "strong_buy"
        assert res["final_result"]["adjusted_confidence"] == 85
        
        # Case 2: invalid verdict defaults to "buy" and invalid confidence defaults to 50
        mock_client2 = MockLLMClient({
            "verdict": "unknown_verdict",
            "reasoning": "Hmm",
            "adjusted_confidence": "not-a-number",
            "key_risk": "None"
        })
        sv.get_llm_client = lambda: mock_client2
        res2 = sv.verdict_node(state)
        assert res2["final_result"]["verdict"] == "buy"
        assert res2["final_result"]["adjusted_confidence"] == 50
    finally:
        sv.get_llm_client = orig_get_client


def test_search_prompt_parsing_and_fallback():
    """Test robust extraction of search queries and correct fallback when search limit is exceeded."""
    class MockLLMClient:
        def __init__(self, response):
            self.response = response
        def is_healthy(self):
            return True
        def generate(self, prompt, system=None):
            return self.response
            
    orig_get_client = sv.get_llm_client
    try:
        # Case 1: "SEARCH:" in response and count < 2
        mock_client1 = MockLLMClient("I think we need more info. SEARCH: \"Apple Inc stock news\"")
        sv.get_llm_client = lambda: mock_client1
        state = {
            "signal": {"ticker": "AAPL.NS", "company_name": "Apple Inc"},
            "market_context": "...",
            "news_context": "...",
            "sentiment_search_history": ""
        }
        res1 = sv.sentiment_node(state)
        assert res1["sentiment_analysis"] == "SEARCH: Apple Inc stock news"
        
        # Case 2: "SEARCH:" in response and count >= 2
        state_exceeded = {
            "signal": {"ticker": "AAPL.NS", "company_name": "Apple Inc"},
            "market_context": "...",
            "news_context": "...",
            "sentiment_search_history": "Query: Apple\nQuery: Apple news\n"
        }
        res2 = sv.sentiment_node(state_exceeded)
        assert "Maximum web search limit reached" in res2["sentiment_analysis"]
        
        # Case 3: risk_manager_node with "SEARCH:" and count >= 2
        mock_client2 = MockLLMClient("Let's do SEARCH: 'US interest rates'")
        sv.get_llm_client = lambda: mock_client2
        state_risk = {
            "signal": {"ticker": "AAPL.NS", "company_name": "Apple Inc"},
            "tech_analysis": "...",
            "sentiment_analysis": "...",
            "mistake_history": "...",
            "market_context": "...",
            "risk_search_history": "Query: inflation\nQuery: rates\n"
        }
        res3 = sv.risk_manager_node(state_risk)
        assert "Maximum web search limit reached" in res3["risk_analysis"]
    finally:
        sv.get_llm_client = orig_get_client
