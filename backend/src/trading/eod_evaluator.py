"""
End-of-day evaluator.
Runs after market close to log outcomes, compute daily P&L, and update metrics.
"""
import os
import csv
from datetime import datetime
from typing import Dict, List, Optional
from src.trading.paper_trader import PaperTrader
from src.trading.intraday_monitor import IntradayMonitor
from src.utils.logger import get_logger
from src.utils.helpers import get_data_dir, now_ist, load_config

logger = get_logger("stock_ai.trading")


class EODEvaluator:
    """End-of-day trade evaluation and reporting."""

    def __init__(self, trader: Optional[PaperTrader] = None, config: Optional[dict] = None):
        self.trader = trader or PaperTrader()
        self.config = config or load_config()
        self.monitor = IntradayMonitor(self.trader)

    def run_eod_evaluation(self) -> Dict:
        """
        Run complete end-of-day evaluation.
        
        Steps:
        1. Final exit check for any remaining SL/target hits
        2. Close trades exceeding max holding period
        3. Compute daily P&L
        4. Save daily snapshot
        5. Export daily report to CSV
        
        Returns:
            EOD report dictionary
        """
        logger.info("=" * 70)
        logger.info(f"END-OF-DAY EVALUATION — {now_ist().strftime('%Y-%m-%d %H:%M IST')}")
        logger.info("=" * 70)

        # Step 1: Final exit check
        logger.info("Step 1: Final exit check...")
        exit_results = self.monitor.check_exits(force=True)

        # Step 2: Check max holding period
        max_holding = self.config.get("trading", {}).get("max_holding_days", 10)
        logger.info(f"Step 2: Checking max holding period ({max_holding} days)...")
        holding_results = self.monitor.check_max_holding(max_days=max_holding)

        all_closed = exit_results + holding_results

        # Step 3: Get portfolio summary
        logger.info("Step 3: Computing portfolio metrics...")
        summary = self.trader.get_portfolio_summary()

        # Step 4: Save daily snapshot
        logger.info("Step 4: Saving daily snapshot...")
        self.trader.save_daily_snapshot()

        # Step 5: Export daily report
        logger.info("Step 5: Exporting daily report...")
        report = self._build_report(summary, all_closed)
        self._export_report(report)

        # Log summary
        logger.info(f"\n{'─' * 50}")
        logger.info(f"  📊 EOD SUMMARY")
        logger.info(f"  Date: {now_ist().strftime('%Y-%m-%d')}")
        logger.info(f"  Total Capital: ₹{summary['total_capital']:,.2f}")
        logger.info(f"  Open Positions: {summary['open_positions']}")
        logger.info(f"  Trades Closed Today: {len(all_closed)}")
        logger.info(f"  Total P&L: ₹{summary['total_pnl']:,.2f}")
        logger.info(f"  Win Rate: {summary['win_rate']:.1f}%")
        logger.info(f"  Return: {summary['return_pct']:+.2f}%")
        logger.info(f"{'─' * 50}")

        return report

    def _build_report(self, summary: Dict, closed_today: List[Dict]) -> Dict:
        """Build a structured EOD report."""
        today_pnl = sum(t.get("pnl", 0) for t in closed_today)

        return {
            "date": now_ist().strftime("%Y-%m-%d"),
            "total_capital": summary["total_capital"],
            "starting_capital": summary["starting_capital"],
            "current_capital": summary["current_capital"],
            "invested_capital": summary["invested_capital"],
            "open_positions": summary["open_positions"],
            "trades_closed_today": len(closed_today),
            "today_pnl": round(today_pnl, 2),
            "total_pnl": summary["total_pnl"],
            "win_rate": summary["win_rate"],
            "total_trades": summary["total_trades"],
            "best_trade": summary["best_trade"],
            "worst_trade": summary["worst_trade"],
            "return_pct": summary["return_pct"],
            "closed_trades": closed_today,
        }

    def _export_report(self, report: Dict):
        """Export daily report to CSV."""
        report_dir = os.path.join(get_data_dir(), "reports")
        os.makedirs(report_dir, exist_ok=True)

        filepath = os.path.join(report_dir, "daily_performance.csv")
        file_exists = os.path.exists(filepath)

        row = {
            "date": report["date"],
            "total_capital": report["total_capital"],
            "invested_capital": report["invested_capital"],
            "open_positions": report["open_positions"],
            "trades_closed_today": report["trades_closed_today"],
            "today_pnl": report["today_pnl"],
            "total_pnl": report["total_pnl"],
            "win_rate": report["win_rate"],
            "total_trades": report["total_trades"],
            "return_pct": report["return_pct"],
        }

        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=row.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        logger.info(f"Daily report exported to {filepath}")
