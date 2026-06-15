from pydantic import BaseModel, Field
from typing import List, Optional, Dict

class CapitalConfig(BaseModel):
    starting_amount: float
    max_risk_per_trade_pct: float
    max_position_pct: float
    max_open_positions: int

class StrategyConfig(BaseModel):
    ema_fast: int
    ema_medium: int
    ema_slow: int
    ema_trend: int
    rsi_period: int
    rsi_overbought: int
    rsi_oversold: int
    macd_fast: int
    macd_slow: int
    macd_signal: int
    atr_period: int
    atr_sl_multiplier: float
    atr_target_multiplier: float
    volume_sma_period: int
    volume_breakout_ratio: float
    volatility_low: int
    volatility_high: int
    volatility_extreme: int
    min_confidence: int
    max_signals: int
    min_signals: int
    min_risk_reward: float

class TradingConfig(BaseModel):
    paper_trading: bool
    slippage_pct: float
    max_holding_days: int
    check_interval_minutes: int

class ScheduleConfig(BaseModel):
    signal_time: str
    market_open: str
    market_close: str
    eod_eval_time: str

class EmailConfig(BaseModel):
    enabled: bool
    send_morning_signals: bool
    send_exit_alerts: bool
    send_daily_report: bool

class LLMFeaturesConfig(BaseModel):
    sentiment_analysis: bool
    signal_validation: bool
    mistake_analysis: bool
    market_briefing: bool

class LLMConfig(BaseModel):
    enabled: bool
    model: str
    timeout_seconds: int
    temperature: float
    features: LLMFeaturesConfig

class MLConfig(BaseModel):
    enabled: bool
    model_type: str
    training_window_years: int
    retrain_frequency: str
    min_oos_improvement: float
    news_feature_weight: float
    mistake_upweight: float
    features: List[str]

class SentimentKeywords(BaseModel):
    positive: List[str]
    negative: List[str]

class NewsConfig(BaseModel):
    enabled: bool
    newsapi_key_env: str
    max_headlines: int
    lookback_days: int
    key_event_keywords: List[str]
    sentiment_keywords: SentimentKeywords

class BacktestConfig(BaseModel):
    start_date: str
    end_date: str
    walk_forward_train_months: int
    walk_forward_test_months: int
    benchmark: str

class LoggingConfig(BaseModel):
    level: str
    log_dir: str
    max_file_size_mb: int
    backup_count: int

class AppConfigSchema(BaseModel):
    capital: CapitalConfig
    strategy: StrategyConfig
    trading: TradingConfig
    schedule: ScheduleConfig
    email: EmailConfig
    llm: LLMConfig
    ml: MLConfig
    news: NewsConfig
    backtest: BacktestConfig
    logging: LoggingConfig
