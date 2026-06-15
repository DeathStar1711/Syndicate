import asyncio
from src.llm.signal_validator import validate_signal

def test_validation():
    mock_signal = {
        "ticker": "RELIANCE",
        "direction": "long",
        "entry_price": 2500,
        "stop_loss": 2400,
        "target": 2700,
        "confidence": 75,
        "trend": "bullish",
        "rsi": 65,
        "scores": {"momentum": "high"},
        "volume_ratio": 1.2,
        "adx": 25
    }
    
    result = validate_signal(
        signal=mock_signal,
        news_context="Reliance announces major 5G expansion.",
        market_context="Nifty is slightly bullish today.",
        mistake_history="Last time, we entered too early on a fake breakout."
    )
    
    print("FINAL RESULT:", result)

if __name__ == "__main__":
    test_validation()
