"""
ML training pipeline for confidence adjustment.
Uses scikit-learn to train logistic regression or random forest models.
"""
import os
import pickle
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score, TimeSeriesSplit, cross_val_predict, RandomizedSearchCV
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.metrics import accuracy_score, classification_report, precision_score, recall_score, precision_recall_curve
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb
import joblib

from src.data.historical import load_historical
from src.features.technical import compute_all_indicators
from src.features.technical import compute_all_indicators
from src.features.sentiment import compute_news_features
from src.data.market_context import get_market_features
from src.utils.logger import get_logger
from src.utils.helpers import load_config, get_data_dir, get_tickers

logger = get_logger("stock_ai.ml")


# Primary features (technical — always highest importance)
TECHNICAL_FEATURE_COLUMNS = [
    "ema_9_slope", "ema_20_slope", "rsi_14", "macd_histogram",
    "volume_ratio", "atr_percentile", "returns_1d", "returns_5d",
    "adx", "bb_width", "stoch_k", "stoch_d",
    "sr_proximity", "is_doji", "bullish_engulfing", "bearish_engulfing",
    "rs_vs_index_1d", "rs_vs_index_5d",
    "vwap_distance_10d", "hist_volatility_20d", "vpt_slope_5d",
    "day_of_week", "is_month_end",
]

# Secondary features (news — minute bias, capped importance)
# Secondary features (news — minute bias, capped importance)
NEWS_FEATURE_COLUMNS = [
    "news_sentiment_score", "news_volume", "news_recency_score",
]

# Market Context features (global — high importance)
MARKET_FEATURE_COLUMNS = [
    "nifty_return_1d", "nifty_return_5d",
    "nifty_above_ema50", "nifty_above_ema200",
    "vix_level", "vix_regime", "market_signal"
]

# Combined feature set
FEATURE_COLUMNS = TECHNICAL_FEATURE_COLUMNS + NEWS_FEATURE_COLUMNS + MARKET_FEATURE_COLUMNS


class MLTrainer:
    """Train and evaluate ML models for confidence adjustment."""

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        self.ml_config = self.config.get("ml", {})
        self.model_type = self.ml_config.get("model_type", "xgboost")  # Default to xgboost now
        self.training_window_years = self.ml_config.get("training_window_years", 2)
        self.model_dir = os.path.join(get_data_dir(), "models")
        os.makedirs(self.model_dir, exist_ok=True)

    def prepare_features(self, tickers: Optional[List[str]] = None) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare feature matrix and labels from historical data.
        
        Labels:
            1 = price goes up more than 1% in next 5 days (bullish)
            0 = price stays flat or drops (not bullish)
        
        Features include both technical indicators (primary) and
        news sentiment features (secondary, minute bias).
        """
        tickers = tickers or get_tickers()
        strategy_config = self.config.get("strategy", {})
        
        # Pre-fetch market context features (once for all stocks)
        market_df = get_market_features(period=f"{self.training_window_years + 1}y")
        if market_df.empty:
            logger.warning("Market context data unavailable — using default neutral values")

        # Fetch index data for relative strength
        from src.data.fetcher import fetch_index
        index_df = fetch_index("^NSEI", period=f"{self.training_window_years + 1}y")

        all_features = []
        all_labels = []

        for ticker in tickers:
            try:
                df = load_historical(ticker)
                if df is None or len(df) < 250:
                    continue

                # Filter to training window
                cutoff = datetime.now() - timedelta(days=self.training_window_years * 365)
                df.index = pd.to_datetime(df.index)
                # Strip timezone info to avoid tz-naive vs tz-aware comparison
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                df = df[df.index >= cutoff]

                if len(df) < 200:
                    continue

                # Compute technical indicators
                df = compute_all_indicators(df, strategy_config, index_df=index_df)

                # Compute news sentiment features (secondary input)
                try:
                    news_feats = compute_news_features(ticker)
                    for col, val in news_feats.items():
                        df[col] = val  # broadcast scalar to all rows
                except Exception as e:
                    logger.debug(f"News features unavailable for {ticker}: {e}")
                    for col in NEWS_FEATURE_COLUMNS:
                        df[col] = 0.0  # neutral fallback

                # Merge Market Context Features
                if not market_df.empty:
                    # Join on index (Date)
                    df = df.join(market_df, how="left")
                    # Forward fill any missing market data (e.g. holidays)
                    df[MARKET_FEATURE_COLUMNS] = df[MARKET_FEATURE_COLUMNS].ffill()
                else:
                    for col in MARKET_FEATURE_COLUMNS:
                        df[col] = 0.0  # fallback

                # Create label: 1 if price rises >1% in next 5 days
                df["future_return_5d"] = df["close"].shift(-5) / df["close"] - 1
                df["label"] = (df["future_return_5d"] > 0.01).astype(int)

                # Select features
                feature_cols = [c for c in FEATURE_COLUMNS if c in df.columns]
                df_clean = df[feature_cols + ["label"]].dropna()

                if len(df_clean) > 50:
                    all_features.append(df_clean[feature_cols])
                    all_labels.append(df_clean["label"])

            except Exception as e:
                logger.warning(f"Error preparing features for {ticker}: {e}")
                continue

        if not all_features:
            logger.error("No features prepared — insufficient data")
            return pd.DataFrame(), pd.Series(dtype=float)

        X = pd.concat(all_features, ignore_index=True)
        y = pd.concat(all_labels, ignore_index=True)

        logger.info(f"Prepared {len(X)} samples from {len(all_features)} tickers")
        logger.info(f"  Technical features: {len(TECHNICAL_FEATURE_COLUMNS)}")
        logger.info(f"  Technical features: {len(TECHNICAL_FEATURE_COLUMNS)}")
        logger.info(f"  News features: {len(NEWS_FEATURE_COLUMNS)}")
        logger.info(f"  Market features: {len(MARKET_FEATURE_COLUMNS)}")
        logger.info(f"Label distribution: {y.value_counts().to_dict()}")

        return X, y

    def train(self, X: pd.DataFrame, y: pd.Series, sample_weights: Optional[np.ndarray] = None) -> Dict:
        """
        Train the ML model and return training metrics.
        
        Args:
            X: Feature matrix
            y: Labels
            sample_weights: Optional per-sample weights (used to upweight
                           past mistake samples during retraining)
        
        Returns:
            Dictionary with model, scaler, and performance metrics
        """
        if len(X) < 100:
            logger.error("Insufficient samples for training")
            return {"error": "Insufficient data"}

        # Split: last 20% for OOS validation (before scaling to avoid leakage)
        split_idx = int(len(X) * 0.8)
        X_train_raw = X.iloc[:split_idx]
        X_test_raw = X.iloc[split_idx:]
        y_train = y.iloc[:split_idx]
        y_test = y.iloc[split_idx:]

        # Scale features using RobustScaler (handles financial outliers better than Standard)
        scaler = RobustScaler()
        X_train = scaler.fit_transform(X_train_raw)
        X_test = scaler.transform(X_test_raw)
        X_scaled = scaler.transform(X)

        # Prepare sample weights for training split
        train_weights = None
        if sample_weights is not None:
            train_weights = sample_weights[:split_idx]
            logger.info(f"  Using sample weights (min={train_weights.min():.2f}, "
                       f"max={train_weights.max():.2f}, "
                       f"upweighted={np.sum(train_weights > 1.0)} samples)")

        # Train model with Hyperparameter Tuning and class-weight balancing
        tscv_search = TimeSeriesSplit(n_splits=5, gap=5)
        
        if self.model_type == "logistic_regression":
            base_model = LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
            param_distributions = {
                'C': [0.01, 0.1, 1, 10, 100],
                'solver': ['liblinear', 'lbfgs']
            }
        elif self.model_type == "xgboost":
            # Scale pos weight for imbalanced learning: (negative samples / positive samples)
            pos_ratio = len(y_train) / sum(y_train) - 1 if sum(y_train) > 0 else 1
            base_model = xgb.XGBClassifier(random_state=42, n_jobs=-1, scale_pos_weight=pos_ratio)
            param_distributions = {
                'n_estimators': [100, 200, 300],
                'max_depth': [3, 5, 7],
                'learning_rate': [0.01, 0.05, 0.1],
                'subsample': [0.8, 1.0],
                'colsample_bytree': [0.8, 1.0]
            }
        else:
            base_model = RandomForestClassifier(random_state=42, n_jobs=-1, class_weight='balanced')
            param_distributions = {
                'n_estimators': [50, 100, 200],
                'max_depth': [5, 10, 20, None],
                'min_samples_leaf': [1, 2, 4]
            }

        search = RandomizedSearchCV(
            base_model, param_distributions, n_iter=10, scoring='precision', 
            cv=tscv_search, random_state=42, n_jobs=-1
        )
        
        fit_kwargs = {'sample_weight': train_weights} if train_weights is not None else {}
        search.fit(X_train, y_train, **fit_kwargs)
        
        logger.info(f"  Best params: {search.best_params_}")
        
        # Calibrate probabilities for true mathematical probability outputs
        # We use 'isotonic' for >1000 samples generally, but 'sigmoid' (Platt Scaling) is safer for smaller sets.
        calibrator = CalibratedClassifierCV(estimator=search.best_estimator_, method='sigmoid', cv=5)
        calibrator.fit(X_train, y_train, sample_weight=train_weights)
        
        model = calibrator

        # Evaluate
        train_score = accuracy_score(y_train, model.predict(X_train))
        test_score = accuracy_score(y_test, model.predict(X_test))
        
        # Use TimeSeriesSplit for CV to prevent leakage (gap=5 embargos the label overlap)
        tscv = TimeSeriesSplit(n_splits=5, gap=5)
        cv_scores = cross_val_score(model, X_scaled, y, cv=tscv, scoring='precision')

        # -----------------------------------------------------
        # PRECISION OPTIMIZATION (Dynamic Threshold)
        # -----------------------------------------------------
        # 1. Calculate Baseline Precision (Random Guess)
        baseline_precision = y.sum() / len(y)
        logger.info(f"  Baseline Precision (Random): {baseline_precision:.4f}")

        # 2. Get OOS probabilities for the test set
        y_probs = model.predict_proba(X_test)[:, 1]
        
        # 3. Find optimal threshold for Precision > 1.5x Baseline (or min 0.65)
        precisions, recalls, thresholds = precision_recall_curve(y_test, y_probs)
        
        optimal_threshold = 0.5
        best_precision = 0.0
        
        target_precision = max(0.65, baseline_precision * 1.5)
        
        # Find lowest threshold that meets target precision
        # (We want to maximize Recall while keeping Precision high)
        found_threshold = False
        for p, t in zip(precisions[:-1], thresholds):
            if p >= target_precision:
                optimal_threshold = t
                best_precision = p
                found_threshold = True
                break  # Found the first (lowest) threshold meeting criteria
        
        if not found_threshold:
            # Fallback: Find threshold maximizing F1 score if target not met
            precisions_sliced = precisions[:-1]
            recalls_sliced = recalls[:-1]
            f1_scores = 2 * (precisions_sliced * recalls_sliced) / (precisions_sliced + recalls_sliced + 1e-9)
            best_f1_idx = np.argmax(f1_scores)
            optimal_threshold = thresholds[best_f1_idx]
            best_precision = precisions_sliced[best_f1_idx]
            logger.warning(f"  Target precision {target_precision:.2f} not met. optimizing for F1.")

        # 4. Evaluate at Optimal Threshold
        y_pred_opt = (y_probs >= optimal_threshold).astype(int)
        final_precision = precision_score(y_test, y_pred_opt, zero_division=0)
        final_recall = recall_score(y_test, y_pred_opt, zero_division=0)
        
        logger.info(f"  Optimal Threshold: {optimal_threshold:.4f}")
        logger.info(f"  Precision @ Threshold: {final_precision:.4f} (Baseline: {baseline_precision:.4f})")
        logger.info(f"  Recall @ Threshold: {final_recall:.4f}")

        # Feature importance (must extract from the base estimator inside the calibrator)
        base_est = model.estimator if hasattr(model, "estimator") else model
        if hasattr(base_est, "feature_importances_"):
            importance = dict(zip(X.columns, base_est.feature_importances_))
        elif hasattr(base_est, "coef_"):
            importance = dict(zip(X.columns, abs(base_est.coef_[0])))
        else:
            importance = {}

        # Log news feature importance separately
        news_importance = {
            k: v for k, v in importance.items() if k in NEWS_FEATURE_COLUMNS
        }
        tech_importance = {
            k: v for k, v in importance.items() if k in TECHNICAL_FEATURE_COLUMNS
        }
        market_importance = {
            k: v for k, v in importance.items() if k in MARKET_FEATURE_COLUMNS
        }

        results = {
            "model": model,
            "scaler": scaler,
            "threshold": float(optimal_threshold),
            "train_accuracy": round(train_score, 4),
            "test_accuracy": round(test_score, 4),
            "test_precision": round(final_precision, 4),
            "test_recall": round(final_recall, 4),
            "baseline_precision": round(baseline_precision, 4),
            "cv_mean": round(cv_scores.mean(), 4),
            "cv_std": round(cv_scores.std(), 4),
            "feature_importance": importance,
            "technical_importance": tech_importance,
            "news_importance": news_importance,
            "market_importance": market_importance,
            "samples": len(X),
            "model_type": self.model_type,
            "training_date": datetime.now().isoformat(),
        }

        logger.info(f"Training complete:")
        logger.info(f"  CV Precision: {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        if news_importance:
            total_imp = sum(importance.values()) or 1.0
            news_pct = sum(news_importance.values()) / total_imp * 100
            logger.info(f"  News feature importance: {news_pct:.1f}% of total")

        return results

    def save_model(self, model, scaler, metadata: Dict):
        """Save trained model and scaler to disk."""
        model_path = os.path.join(self.model_dir, "model_latest.pkl")
        scaler_path = os.path.join(self.model_dir, "scaler_latest.pkl")
        meta_path = os.path.join(self.model_dir, "model_metadata.pkl")

        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        joblib.dump(metadata, meta_path)

        logger.info(f"Model saved to {model_path}")

    def load_model(self):
        """Load the latest trained model."""
        model_path = os.path.join(self.model_dir, "model_latest.pkl")
        scaler_path = os.path.join(self.model_dir, "scaler_latest.pkl")

        if not os.path.exists(model_path):
            logger.warning("No trained model found")
            return None, None

        model = joblib.load(model_path)
        scaler = joblib.load(scaler_path)
        return model, scaler
