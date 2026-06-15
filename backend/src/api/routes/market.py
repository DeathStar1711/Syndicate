"""
Market API routes.
Provides market overview, LLM briefing, and sector data.
"""
import math
from fastapi import APIRouter
from src.utils.logger import get_logger
from src.utils.helpers import load_config, now_ist, is_market_hours

logger = get_logger("stock_ai.api")
router = APIRouter()


def _fetch_clean(ticker: str, period: str = "5d"):
    """Fetch data and drop rows with NaN close (e.g. today before market close)."""
    from src.data.fetcher import fetch_latest
    df = fetch_latest(ticker, period=period)
    if df is not None and not df.empty:
        df = df.dropna(subset=["close"])
    return df


@router.get("/briefing")
async def get_market_briefing():
    """Get today's LLM-generated market briefing."""
    from src.llm.market_briefing import get_cached_briefing, generate_market_briefing

    # Try cached first
    briefing = get_cached_briefing()
    if briefing:
        return {"status": "ok", "briefing": briefing}

    # Generate fresh briefing
    try:
        from src.data.news import fetch_news_google_rss

        nifty_df = _fetch_clean("^NSEI", "5d")
        sensex_df = _fetch_clean("^BSESN", "5d")

        market_data = {}
        if nifty_df is not None and len(nifty_df) >= 2:
            latest = nifty_df.iloc[-1]
            prev = nifty_df.iloc[-2]
            change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100
            market_data["nifty_value"] = round(float(latest["close"]), 2)
            market_data["nifty_change"] = f"{change_pct:+.2f}%"

        if sensex_df is not None and len(sensex_df) >= 2:
            latest = sensex_df.iloc[-1]
            prev = sensex_df.iloc[-2]
            change_pct = ((latest["close"] - prev["close"]) / prev["close"]) * 100
            market_data["sensex_value"] = round(float(latest["close"]), 2)
            market_data["sensex_change"] = f"{change_pct:+.2f}%"

        # VIX
        try:
            vix_df = _fetch_clean("^INDIAVIX", "5d")
            if vix_df is not None and not vix_df.empty:
                market_data["vix_value"] = round(float(vix_df.iloc[-1]["close"]), 2)
        except Exception:
            market_data["vix_value"] = 0

        market_data["nifty_above_ema50"] = "N/A"
        market_data["nifty_above_ema200"] = "N/A"

        # Market headlines
        headlines = fetch_news_google_rss("Indian stock market NSE", max_results=5, days=1)
        headline_text = "\n".join(f"- {h['title']}" for h in headlines) or "No headlines"

        briefing = generate_market_briefing(
            market_data=market_data,
            market_headlines=headline_text,
        )

        if briefing:
            return {"status": "ok", "briefing": briefing}
        else:
            return {"status": "llm_unavailable", "briefing": None}

    except Exception as e:
        logger.error(f"Market briefing generation failed: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/status")
async def get_market_status():
    """Get current market status (open/closed, index values)."""
    is_open = is_market_hours()
    now = now_ist()

    status = {
        "is_open": is_open,
        "current_time": now.strftime("%H:%M IST"),
        "date": now.strftime("%Y-%m-%d"),
        "day": now.strftime("%A"),
    }

    try:
        nifty = _fetch_clean("^NSEI", "5d")
        if nifty is not None and len(nifty) >= 2:
            latest = nifty.iloc[-1]
            prev = nifty.iloc[-2]
            change = float(latest["close"]) - float(prev["close"])
            change_pct = (change / float(prev["close"])) * 100
            status["nifty"] = {
                "value": round(float(latest["close"]), 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            }

        sensex = _fetch_clean("^BSESN", "5d")
        if sensex is not None and len(sensex) >= 2:
            latest = sensex.iloc[-1]
            prev = sensex.iloc[-2]
            change = float(latest["close"]) - float(prev["close"])
            change_pct = (change / float(prev["close"])) * 100
            status["sensex"] = {
                "value": round(float(latest["close"]), 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
            }
    except Exception as e:
        logger.warning(f"Failed to fetch index data: {e}")

    return status


@router.get("/sectors")
async def get_sector_performance():
    """Get sector-wise performance for heatmap."""
    sector_tickers = {
        "IT": "TCS.NS",
        "Banking": "HDFCBANK.NS",
        "Pharma": "SUNPHARMA.NS",
        "Auto": "MARUTI.NS",
        "FMCG": "HINDUNILVR.NS",
        "Energy": "RELIANCE.NS",
        "Metals": "TATASTEEL.NS",
        "Infra": "LT.NS",
        "Telecom": "BHARTIARTL.NS",
        "Realty": "DLF.NS",
    }

    sectors = {}
    for sector, ticker in sector_tickers.items():
        try:
            df = _fetch_clean(ticker, "5d")
            if df is not None and len(df) >= 2:
                latest = float(df.iloc[-1]["close"])
                prev = float(df.iloc[-2]["close"])
                if prev > 0:
                    change_pct = ((latest - prev) / prev) * 100
                    sectors[sector] = {
                        "representative": ticker,
                        "change_pct": round(change_pct, 2),
                    }
        except Exception as e:
            logger.debug(f"Sector data for {sector} ({ticker}) failed: {e}")

    return {"sectors": sectors}


@router.get("/history/{ticker}")
async def get_historical_data(ticker: str, period: str = "3mo"):
    """Get historical OHLCV data formatted for lightweight-charts."""
    try:
        df = _fetch_clean(ticker, period)
        if df is None or df.empty:
            return {"status": "error", "message": "No data found"}
            
        # Format for lightweight-charts: { time: 'YYYY-MM-DD', open, high, low, close }
        chart_data = []
        for timestamp, row in df.iterrows():
            chart_data.append({
                "time": timestamp.strftime("%Y-%m-%d"),
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
                "value": round(float(row["volume"]), 2)  # For volume histogram
            })
            
        return {"status": "ok", "data": chart_data}
    except Exception as e:
        logger.error(f"Failed to fetch history for {ticker}: {e}")
        return {"status": "error", "message": str(e)}
