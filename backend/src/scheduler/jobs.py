"""
APScheduler jobs replacing GitHub Actions cron.
All jobs run in IST timezone.
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.scheduler")


def start_scheduler() -> BackgroundScheduler:
    """Create and start the APScheduler with all trading jobs."""
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")

    # Morning market briefing — hourly Mon-Fri during market hours (8:45, 10:00, 11:00, ...)
    scheduler.add_job(job_market_briefing, CronTrigger(minute=0, hour="8-15", day_of_week="mon-fri"), id="market_briefing", replace_existing=True)

    # Morning signals — 9:10 AM Mon-Fri
    scheduler.add_job(job_generate_signals, CronTrigger(hour=9, minute=10, day_of_week="mon-fri"), id="morning_signals", replace_existing=True)

    # Intraday monitor — every 5 min, 9:15-15:30 Mon-Fri
    scheduler.add_job(job_intraday_monitor, CronTrigger(minute="*/5", hour="9-15", day_of_week="mon-fri"), id="intraday_monitor", replace_existing=True)

    # EOD evaluation — 3:45 PM Mon-Fri
    scheduler.add_job(job_eod_evaluation, CronTrigger(hour=15, minute=45, day_of_week="mon-fri"), id="eod_evaluation", replace_existing=True)

    # Price broadcast — every 5 seconds during market hours
    scheduler.add_job(job_broadcast_prices, "interval", seconds=5, id="price_broadcast", replace_existing=True)

    # Weekly retrain — Sunday 11:30 PM
    scheduler.add_job(job_weekly_retrain, CronTrigger(hour=23, minute=30, day_of_week="sun"), id="weekly_retrain", replace_existing=True)

    scheduler.start()
    logger.info("✅ Scheduler started with 6 jobs")
    return scheduler


def job_market_briefing():
    """Generate the morning market briefing via LLM."""
    try:
        logger.info("⏰ [Scheduler] Market briefing job started")
        from src.api.routes.market import get_market_briefing
        import asyncio
        asyncio.run(get_market_briefing())
    except Exception as e:
        logger.error(f"Market briefing job failed: {e}")


def job_generate_signals():
    """Generate morning trade signals."""
    try:
        logger.info("⏰ [Scheduler] Signal generation job started")
        from src.api.routes.signals import _run_signal_generation
        _run_signal_generation()
    except Exception as e:
        logger.error(f"Signal generation job failed: {e}")


def job_intraday_monitor():
    """Check open trades for SL/target hits."""
    from src.utils.helpers import is_market_hours
    if not is_market_hours():
        return
    try:
        from src.trading.intraday_monitor import IntradayMonitor
        monitor = IntradayMonitor()
        closed = monitor.check_exits()
        if closed:
            logger.info(f"⏰ [Scheduler] Monitor: {len(closed)} exits triggered")
            # Broadcast exits
            try:
                from src.api.websocket import broadcast_event
                import asyncio
                asyncio.run(broadcast_event("trade_exits", closed))
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Intraday monitor job failed: {e}")


def job_eod_evaluation():
    """End-of-day evaluation and snapshot."""
    try:
        logger.info("⏰ [Scheduler] EOD evaluation started")
        from src.trading.paper_trader import PaperTrader
        trader = PaperTrader()
        trader.save_daily_snapshot()
    except Exception as e:
        logger.error(f"EOD evaluation failed: {e}")


def job_broadcast_prices():
    """Broadcast live prices to WebSocket clients (throttled to every 5s)."""
    from src.utils.helpers import is_market_hours
    if not is_market_hours():
        return
    try:
        from src.api.websocket import manager
        if not manager.active:
            return  # No clients connected

        from src.trading.paper_trader import PaperTrader
        trader = PaperTrader()
        open_positions = trader.get_open_positions()
        if not open_positions:
            return

        tickers = list(set(p["ticker"] for p in open_positions))
        from src.data.fetcher import get_current_prices
        prices = get_current_prices(tickers, use_live_api=True)

        if prices:
            import asyncio
            from src.api.websocket import broadcast_prices
            asyncio.run(broadcast_prices(prices))
    except Exception as e:
        logger.debug(f"Price broadcast failed: {e}")


def job_weekly_retrain():
    """Weekly ML model retraining."""
    try:
        logger.info("⏰ [Scheduler] Weekly retrain started")
        from src.ml.retrain import retrain_model
        result = retrain_model()
        logger.info(f"Retrain result: {result.get('status', '?')}")
    except Exception as e:
        logger.error(f"Weekly retrain failed: {e}")
