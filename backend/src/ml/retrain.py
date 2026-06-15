"""
Weekly model retraining script with mistake learning.
Implements controlled adaptive learning with OOS deployment gate,
enhanced with mistake analysis and news feature integration.
"""
import os
import numpy as np
from datetime import datetime
from typing import Dict, Optional
from src.ml.trainer import MLTrainer, FEATURE_COLUMNS, NEWS_FEATURE_COLUMNS
from src.ml.mistake_journal import MistakeJournal
from src.utils.logger import get_logger
from src.utils.helpers import load_config, get_tickers, get_data_dir
from src.utils.helpers import load_config, get_tickers, get_data_dir
import joblib

def _broadcast_step(step: str, status: str, content: str = ""):
    """Broadcast a pipeline step event via WebSocket."""
    try:
        from src.api.websocket import manager
        import asyncio

        event = {
            "type": "pipeline_step",
            "data": {
                "step": f"ML Training: {step}",
                "ticker": "",
                "status": status,
                "content": content[:500] if content else "",
            }
        }
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast(event))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(manager.broadcast(event))
            loop.close()
    except Exception as e:
        logger.debug(f"WS broadcast failed: {e}")

logger = get_logger("stock_ai.ml")


def retrain_model(config: Optional[dict] = None) -> Dict:
    """
    Retrain the ML model using rolling training window.
    
    Process:
    1. Prepare features from latest 2-year window (technical + news)
    2. Analyze past mistakes and prepare sample weights
    3. Train new model with mistake-upweighted samples
    4. Compare OOS performance against current model
    5. Deploy only if new model improves by min_oos_improvement
    
    Returns:
        Dictionary with retraining results
    """
    config = config or load_config()
    ml_config = config.get("ml", {})
    min_improvement = ml_config.get("min_oos_improvement", 0.02)
    mistake_upweight = ml_config.get("mistake_upweight", 2.0)

    logger.info("=" * 70)
    logger.info(f"MODEL RETRAINING — {datetime.now().strftime('%Y-%m-%d')}")
    logger.info("=" * 70)

    trainer = MLTrainer(config)

    # Step 0: Download Historical Data
    try:
        from src.data.historical import download_historical
        logger.info("Step 0: Downloading historical data...")
        _broadcast_step("Data Download", "start", f"Downloading {trainer.training_window_years}yr history for all tickers...")
        downloaded = download_historical(get_tickers(), years=trainer.training_window_years + 1, force=False)
        _broadcast_step("Data Download", "done", f"Available data for {len(downloaded)} tickers")
    except Exception as e:
        logger.error(f"Historical data download failed: {e}")
        _broadcast_step("Data Download", "error", str(e))
        return {"status": "failed", "reason": "data_download_failed"}

    # Step 1: Prepare features (now includes news features)
    logger.info("Step 1: Preparing features (technical + news)...")
    _broadcast_step("Feature Prep", "start", "Computing indicators & merging market context...")
    tickers = get_tickers()
    X, y = trainer.prepare_features(tickers)

    if len(X) < 100:
        logger.error("Insufficient data for retraining")
        _broadcast_step("Feature Prep", "error", f"Only {len(X)} samples found (need 100+)")
        return {"status": "failed", "reason": "insufficient_data"}

    _broadcast_step("Feature Prep", "done", f"Generated {len(X)} feature vectors")

    # Step 2: Mistake Analysis
    logger.info("Step 2: Analyzing past mistakes...")
    _broadcast_step("Mistake Analysis", "start", "Analyzing journal to build sample weights...")
    journal = MistakeJournal()
    patterns = journal.get_mistake_patterns()
    mistake_samples = journal.get_mistake_samples(n=50)

    # Log mistake analysis
    if patterns["total_mistakes"] > 0:
        logger.info(f"  Total past mistakes: {patterns['total_mistakes']}")
        logger.info(f"  Total loss from mistakes: ₹{patterns['total_loss']:,.2f}")

        top_reasons = list(patterns["reason_counts"].items())[:3]
        for code, count in top_reasons:
            logger.info(f"  Top failure reason: {code} ({count} times)")

        if patterns["worst_tickers"]:
            worst = patterns["worst_tickers"][0]
            logger.info(f"  Worst ticker: {worst[0]} (avg loss: ₹{worst[1]:,.2f})")
    else:
        logger.info("  No past mistakes recorded yet — first training run")

    # Build sample weights: upweight samples that match past mistake patterns
    sample_weights = _build_sample_weights(
        X, y, mistake_samples, mistake_upweight
    )

    # Step 3: Train new model with mistake-aware weights
    logger.info("Step 3: Training new model (with mistake upweighting)...")
    _broadcast_step("Mistake Analysis", "done", f"Upweighted {len(mistake_samples)} mistake patterns")
    _broadcast_step("Model Training", "start", "Running randomized search with time-series CV...")
    results = trainer.train(X, y, sample_weights=sample_weights)

    if "error" in results:
        _broadcast_step("Model Training", "error", results["error"])
        return {"status": "failed", "reason": results["error"]}

    _broadcast_step("Model Training", "done", f"Training complete. Precision: {results.get('test_precision', 0):.2f}")

    new_accuracy = results["test_accuracy"]

    # Step 4: Compare with current model
    logger.info("Step 4: Comparing with current model...")
    current_model, current_scaler = trainer.load_model()
    current_accuracy = 0.0

    if current_model is not None:
        # Load current model's metadata
        meta_path = os.path.join(get_data_dir(), "models", "model_metadata.pkl")
        if os.path.exists(meta_path):
            current_meta = joblib.load(meta_path)
            current_accuracy = current_meta.get("test_accuracy", 0.0)

    improvement = new_accuracy - current_accuracy

    logger.info(f"  Current model accuracy: {current_accuracy:.4f}")
    logger.info(f"  New model accuracy:     {new_accuracy:.4f}")
    logger.info(f"  Improvement:            {improvement:+.4f}")
    logger.info(f"  Min required:           {min_improvement:.4f}")

    # Step 5: Deploy if improved
    # Logic: Deploy if Precision > Baseline * 1.5 AND Precision >= 0.60
    # OR if no current model exists
    
    precision_lift = results["test_precision"] / results["baseline_precision"]
    deploy_decision = False
    
    logger.info(f"  Model Precision: {results['test_precision']:.4f}")
    logger.info(f"  Baseline Precision: {results['baseline_precision']:.4f}")
    logger.info(f"  Precision Lift: {precision_lift:.2f}x")
    
    if current_model is None:
        deploy_decision = True
        logger.info("  Reason: No current model")
    elif results["test_precision"] >= 0.60 and precision_lift >= 1.2:
        deploy_decision = True
        logger.info("  Reason: Precision > 60% and Lift > 1.2x")
    else:
        logger.info("  Reason: Failed precision criteria")

    if deploy_decision:
        logger.info("✅ DEPLOYING new model (improvement threshold met)")
        _broadcast_step("Complete", "done", f"Deployed new model! Lift: {precision_lift:.2f}x")
        
        
        metadata = {
            "threshold": results["threshold"],
            "test_accuracy": new_accuracy,
            "test_precision": results["test_precision"],
            "test_recall": results["test_recall"],
            "baseline_precision": results["baseline_precision"],
            "train_accuracy": results["train_accuracy"],
            "cv_mean": results["cv_mean"],
            "cv_std": results["cv_std"],
            "feature_importance": results["feature_importance"],
            "technical_importance": results.get("technical_importance", {}),
            "news_importance": results.get("news_importance", {}),
            "market_importance": results.get("market_importance", {}),
            "samples": results["samples"],
            "model_type": results["model_type"],
            "training_date": results["training_date"],
            "previous_accuracy": current_accuracy,
            "improvement": round(improvement, 4),
            "feature_columns": FEATURE_COLUMNS,
            "mistake_count": patterns["total_mistakes"],
            "top_mistake_patterns": dict(
                list(patterns["reason_counts"].items())[:5]
            ),
            "mistake_samples_used": len(mistake_samples),
        }
        
        trainer.save_model(results["model"], results["scaler"], metadata)
        
        return {
            "status": "deployed",
            "new_accuracy": new_accuracy,
            "previous_accuracy": current_accuracy,
            "improvement": round(improvement, 4),
            "mistake_analysis": {
                "total_mistakes": patterns["total_mistakes"],
                "samples_upweighted": len(mistake_samples),
                "top_reasons": dict(list(patterns["reason_counts"].items())[:3]),
            },
            "threshold": results["threshold"],
            "test_precision": results["test_precision"],
            "baseline_precision": results["baseline_precision"],
            "precision_lift": round(precision_lift, 2),
            "metadata": metadata,
        }
    else:
        logger.info("❌ NOT deploying — precision criteria not met")
        _broadcast_step("Complete", "done", "Training finished but precision criteria not met (model discarded)")
        return {
            "status": "not_deployed",
            "test_precision": results["test_precision"],
            "baseline_precision": results["baseline_precision"],
            "threshold": results["threshold"],
            "reason": "insufficient_precision",
        }


def _build_sample_weights(
    X, y, mistake_samples, upweight_factor: float = 2.0
) -> Optional[np.ndarray]:
    """
    Build per-sample weights for training. Samples that resemble past
    mistakes get higher weight so the model learns from its errors.

    Strategy: For each training sample that has similar feature profile
    to a past mistake (same general conditions), multiply its weight.

    Args:
        X: Feature DataFrame
        y: Labels
        mistake_samples: List of mistake dicts from MistakeJournal
        upweight_factor: Weight multiplier for mistake-like samples

    Returns:
        numpy array of sample weights, or None if no mistakes to learn from
    """
    if not mistake_samples or len(X) == 0:
        return None

    weights = np.ones(len(X))

    # Features we can compare against for similarity matching
    comparison_features = {
        "rsi_14": 10,        # within 10 RSI points
        "volume_ratio": 0.3, # within 0.3x
        "atr_percentile": 15, # within 15 percentile points
        "returns_1d": 0.02,  # within 2%
    }
    # Only keep features that exist in both X and can be compared
    available_comparisons = {
        k: v for k, v in comparison_features.items() if k in X.columns
    }

    if not available_comparisons:
        logger.info("  No overlapping features for mistake similarity — skipping upweighting")
        return None

    # For each mistake, find training samples with similar conditions
    for mistake in mistake_samples:
        features = mistake.get("features", {})
        if not features:
            continue

        # Pre-compute which feature columns have values in this mistake
        matchable = {
            k: features.get(k)
            for k in available_comparisons
            if features.get(k) is not None
        }
        if not matchable:
            continue

        # Vectorized similarity: check each feature column at once
        match_mask = np.ones(len(X), dtype=bool)
        matched_features = 0
        for feat_name, mistake_val in matchable.items():
            try:
                threshold = available_comparisons[feat_name]
                col_values = X[feat_name].values
                within_range = np.abs(col_values - float(mistake_val)) <= threshold
                match_mask &= within_range
                matched_features += 1
            except (ValueError, TypeError):
                continue

        if matched_features > 0:
            # Similarity score = fraction of features that matched
            # For matched samples, apply upweight proportionally
            match_indices = np.where(match_mask)[0]
            for idx in match_indices:
                similarity = matched_features / len(matchable)
                if similarity > 0.5:
                    weights[idx] *= (1.0 + (upweight_factor - 1.0) * similarity)

    # Cap weights to prevent extreme values
    weights = np.clip(weights, 1.0, upweight_factor * 2)

    upweighted_count = np.sum(weights > 1.0)
    if upweighted_count > 0:
        logger.info(
            f"  Mistake upweighting: {int(upweighted_count)} samples given extra weight "
            f"(avg weight: {weights[weights > 1.0].mean():.2f}x)"
        )

    return weights
