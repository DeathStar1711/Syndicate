"""
ML predictor module.
Loads trained model and adjusts confidence scores for trade signals.
IMPORTANT: ML only adjusts confidence — it never overrides risk management rules.
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from src.ml.trainer import MLTrainer, FEATURE_COLUMNS, NEWS_FEATURE_COLUMNS, MARKET_FEATURE_COLUMNS
from src.features.sentiment import compute_news_features
from src.data.market_context import get_market_features
from src.utils.logger import get_logger
from src.utils.helpers import load_config

logger = get_logger("stock_ai.ml")


class MLPredictor:
    """Use trained ML model to adjust strategy confidence scores."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.ml_config = self.config.get("ml", {})
        self.enabled = self.ml_config.get("enabled", False)
        self.model = None
        self.scaler = None
        self.threshold = 0.5  # Default
        self.market_features = None
        self._loaded = False

    def _ensure_loaded(self):
        """Lazy-load the model on first use."""
        if self._loaded:
            return
        self._loaded = True

        if not self.enabled:
            logger.info("ML predictions disabled in config")
            return

        trainer = MLTrainer(self.config)
        self.model, self.scaler = trainer.load_model()

        if self.model is None:
            logger.warning("No ML model available — predictions will be skipped")
        else:
            # Load metadata for threshold
            try:
                import os
                import joblib
                from src.utils.helpers import get_data_dir
                meta_path = os.path.join(get_data_dir(), "models", "model_metadata.pkl")
                if os.path.exists(meta_path):
                    meta = joblib.load(meta_path)
                    self.threshold = meta.get("threshold", 0.65)
                    logger.info(f"Loaded ML model with threshold: {self.threshold:.2f}")
            except Exception as e:
                logger.warning(f"Could not load model metadata: {e}")

            # Pre-fetch market features (lazy load)
            try:
                # Fetch last 5 days to ensure we get latest
                market_df = get_market_features(period="1mo")
                if not market_df.empty:
                    self.market_features = market_df.iloc[-1]
                    logger.info("Market features loaded for inference")
            except Exception as e:
                logger.warning(f"Failed to load market features for inference: {e}")

    def adjust_confidence(self, signal: Dict, features_df: pd.DataFrame) -> Dict:
        """
        Adjust a signal's confidence score using ML prediction.
        
        The ML model predicts the probability of a bullish move.
        This adjusts the confidence score by ±10 points max.
        
        IMPORTANT: This NEVER overrides stop-loss, target, or position sizing rules.
        
        Args:
            signal: Trade signal dictionary
            features_df: DataFrame with computed indicators (latest row used)
        
        Returns:
            Modified signal with adjusted confidence
        """
        self._ensure_loaded()

        if self.model is None or not self.enabled:
            return signal

        try:
            # Extract technical features from latest row
            latest = features_df.iloc[-1]
            feature_values = []

            # Get news features for this ticker
            ticker = signal.get("ticker", "")
            try:
                news_feats = compute_news_features(ticker)
            except Exception:
                news_feats = {c: 0.0 for c in NEWS_FEATURE_COLUMNS}

            for col in FEATURE_COLUMNS:
                if col in NEWS_FEATURE_COLUMNS:
                    # Use live news features
                    val = news_feats.get(col, 0.0)
                elif col in MARKET_FEATURE_COLUMNS:
                    # Use market features
                    if self.market_features is not None:
                        val = self.market_features.get(col, 0.0)
                    else:
                        val = 0.0
                else:
                    # Use technical features from DataFrame
                    val = latest.get(col, np.nan)
                feature_values.append(float(val) if not pd.isna(val) else 0.0)

            X = np.array(feature_values).reshape(1, -1)
            X_scaled = self.scaler.transform(X)

            # Get probability prediction
            proba = self.model.predict_proba(X_scaled)[0]
            bullish_prob = proba[1] if len(proba) > 1 else proba[0]

            # Adjust confidence: Based on dynamic threshold
            # If P > Threshold, boost confidence.
            # If P < Baseline, reduce confidence.
            
            original_confidence = signal["confidence"]
            direction = signal.get("direction", "long")
            
            if direction == "long":
                if bullish_prob >= self.threshold:
                    boost_factor = (bullish_prob - self.threshold) / (1.0 - self.threshold + 1e-6)
                    adjustment = 10 + int(boost_factor * 10)
                elif bullish_prob < 0.40:
                    adjustment = -15
                else:
                    adjustment = 0
            else: # short
                # For short trades, we want LOW bullish probability
                bearish_prob = 1.0 - bullish_prob
                if bearish_prob >= self.threshold:
                    boost_factor = (bearish_prob - self.threshold) / (1.0 - self.threshold + 1e-6)
                    adjustment = 10 + int(boost_factor * 10)
                elif bearish_prob < 0.40:
                    adjustment = -15
                else:
                    adjustment = 0

            new_confidence = max(0, min(100, original_confidence + adjustment))

            signal["confidence"] = new_confidence
            signal["ml_probability"] = round(bullish_prob, 4)
            signal["ml_adjustment"] = adjustment
            signal["original_confidence"] = original_confidence

            if adjustment != 0:
                logger.info(
                    f"ML adjustment for {signal['ticker']}: "
                    f"{original_confidence} → {new_confidence} "
                    f"(prob={bullish_prob:.2f}, adj={adjustment:+d})"
                )

        except Exception as e:
            logger.warning(f"ML prediction failed for {signal.get('ticker', '?')}: {e}")
            # Graceful fallback — return signal unchanged

        return signal

    def batch_adjust(self, signals: List[Dict], features_dict: Dict[str, pd.DataFrame]) -> List[Dict]:
        """
        Adjust confidence for a batch of signals.
        
        Args:
            signals: List of trade signal dictionaries
            features_dict: Dictionary mapping ticker -> features DataFrame
        
        Returns:
            List of signals with adjusted confidence scores
        """
        adjusted = []
        for signal in signals:
            ticker = signal.get("ticker")
            if ticker in features_dict:
                signal = self.adjust_confidence(signal, features_dict[ticker])
            adjusted.append(signal)
        return adjusted
