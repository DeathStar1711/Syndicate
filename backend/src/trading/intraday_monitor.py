"""
Intraday monitoring module.
Checks current prices against stop-loss and target levels for open trades.
Also includes a live WebSocket monitor that records ticks to `tick_data.db`.
"""
from typing import List, Dict, Optional
from src.data.fetcher import get_current_prices
from src.trading.paper_trader import PaperTrader
from src.utils.logger import get_logger
from src.utils.helpers import now_ist, is_market_hours

logger = get_logger("stock_ai.trading")


class IntradayMonitor:
    """Monitors open trades and triggers exits when SL or target is hit."""

    def __init__(self, trader: Optional[PaperTrader] = None):
        self.trader = trader or PaperTrader()

    def _check_ticker_exits(self, ticker: str, current_price: float, open_trades: List[Dict]) -> List[Dict]:
        """Core exit logic for a single ticker to be called by REST or WebSocket."""
        closed_trades = []
        for trade in open_trades:
            if trade["ticker"] != ticker:
                continue

            trade_id = trade["id"]

            if current_price is None:
                logger.warning(f"No price data for {ticker} — skipping")
                continue

            trade_id = trade["id"]
            entry_price = trade["entry_price"]
            stop_loss = trade["stop_loss"]
            target = trade["target"]
            direction = trade.get("direction", "long")

            # Parse trade type from metadata
            import json as _json
            metadata = {}
            if trade.get("metadata"):
                try:
                    metadata = _json.loads(trade["metadata"])
                except (ValueError, TypeError):
                    pass
            trade_type = metadata.get("trade_type", "daily")
            horizon = metadata.get("horizon", "")

            type_label = {"swing": "🔁 Swing", "breakout": "🚨 Breakout", "daily": "⚡ Intraday"}.get(trade_type, "⚡ Intraday")

            logger.debug(
                f"  [{type_label}] {ticker}: Current ₹{current_price:.2f} | "
                f"Entry ₹{entry_price:.2f} | SL ₹{stop_loss:.2f} | Target ₹{target:.2f}"
            )

            # Trailing stop loss logic
            atr = float(metadata.get("atr", 0) or 0)
            if atr > 0:
                if direction == "long":
                    if current_price >= entry_price + 2 * atr:
                        new_sl = entry_price + atr
                    elif current_price >= entry_price + atr:
                        new_sl = entry_price
                    else:
                        new_sl = stop_loss
                    
                    if new_sl > stop_loss:
                        try:
                            from src.db.session import SessionLocal
                            from src.db.models import Trade
                            with SessionLocal() as db:
                                trade_obj = db.query(Trade).filter(Trade.id == trade_id).first()
                                if trade_obj:
                                    trade_obj.stop_loss = new_sl
                                    db.commit()
                            stop_loss = new_sl
                            logger.info(f"📈 Trailing SL raised to Break-Even/Profit for {ticker}: ₹{new_sl:.2f}")
                        except BaseException as e:
                            logger.warning(f"Failed to update trailing SL for {ticker}: {e}")

            # Check exit conditions
            exit_reason = None

            if direction == "long":
                if current_price <= stop_loss:
                    exit_reason = "stop_loss"
                elif current_price >= target:
                    exit_reason = "target"
            else:  # short
                if current_price >= stop_loss:
                    exit_reason = "stop_loss"
                elif current_price <= target:
                    exit_reason = "target"

            if exit_reason:
                result = self.trader.close_trade(trade_id, current_price, exit_reason)
                result["current_price"] = current_price
                result["trade_type"] = trade_type
                result["horizon"] = horizon
                closed_trades.append(result)

                emoji = "🎯" if exit_reason == "target" else "🛑"
                logger.info(
                    f"{emoji} EXIT [{type_label}]: {ticker} | Reason: {exit_reason} | "
                f"Current: ₹{current_price:.2f} | P&L: ₹{result.get('pnl', 0):,.2f}"
            )

        return closed_trades

    def check_exits(self, force: bool = False, prices: Optional[Dict[str, float]] = None) -> List[Dict]:
        """Check all open positions for exit conditions."""
        if not force and not is_market_hours():
            logger.info("Market is closed — skipping intraday check")
            return []

        open_trades = self.trader.get_open_positions()
        if not open_trades:
            return []

        if prices is None:
            tickers = list(set(t["ticker"] for t in open_trades))
            prices = get_current_prices(tickers, use_live_api=True)

        if not prices:
            return []

        all_closed = []
        for ticker, current_price in prices.items():
            if current_price is None:
                continue
            closed = self._check_ticker_exits(ticker, current_price, open_trades)
            all_closed.extend(closed)

        if all_closed:
            logger.info(f"Monitor check complete: {len(all_closed)} exits triggered")
        return all_closed

    def start_live_monitor(self):
        """Start the WebSocket listener to check exits and record ticks in real-time."""
        open_trades = self.trader.get_open_positions()
        tickers = list(set(t["ticker"] for t in open_trades))
        
        if not tickers:
            logger.info("No open positions. Starting live feed for Nifty 50 defaults to build DB.")
            tickers = ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "ICICIBANK.NS"]

        from src.data.groww_feed import GrowwFeedListener
        from src.data.tick_recorder import TickRecorder
        import asyncio

        import time
        recorder = TickRecorder()

        open_trades_cache = self.trader.get_open_positions()
        last_cache_refresh = time.time()

        def on_tick(tick_data):
            nonlocal open_trades_cache, last_cache_refresh
            # 1. Record the tick for future ML
            recorder.record_tick(tick_data)
            
            # Periodically refresh the cache from the DB (every 10 seconds)
            current_time = time.time()
            if current_time - last_cache_refresh >= 10:
                try:
                    latest_open_trades = self.trader.get_open_positions()
                    cache_tickers = {t["ticker"] for t in open_trades_cache}
                    latest_tickers = {t["ticker"] for t in latest_open_trades}
                    new_tickers = list(latest_tickers - cache_tickers)
                    
                    if new_tickers:
                        logger.info(f"New tickers detected in open positions: {new_tickers}. Subscribing...")
                        listener.subscribe_new_tickers(new_tickers)
                    
                    open_trades_cache = latest_open_trades
                    last_cache_refresh = current_time
                except Exception as e:
                    logger.error(f"Error refreshing open trades cache in live monitor: {e}")

            # 2. Check exits instantly
            ticker = tick_data.get("ticker")
            ltp = tick_data.get("ltp")
            if ltp is not None and open_trades_cache:
                closed = self._check_ticker_exits(ticker, ltp, open_trades_cache)
                if closed:
                    # Update cache by removing closed trades
                    closed_ids = {c["trade_id"] for c in closed}
                    open_trades_cache = [t for t in open_trades_cache if t["id"] not in closed_ids]

        listener = GrowwFeedListener(tickers, on_tick)
        asyncio.run(listener.connect_and_listen())

    def check_max_holding(self, max_days: int = 10) -> List[Dict]:
        """
        Close trades that have exceeded maximum holding period.
        Uses 30 days for swing trades, max_days for daily trades.
        
        Args:
            max_days: Maximum holding days for daily trades (default 10)
        
        Returns:
            List of trades that were force-closed
        """
        from datetime import datetime, timedelta
        import json

        open_trades = self.trader.get_open_positions()
        closed = []

        for trade in open_trades:
            entry_date = datetime.fromisoformat(trade["entry_date"])
            days_held = (now_ist() - entry_date).days

            # Determine max holding based on trade type
            metadata = {}
            if trade.get("metadata"):
                try:
                    metadata = json.loads(trade["metadata"])
                except (json.JSONDecodeError, TypeError):
                    pass

            trade_type = metadata.get("trade_type", "daily")
            trade_max_days = 30 if trade_type == "swing" else max_days

            if days_held >= trade_max_days:
                ticker = trade["ticker"]
                from src.data.fetcher import get_current_price
                current_price = get_current_price(ticker)

                if current_price:
                    result = self.trader.close_trade(trade["id"], current_price, "max_holding")
                    closed.append(result)
                    logger.info(
                        f"⏰ MAX HOLDING ({trade_type}): {ticker} closed after {days_held} days | "
                        f"P&L: ₹{result.get('pnl', 0):,.2f}"
                    )

        return closed
