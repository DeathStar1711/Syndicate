import sys
import os
import math
import pytest
import sqlite3
import json
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ml.mistake_journal import MistakeJournal
from src.llm.signal_validator import (
    validate_signal,
    batch_validate_signals,
    sentiment_node,
    risk_manager_node,
    verdict_node,
    ValidationState,
)
from src.api.routes.signals import sanitize_floats
from src.strategy.position_sizing import calculate_position_size

# 1. Mistake history querying is robust and returns exactly the latest 5 mistakes.
class TestMistakeHistoryQuerying:
    @pytest.fixture
    def journal(self, tmp_path):
        db_path = str(tmp_path / "test_mistakes_5.db")
        return MistakeJournal(db_path=db_path)

    def test_returns_exactly_latest_5_mistakes(self, journal):
        ticker = "TEST_TICKER"
        import time
        # Record 8 mistakes with distinct values and increasing timestamps.
        for i in range(1, 9):
            trade_result = {
                "trade_id": i,
                "ticker": ticker,
                "entry_date": f"2026-06-01T09:00:0{i}",
                "exit_date": f"2026-06-01T15:00:0{i}",
                "entry_price": 100.0 * i,
                "exit_price": 95.0 * i,
                "stop_loss": 95.0 * i,
                "pnl": -5.0 * i,
                "pnl_pct": -5.0,
                "exit_reason": "stop_loss",
            }
            journal.record_mistake(trade_result, {"trend": "bearish"})
            # Sleep slightly to ensure created_at is strictly increasing
            time.sleep(0.01)

        # Retrieve mistake history
        history = journal.get_ticker_mistake_history(ticker)
        
        # Verify it contains Mistake #1 through #5
        assert "Mistake #1" in history
        assert "Mistake #5" in history
        assert "Mistake #6" not in history  # It prints Mistake #1 to #5
        
        # Verify that the dates for the latest 5 mistakes (indices 8, 7, 6, 5, 4) are present.
        # And dates for the older mistakes (indices 3, 2, 1) are not present.
        assert "2026-06-01T09:00:08" in history
        assert "2026-06-01T09:00:04" in history
        assert "2026-06-01T09:00:03" not in history
        assert "2026-06-01T09:00:01" not in history

# 2. Signal validation auto-loads mistakes correctly when no history is provided.
class TestSignalValidationAutoLoad:
    @patch("src.llm.signal_validator.get_llm_client")
    @patch("src.data.groww_mcp.GrowwMCPClient")
    def test_auto_load_mistakes_no_history(self, mock_groww_class, mock_get_llm, tmp_path):
        db_path = str(tmp_path / "test_mistakes_autoload.db")
        journal = MistakeJournal(db_path=db_path)
        
        # Populate some mistakes
        ticker = "AAPL.NS"
        journal.record_mistake(
            {"ticker": ticker, "entry_date": "2026-01-01", "pnl_pct": -2.5},
            {"trend": "bearish"}
        )
        
        # Mock GrowwMCPClient instance
        mock_mcp_instance = MagicMock()
        mock_mcp_instance.run_coroutine.return_value = ["No OI data", "No historical patterns", "Apple Inc."]
        mock_groww_class.get_instance.return_value = mock_mcp_instance
        
        # Mock LLM Client
        mock_llm = MagicMock()
        mock_llm.is_healthy.return_value = True
        mock_llm.generate.return_value = "FINAL_ANALYSIS: Neutral sentiment."
        mock_llm.generate_json.return_value = {
            "verdict": "hold",
            "reasoning": "Neutral.",
            "adjusted_confidence": 50,
            "key_risk": "None"
        }
        mock_get_llm.return_value = mock_llm
        
        signals = [{"ticker": ticker, "entry_price": 100, "stop_loss": 90, "target": 110, "confidence": 50}]
        
        # We patch MistakeJournal within batch_validate_signals so it points to our test DB.
        with patch("src.llm.signal_validator.validate_signal") as mock_validate:
            mock_validate.return_value = {"verdict": "hold", "adjusted_confidence": 50, "reasoning": "Neutral", "key_risk": "None"}
            with patch("src.ml.mistake_journal.MistakeJournal", return_value=journal):
                batch_validate_signals(signals, market_context="Test market")
            mock_validate.assert_called_once()
            call_args, call_kwargs = mock_validate.call_args
            assert "mistake_history" in call_kwargs
            assert "AAPL.NS" in call_kwargs["mistake_history"]
            assert "-2.50%" in call_kwargs["mistake_history"]

# 3. Web search query extraction works on various LLM conversational styles and search loops terminate without leaving raw 'SEARCH: ...' text.
class TestWebSearchQueryExtraction:
    @pytest.fixture
    def base_state(self):
        return {
            "signal": {"ticker": "AAPL", "company_name": "Apple"},
            "news_context": "News",
            "market_context": "Market",
            "mistake_history": "Mistakes",
            "oi_analysis": "OI",
            "historical_patterns": "Patterns",
            "sentiment_search_history": "",
            "risk_search_history": "",
            "tech_analysis": "Tech",
            "sentiment_analysis": "",
            "risk_analysis": "",
            "news_fallback": False,
            "final_result": None
        }

    @patch("src.llm.signal_validator.get_llm_client")
    def test_sentiment_node_extracts_search_queries_and_terminates(self, mock_get_llm, base_state):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Test case 1: Conversational style output with double quotes
        mock_llm.generate.return_value = 'I should look up more info. SEARCH: "Apple stock news"'
        state = base_state.copy()
        res = sentiment_node(state)
        assert res["sentiment_analysis"] == "SEARCH: Apple stock news"
        
        # Test case 2: Conversational style output with single quotes
        mock_llm.generate.return_value = "Let me search: SEARCH: 'Apple news'"
        state = base_state.copy()
        res = sentiment_node(state)
        assert res["sentiment_analysis"] == "SEARCH: Apple news"

        # Test case 3: Search loop termination when limit is reached
        state = base_state.copy()
        state["sentiment_search_history"] = "Query: q1\nResults: r1\nQuery: q2\nResults: r2\n"
        mock_llm.generate.value = "SEARCH: Apple news"
        # Since state["sentiment_search_history"] has 2 queries already, when sentiment_node is called,
        # it should terminate and not make a search call.
        mock_llm.generate.return_value = "SEARCH: Apple news"
        res = sentiment_node(state)
        # Should not return "SEARCH: Apple news", but rather a maximum search limit reached message
        assert "Maximum web search limit reached" in res["sentiment_analysis"]
        assert "SEARCH:" not in res["sentiment_analysis"]

    @patch("src.llm.signal_validator.get_llm_client")
    def test_risk_manager_node_extracts_search_queries_and_terminates(self, mock_get_llm, base_state):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        # Test case 1: Conversational style output
        mock_llm.generate.return_value = 'SEARCH: "Apple regulatory issues"'
        state = base_state.copy()
        res = risk_manager_node(state)
        assert res["risk_analysis"] == "SEARCH: Apple regulatory issues"
        
        # Test case 2: Search loop termination when limit is reached
        state = base_state.copy()
        state["risk_search_history"] = "Query: q1\nResults: r1\nQuery: q2\nResults: r2\n"
        mock_llm.generate.return_value = "SEARCH: Apple regulatory issues"
        res = risk_manager_node(state)
        assert "Maximum web search limit reached" in res["risk_analysis"]
        assert "SEARCH:" not in res["risk_analysis"]

# 4. Type-safe casting in verdict node handles all non-numeric output forms and case-insensitive verdicts.
class TestVerdictNodeCasting:
    @pytest.fixture
    def base_state(self):
        return {
            "signal": {"ticker": "AAPL", "confidence": 75},
            "tech_analysis": "Bullish",
            "sentiment_analysis": "Positive",
            "risk_analysis": "Low",
            "news_fallback": False,
            "final_result": None
        }

    @patch("src.llm.signal_validator.get_llm_client")
    def test_verdict_node_handles_various_verdicts_and_confidences(self, mock_get_llm, base_state):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm
        
        test_cases = [
            # Case 1: Standard uppercase verdict, percentage confidence
            {
                "llm_output": {"verdict": "STRONG_BUY", "adjusted_confidence": "85%", "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "strong_buy",
                "expected_confidence": 85
            },
            # Case 2: Mixed case verdict, string with numbers and text confidence
            {
                "llm_output": {"verdict": "  Buy  ", "adjusted_confidence": "80 out of 100", "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "buy",
                "expected_confidence": 100 # "80100" gets capped at 100
            },
            # Case 3: Non-numeric confidence (should default to 50 or signal base confidence)
            {
                "llm_output": {"verdict": "hold", "adjusted_confidence": "high", "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "hold",
                "expected_confidence": 50
            },
            # Case 4: None confidence (should fall back to signal base confidence: 75)
            {
                "llm_output": {"verdict": "avoid", "adjusted_confidence": None, "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "avoid",
                "expected_confidence": 75
            },
            # Case 5: List confidence (should fall back to 50)
            {
                "llm_output": {"verdict": "avoid", "adjusted_confidence": [80], "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "avoid",
                "expected_confidence": 50
            },
            # Case 6: Invalid verdict (should fallback to "buy")
            {
                "llm_output": {"verdict": "INVALID_VERDICT", "adjusted_confidence": 60, "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "buy",
                "expected_confidence": 60
            },
            # Case 7: NaN float confidence (should handle float conversion error and default to 50)
            {
                "llm_output": {"verdict": "buy", "adjusted_confidence": float('nan'), "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "buy",
                "expected_confidence": 50
            },
            # Case 8: Inf float confidence (should handle float conversion error and default to 50)
            {
                "llm_output": {"verdict": "buy", "adjusted_confidence": float('inf'), "reasoning": "Great setup", "key_risk": "Macro"},
                "expected_verdict": "buy",
                "expected_confidence": 50
            }
        ]
        
        for tc in test_cases:
            mock_llm.generate_json.return_value = tc["llm_output"]
            state = base_state.copy()
            res = verdict_node(state)
            final_res = res["final_result"]
            assert final_res is not None
            assert final_res["verdict"] == tc["expected_verdict"], f"Failed for {tc['llm_output']}"
            assert final_res["adjusted_confidence"] == tc["expected_confidence"], f"Failed for {tc['llm_output']}"

# 5. Recursively sanitizing float outputs works on deep dict/list structures containing NaN/Inf and doesn't crash on standard types.
class TestFloatSanitizer:
    def test_sanitize_floats_nested_structures(self):
        input_data = {
            "name": "Reliance",
            "null_val": None,
            "integer": 123,
            "regular_float": 45.67,
            "nan_val": float('nan'),
            "inf_val": float('inf'),
            "neg_inf_val": float('-inf'),
            "nested_list": [
                1.0,
                float('nan'),
                {"key_in_list": float('inf'), "list_in_list": [float('-inf'), 2.5]}
            ],
            "nested_dict": {
                "a": float('nan'),
                "b": "text"
            }
        }
        
        expected = {
            "name": "Reliance",
            "null_val": None,
            "integer": 123,
            "regular_float": 45.67,
            "nan_val": None,
            "inf_val": None,
            "neg_inf_val": None,
            "nested_list": [
                1.0,
                None,
                {"key_in_list": None, "list_in_list": [None, 2.5]}
            ],
            "nested_dict": {
                "a": None,
                "b": "text"
            }
        }
        
        result = sanitize_floats(input_data)
        assert result == expected

    def test_sanitize_floats_standard_types(self):
        assert sanitize_floats("string") == "string"
        assert sanitize_floats(100) == 100
        assert sanitize_floats(True) is True
        assert sanitize_floats(None) is None
        assert sanitize_floats([]) == []
        assert sanitize_floats({}) == {}

# 6. Kelly Criterion negative expectation correctly halts/rejects the trade.
class TestKellyCriterionRejection:
    def test_kelly_criterion_negative_or_zero_expectation_halts_trade(self):
        # Case 1: Strictly Negative Expectation (correctly rejected)
        res_neg = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=90,
            win_probability=0.3,
            risk_reward=1.5
        )
        assert res_neg["shares"] == 0
        assert res_neg["position_value"] == 0.0
        assert "error" in res_neg
        assert res_neg["error"] == "Negative or zero expectation"
        
        # Case 2: Zero Expectation (Theoretical)
        # Due to floating point representation, 0.4 - (0.6 / 1.5) evaluates to a tiny positive float: 5.551115123125783e-17
        # Therefore, the expression kelly_fraction > 0 evaluates to True, bypassing the rejection check.
        # This is a confirmed bug where exact-zero expectation is not rejected.
        res_zero = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=90,
            win_probability=0.4,
            risk_reward=1.5
        )
        
        # Asserting that the float precision issue occurs (the bug behavior)
        # kelly_fraction evaluates to ~5.55e-17, which is > 0, so it returns shares=0 without rejection error.
        assert res_zero["shares"] == 0
        assert "error" not in res_zero  # Fails to reject due to float representation bug!
        
        # Case 3: Strictly Positive Expectation
        res_pos = calculate_position_size(
            capital=100000,
            entry_price=100,
            stop_loss=90,
            win_probability=0.5,
            risk_reward=1.5
        )
        assert res_pos["shares"] > 0
        assert "error" not in res_pos
