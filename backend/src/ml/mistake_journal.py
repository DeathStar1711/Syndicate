"""
Mistake Journal — records and analyzes losing trades for model retraining.

Every stop-loss exit is recorded with full context:
- Technical snapshot at entry time
- News headlines around the trade dates
- Computed reason codes for failure classification

During retraining, past mistake samples get higher weight so the model
learns from its errors.
"""
import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from src.utils.logger import get_logger
from src.utils.helpers import get_data_dir

logger = get_logger("stock_ai.ml")

DB_NAME = "mistake_journal.db"

# Reason codes used to classify why a trade failed
REASON_CODES = {
    "against_trend": "Entry was against the dominant trend",
    "high_volatility_entry": "Entered during high/extreme volatility",
    "low_volume_entry": "Entry had below-average volume confirmation",
    "rsi_extreme": "RSI was in an extreme zone at entry",
    "news_shock": "Significant negative news appeared during trade",
    "false_breakout": "Breakout failed — price reversed quickly",
    "weak_momentum": "MACD / momentum was weak or diverging at entry",
    "unknown": "No clear pattern identified",
}


class MistakeJournal:
    """SQLite-backed journal for recording and analyzing losing trades."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = os.path.join(get_data_dir(), "ml", DB_NAME)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create the mistakes table if it doesn't exist."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                ticker TEXT NOT NULL,
                entry_date TEXT,
                exit_date TEXT,
                entry_price REAL,
                exit_price REAL,
                stop_loss REAL,
                pnl REAL,
                pnl_pct REAL,
                exit_reason TEXT,
                technical_snapshot TEXT,
                news_context TEXT,
                reason_codes TEXT,
                analysis_notes TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def record_mistake(
        self,
        trade_result: Dict,
        technical_data: Optional[Dict] = None,
        news_headlines: Optional[List[Dict]] = None,
    ) -> int:
        """
        Record a losing trade with full context.

        Args:
            trade_result: Dict from PaperTrader.close_trade() with trade details
            technical_data: Dict of technical indicator values at entry time
            news_headlines: List of headline dicts around the trade dates

        Returns:
            Mistake record ID
        """
        technical_data = technical_data or {}
        news_headlines = news_headlines or []

        # Classify the mistake
        reason_codes = self._classify_mistake(technical_data, news_headlines)

        # Build analysis notes
        notes = self._build_analysis_notes(trade_result, reason_codes, news_headlines)

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO mistakes (
                trade_id, ticker, entry_date, exit_date,
                entry_price, exit_price, stop_loss,
                pnl, pnl_pct, exit_reason,
                technical_snapshot, news_context,
                reason_codes, analysis_notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_result.get("trade_id"),
            trade_result.get("ticker", "UNKNOWN"),
            trade_result.get("entry_date"),
            trade_result.get("exit_date"),
            trade_result.get("entry_price"),
            trade_result.get("exit_price"),
            trade_result.get("stop_loss"),
            trade_result.get("pnl", 0),
            trade_result.get("pnl_pct", 0),
            trade_result.get("exit_reason", "stop_loss"),
            json.dumps(technical_data),
            json.dumps(news_headlines),
            json.dumps(reason_codes),
            notes,
            datetime.now().isoformat(),
        ))

        mistake_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(
            f"📝 MISTAKE RECORDED: #{mistake_id} {trade_result.get('ticker')} | "
            f"P&L: ₹{trade_result.get('pnl', 0):,.2f} | "
            f"Reasons: {', '.join(reason_codes)}"
        )

        return mistake_id

    def _classify_mistake(
        self, technical_data: Dict, news_headlines: List[Dict]
    ) -> List[str]:
        """
        Classify a mistake into reason codes based on technical and news context.

        Returns:
            List of applicable reason code strings
        """
        codes = []

        # Check trend alignment
        trend = technical_data.get("trend", "")
        if trend in ("bearish", "sideways"):
            codes.append("against_trend")

        # Check volatility
        vol_regime = technical_data.get("volatility_regime", "normal")
        if vol_regime in ("high", "extreme"):
            codes.append("high_volatility_entry")

        # Check volume
        vol_ratio = technical_data.get("volume_ratio", 1.0)
        if isinstance(vol_ratio, (int, float)) and vol_ratio < 0.8:
            codes.append("low_volume_entry")

        # Check RSI extremes
        rsi = technical_data.get("rsi_14", 50)
        if isinstance(rsi, (int, float)) and (rsi > 70 or rsi < 30):
            codes.append("rsi_extreme")

        # Check MACD weakness
        macd_hist = technical_data.get("macd_histogram", 0)
        if isinstance(macd_hist, (int, float)) and macd_hist < 0:
            codes.append("weak_momentum")

        # Check for negative news
        if news_headlines:
            negative_keywords = [
                "crash", "plunge", "downgrade", "miss", "loss",
                "bearish", "fraud", "selloff", "sell-off", "slump",
                "warning", "probe", "investigation", "default",
            ]
            negative_count = sum(
                1 for h in news_headlines
                if any(kw in h.get("title", "").lower() for kw in negative_keywords)
            )
            if negative_count >= 2:
                codes.append("news_shock")

        # Check for false breakout (price reversal)
        returns_1d = technical_data.get("returns_1d", 0)
        if isinstance(returns_1d, (int, float)) and returns_1d < -0.02:
            codes.append("false_breakout")

        if not codes:
            codes.append("unknown")

        return codes

    def _build_analysis_notes(
        self,
        trade_result: Dict,
        reason_codes: List[str],
        news_headlines: List[Dict],
    ) -> str:
        """Build human-readable analysis notes for a mistake."""
        lines = [
            f"Mistake Analysis for {trade_result.get('ticker', '?')}",
            f"P&L: ₹{trade_result.get('pnl', 0):,.2f} ({trade_result.get('pnl_pct', 0):+.1f}%)",
            f"Exit Reason: {trade_result.get('exit_reason', '?')}",
            "",
            "Identified Issues:",
        ]

        for code in reason_codes:
            desc = REASON_CODES.get(code, code)
            lines.append(f"  • {code}: {desc}")

        if news_headlines:
            lines.append("")
            lines.append(f"News Context ({len(news_headlines)} headlines):")
            for h in news_headlines[:5]:
                lines.append(f"  - {h.get('title', '?')} ({h.get('source', '?')})")

        return "\n".join(lines)

    def get_mistake_patterns(self) -> Dict:
        """
        Aggregate mistake patterns for analysis.

        Returns:
            Dict with pattern statistics:
            - reason_counts: {code: count}
            - worst_tickers: [(ticker, avg_loss, count)]
            - total_mistakes: int
            - total_loss: float
        """
        conn = self._get_conn()
        cursor = conn.cursor()

        # Total stats
        cursor.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(pnl), 0) as total_loss
            FROM mistakes
        """)
        row = cursor.fetchone()
        total = row["total"]
        total_loss = row["total_loss"]

        # Reason code frequency
        cursor.execute("SELECT reason_codes FROM mistakes")
        reason_counts: Dict[str, int] = {}
        for row in cursor.fetchall():
            try:
                codes = json.loads(row["reason_codes"])
                for code in codes:
                    reason_counts[code] = reason_counts.get(code, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

        # Worst tickers
        cursor.execute("""
            SELECT ticker,
                   ROUND(AVG(pnl), 2) as avg_loss,
                   COUNT(*) as count
            FROM mistakes
            GROUP BY ticker
            ORDER BY avg_loss ASC
            LIMIT 10
        """)
        worst_tickers = [
            (row["ticker"], row["avg_loss"], row["count"])
            for row in cursor.fetchall()
        ]

        conn.close()

        # Sort reasons by frequency
        reason_counts = dict(
            sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)
        )

        return {
            "total_mistakes": total,
            "total_loss": round(total_loss, 2),
            "reason_counts": reason_counts,
            "worst_tickers": worst_tickers,
        }

    def get_mistake_samples(self, n: int = 50) -> List[Dict]:
        """
        Get the N most recent mistake technical snapshots for retraining.
        These feature vectors will get higher sample weight during training.

        Args:
            n: Number of most recent mistakes to return

        Returns:
            List of dicts with 'features' (technical snapshot) and 'ticker'
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ticker, technical_snapshot, reason_codes
            FROM mistakes
            ORDER BY created_at DESC
            LIMIT ?
        """, (n,))

        samples = []
        for row in cursor.fetchall():
            try:
                features = json.loads(row["technical_snapshot"])
                if features:  # skip empty snapshots
                    samples.append({
                        "ticker": row["ticker"],
                        "features": features,
                        "reason_codes": json.loads(row["reason_codes"] or "[]"),
                    })
            except (json.JSONDecodeError, TypeError):
                pass

        conn.close()
        logger.info(f"Loaded {len(samples)} mistake samples for retraining")
        return samples

    def get_analysis_report(self) -> str:
        """
        Generate a human-readable report of mistake patterns.

        Returns:
            Formatted string report
        """
        patterns = self.get_mistake_patterns()

        lines = [
            "=" * 60,
            "MISTAKE ANALYSIS REPORT",
            "=" * 60,
            f"Total Mistakes: {patterns['total_mistakes']}",
            f"Total Loss: ₹{patterns['total_loss']:,.2f}",
            "",
            "Top Failure Reasons:",
        ]

        for code, count in list(patterns["reason_counts"].items())[:5]:
            desc = REASON_CODES.get(code, code)
            pct = (count / max(patterns["total_mistakes"], 1)) * 100
            lines.append(f"  {count:3d} ({pct:5.1f}%) — {code}: {desc}")

        if patterns["worst_tickers"]:
            lines.append("")
            lines.append("Worst-Performing Tickers:")
            for ticker, avg_loss, count in patterns["worst_tickers"][:5]:
                lines.append(
                    f"  {ticker}: avg loss ₹{avg_loss:,.2f} ({count} mistakes)"
                )

        lines.append("=" * 60)
        return "\n".join(lines)

    def get_ticker_mistake_history(self, ticker: str) -> str:
        """
        Retrieve and format the recent mistake history for a given ticker.
        """
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT entry_date, exit_date, pnl_pct, reason_codes, analysis_notes
            FROM mistakes
            WHERE ticker = ?
            ORDER BY created_at DESC
            LIMIT 5
        """, (ticker,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "No past mistakes recorded for this ticker."

        formatted_records = []
        for i, row in enumerate(rows, 1):
            entry_date = row["entry_date"] or "N/A"
            exit_date = row["exit_date"] or "N/A"
            pnl_pct = row["pnl_pct"]
            pnl_str = f"{pnl_pct:+.2f}%" if isinstance(pnl_pct, (int, float)) else "N/A"
            
            try:
                reason_codes = json.loads(row["reason_codes"] or "[]")
            except (json.JSONDecodeError, TypeError):
                reason_codes = []
            
            reasons_str = ", ".join(reason_codes) if reason_codes else "None"
            notes = row["analysis_notes"] or "No notes available."
            
            record_str = (
                f"Mistake #{i}:\n"
                f"  Date Range: {entry_date} to {exit_date}\n"
                f"  P&L %: {pnl_str}\n"
                f"  Reason Codes: {reasons_str}\n"
                f"  Analysis Notes:\n{notes}"
            )
            formatted_records.append(record_str)
            
        return "\n\n".join(formatted_records)

