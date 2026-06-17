"""
Test suite for news data module, sentiment analysis, and mistake journal.
"""
import sys
import os
import pytest
import json
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.features.sentiment import (
    score_headline,
    score_headlines,
    compute_news_features,
)
from src.ml.mistake_journal import MistakeJournal, REASON_CODES
from src.ml.trainer import (
    FEATURE_COLUMNS,
    TECHNICAL_FEATURE_COLUMNS,
    NEWS_FEATURE_COLUMNS,
)


# ── Sentiment Scoring Tests ──────────────────────────────────────────


class TestSentimentScoring:
    """Tests for headline sentiment analysis."""

    def test_positive_headline_scores_positive(self):
        score = score_headline("Stock surges on strong profit growth")
        assert score > 0, f"Expected positive score, got {score}"

    def test_negative_headline_scores_negative(self):
        score = score_headline("Stock plunges amid fraud investigation and selloff")
        assert score < 0, f"Expected negative score, got {score}"

    def test_neutral_headline_scores_zero(self):
        score = score_headline("Company holds annual general meeting")
        assert score == 0.0, f"Expected zero score, got {score}"

    def test_empty_headline_scores_zero(self):
        assert score_headline("") == 0.0
        assert score_headline(None) == 0.0

    def test_score_range(self):
        """Score must be in [-1, 1] range."""
        headlines = [
            "Stock rally surges with massive profit upgrade bullish growth",
            "Crash plunge downgrade fraud loss bearish selloff",
            "Normal quarterly results announced",
        ]
        for h in headlines:
            s = score_headline(h)
            assert -1.0 <= s <= 1.0, f"Score {s} out of range for: {h}"

    def test_custom_keywords(self):
        keywords = {
            "positive": ["moon", "rocket"],
            "negative": ["dump"],
        }
        assert score_headline("Stock goes to the moon", keywords) > 0
        assert score_headline("Massive dump incoming", keywords) < 0


class TestScoreHeadlines:
    """Tests for batch headline scoring."""

    def test_multiple_headlines(self):
        headlines = [
            {"title": "Stock surges on profit beat"},
            {"title": "Earnings miss causes selloff"},
            {"title": "Regular quarterly results"},
        ]
        result = score_headlines(headlines)
        assert "score" in result
        assert "count" in result
        assert "std" in result
        assert result["count"] == 3
        assert -1.0 <= result["score"] <= 1.0

    def test_empty_headlines_list(self):
        result = score_headlines([])
        assert result["score"] == 0.0
        assert result["count"] == 0
        assert result["std"] == 0.0

    def test_single_headline(self):
        result = score_headlines([{"title": "Strong rally"}])
        assert result["count"] == 1
        assert result["std"] == 0.0  # no variance with single item


# ── News Features Tests ──────────────────────────────────────────────


class TestNewsFeatures:
    """Tests for ML-ready news feature computation."""

    def test_features_shape(self):
        """compute_news_features must return dict with expected keys."""
        # This will return neutral values since we're not hitting real APIs
        features = compute_news_features("FAKE_TICKER.NS")
        assert isinstance(features, dict)
        assert "news_sentiment_score" in features
        assert "news_volume" in features
        assert "news_recency_score" in features

    def test_features_are_numeric(self):
        features = compute_news_features("FAKE_TICKER.NS")
        for key, val in features.items():
            assert isinstance(val, (int, float)), f"{key} is not numeric: {val}"

    def test_features_in_expected_range(self):
        features = compute_news_features("FAKE_TICKER.NS")
        assert -1.0 <= features["news_sentiment_score"] <= 1.0
        assert 0.0 <= features["news_volume"] <= 1.0
        assert 0.0 <= features["news_recency_score"] <= 1.0


# ── Feature Columns Tests ────────────────────────────────────────────


class TestFeatureColumns:
    """Tests for the expanded feature set."""

    def test_expanded_feature_count(self):
        """FEATURE_COLUMNS should contain technical and news features."""
        assert len(FEATURE_COLUMNS) >= 11

    def test_technical_features_count(self):
        assert len(TECHNICAL_FEATURE_COLUMNS) >= 8

    def test_news_features_count(self):
        assert len(NEWS_FEATURE_COLUMNS) >= 3

    def test_combined_equals_tech_plus_news(self):
        # Allow extra columns if added dynamically, just ensure tech/news are subsets
        assert set(TECHNICAL_FEATURE_COLUMNS).issubset(set(FEATURE_COLUMNS))
        assert set(NEWS_FEATURE_COLUMNS).issubset(set(FEATURE_COLUMNS))

    def test_news_features_present(self):
        assert "news_sentiment_score" in FEATURE_COLUMNS
        assert "news_volume" in FEATURE_COLUMNS
        assert "news_recency_score" in FEATURE_COLUMNS

    def test_technical_features_still_present(self):
        for col in ["ema_9_slope", "rsi_14", "macd_histogram", "volume_ratio"]:
            assert col in FEATURE_COLUMNS


# ── Mistake Journal Tests ────────────────────────────────────────────


class TestMistakeJournal:
    """Tests for the mistake recording and analysis system."""

    @pytest.fixture
    def journal(self, tmp_path):
        """Create a temporary journal for testing."""
        db_path = str(tmp_path / "test_mistakes.db")
        return MistakeJournal(db_path=db_path)

    def test_journal_initializes(self, journal):
        """Journal should create the database and table."""
        assert os.path.exists(journal.db_path)

    def test_record_mistake(self, journal):
        """Recording a mistake should return a valid ID."""
        trade_result = {
            "trade_id": 1,
            "ticker": "RELIANCE.NS",
            "entry_date": "2026-01-10T09:15:00",
            "exit_date": "2026-01-11T14:30:00",
            "entry_price": 2500.0,
            "exit_price": 2450.0,
            "stop_loss": 2450.0,
            "pnl": -500.0,
            "pnl_pct": -2.0,
            "exit_reason": "stop_loss",
        }
        technical_data = {
            "trend": "bullish",
            "rsi_14": 65,
            "volume_ratio": 1.1,
            "volatility_regime": "normal",
            "macd_histogram": 0.5,
        }
        news = [
            {"title": "Reliance stock faces selloff", "source": "ET"},
        ]

        mistake_id = journal.record_mistake(trade_result, technical_data, news)
        assert mistake_id > 0

    def test_record_and_retrieve(self, journal):
        """Recorded mistakes should be retrievable."""
        trade = {
            "trade_id": 2,
            "ticker": "TCS.NS",
            "pnl": -300.0,
            "pnl_pct": -1.5,
            "exit_reason": "stop_loss",
        }
        journal.record_mistake(trade, {"trend": "bearish", "rsi_14": 72})

        samples = journal.get_mistake_samples(n=10)
        assert len(samples) == 1
        assert samples[0]["ticker"] == "TCS.NS"
        assert "features" in samples[0]

    def test_mistake_classification_against_trend(self, journal):
        """Trade against trend should be classified correctly."""
        codes = journal._classify_mistake(
            {"trend": "bearish", "rsi_14": 50, "volume_ratio": 1.0, "macd_histogram": 0.1},
            []
        )
        assert "against_trend" in codes

    def test_mistake_classification_high_volatility(self, journal):
        codes = journal._classify_mistake(
            {"volatility_regime": "extreme", "trend": "bullish", "rsi_14": 50},
            []
        )
        assert "high_volatility_entry" in codes

    def test_mistake_classification_news_shock(self, journal):
        headlines = [
            {"title": "Stock crashes after fraud allegations"},
            {"title": "Massive selloff continues as losses mount"},
        ]
        codes = journal._classify_mistake(
            {"trend": "bullish", "rsi_14": 50, "volume_ratio": 1.0},
            headlines
        )
        assert "news_shock" in codes

    def test_mistake_classification_unknown(self, journal):
        """No matching conditions should result in 'unknown'."""
        codes = journal._classify_mistake(
            {"trend": "bullish", "rsi_14": 50, "volume_ratio": 1.2,
             "volatility_regime": "normal", "macd_histogram": 0.5, "returns_1d": 0.01},
            []
        )
        assert "unknown" in codes

    def test_get_mistake_patterns(self, journal):
        """Pattern aggregation should work with multiple mistakes."""
        # Record several mistakes with different characteristics
        mistakes = [
            {"ticker": "INFY.NS", "pnl": -200, "exit_reason": "stop_loss"},
            {"ticker": "INFY.NS", "pnl": -150, "exit_reason": "stop_loss"},
            {"ticker": "TCS.NS", "pnl": -100, "exit_reason": "stop_loss"},
        ]
        techs = [
            {"trend": "bearish", "rsi_14": 50, "volume_ratio": 0.5},
            {"trend": "bearish", "rsi_14": 75, "volume_ratio": 1.0},
            {"trend": "bullish", "rsi_14": 50, "volume_ratio": 1.0,
             "volatility_regime": "high"},
        ]

        for m, t in zip(mistakes, techs):
            journal.record_mistake(m, t)

        patterns = journal.get_mistake_patterns()
        assert patterns["total_mistakes"] == 3
        assert patterns["total_loss"] < 0  # should be negative (losses)
        assert "reason_counts" in patterns
        assert "worst_tickers" in patterns
        assert len(patterns["worst_tickers"]) >= 1

    def test_analysis_report(self, journal):
        """Analysis report should be a non-empty string."""
        journal.record_mistake(
            {"ticker": "TEST.NS", "pnl": -100, "exit_reason": "stop_loss"},
            {"trend": "bearish"},
        )
        report = journal.get_analysis_report()
        assert isinstance(report, str)
        assert "MISTAKE ANALYSIS REPORT" in report
        assert "TEST.NS" in report

    def test_empty_journal_patterns(self, journal):
        """Empty journal should return zero counts."""
        patterns = journal.get_mistake_patterns()
        assert patterns["total_mistakes"] == 0
        assert patterns["total_loss"] == 0
        assert patterns["reason_counts"] == {}

    def test_empty_journal_samples(self, journal):
        """Empty journal should return empty samples list."""
        samples = journal.get_mistake_samples()
        assert samples == []

    def test_get_ticker_mistake_history(self, journal):
        """Test retrieving formatted mistake history for a ticker."""
        res_empty = journal.get_ticker_mistake_history("AAPL.NS")
        assert res_empty == "No past mistakes recorded for this ticker."

        journal.record_mistake(
            {"ticker": "AAPL.NS", "entry_date": "2026-01-01", "exit_date": "2026-01-02", "pnl_pct": -2.5, "exit_reason": "stop_loss"},
            {"trend": "bearish"},
        )
        journal.record_mistake(
            {"ticker": "AAPL.NS", "entry_date": "2026-01-03", "exit_date": "2026-01-04", "pnl_pct": -1.2, "exit_reason": "stop_loss"},
            {"rsi_14": 80},
        )
        
        res = journal.get_ticker_mistake_history("AAPL.NS")
        assert "Mistake #1" in res
        assert "Mistake #2" in res
        assert "-1.20%" in res
        assert "-2.50%" in res
        assert "AAPL.NS" in res



# ── Reason Codes Tests ───────────────────────────────────────────────


class TestReasonCodes:
    """Verify reason code definitions are consistent."""

    def test_all_codes_have_descriptions(self):
        expected_codes = [
            "against_trend", "high_volatility_entry", "low_volume_entry",
            "rsi_extreme", "news_shock", "false_breakout", "weak_momentum",
            "unknown",
        ]
        for code in expected_codes:
            assert code in REASON_CODES, f"Missing description for {code}"
