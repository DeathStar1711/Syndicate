import os
import sys

# Ensure backend directory is in path
sys.path.append(os.path.join(os.getcwd(), 'backend'))

from src.data.groww_mcp import fetch_fundamentals_screener_sync
from src.data.fetcher import fetch_batch
from src.features.technical import compute_all_indicators
from src.strategy.rules import StrategyEngine
from src.utils.helpers import load_config

def debug_strategy():
    config = load_config()
    
    print("Fetching fundamental tickers...")
    query = "high ROE, low debt to equity, high profit margins"
    results = fetch_fundamentals_screener_sync(query, max_results=15)
    tickers = []
    for r in results:
        code = r.get("nse_script_code")
        if code and f"{code}.NS" not in tickers:
            tickers.append(f"{code}.NS")
    
    tickers = tickers[:15]
    print(f"Tickers to evaluate: {tickers}")
    
    data = fetch_batch(tickers, period="1y", interval="1d")
    
    engine = StrategyEngine(config)
    
    for ticker, df in data.items():
        if df is None or len(df) < 200:
            print(f"{ticker}: Skipped (insufficient data)")
            continue
            
        df_with_features = compute_all_indicators(df, config.get("strategy", {}))
        latest = df_with_features.iloc[-1]
        
        # Check trend
        trend = latest.get("trend", "sideways")
        strong_trend = latest.get("strong_trend", "neutral")
        
        close = latest["close"]
        ema9 = latest["ema_9"]
        ema20 = latest["ema_20"]
        ema50 = latest["ema_50"]
        
        print(f"\n{ticker}:")
        print(f"  Close: {close:.2f} | EMA9: {ema9:.2f} | EMA20: {ema20:.2f} | EMA50: {ema50:.2f}")
        print(f"  Trend: {trend} | Strong Trend: {strong_trend}")
        
        direction = engine._determine_direction(latest)
        print(f"  Determined Direction: {direction}")
        
        if direction != "long":
            print(f"  -> REJECTED: Not in a bullish trend (Only long trades allowed)")
            continue
            
        signal = engine.evaluate(df_with_features, ticker)
        if signal is None:
            print(f"  -> REJECTED by StrategyEngine.evaluate() (likely confidence score < 55)")
        else:
            print(f"  -> ACCEPTED with confidence {signal['confidence']}")

if __name__ == "__main__":
    debug_strategy()
