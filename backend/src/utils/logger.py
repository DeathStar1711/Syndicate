"""
Centralized logging with rotating file handler and console output.
"""
import os
import logging
from logging.handlers import RotatingFileHandler
import yaml


def setup_logger(name: str = "stock_ai", config_path: str = None) -> logging.Logger:
    """
    Set up and return a configured logger instance.
    
    Args:
        name: Logger name
        config_path: Path to config.yaml (optional, uses defaults if not provided)
    
    Returns:
        Configured Logger instance
    """
    # Defaults
    log_level = "INFO"
    log_dir = "data/logs"
    max_file_size_mb = 10
    backup_count = 5

    # Load from config if available
    if config_path and os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
        log_cfg = config.get("logging", {})
        log_level = log_cfg.get("level", log_level)
        log_dir = log_cfg.get("log_dir", log_dir)
        max_file_size_mb = log_cfg.get("max_file_size_mb", max_file_size_mb)
        backup_count = log_cfg.get("backup_count", backup_count)

    # Create log directory
    os.makedirs(log_dir, exist_ok=True)

    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    # Format
    formatter = logging.Formatter(
        "%(asctime)s | %(name)s | %(levelname)-8s | %(module)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (rotating)
    log_file = os.path.join(log_dir, f"{name}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_file_size_mb * 1024 * 1024,
        backupCount=backup_count
    )
    file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str = "stock_ai") -> logging.Logger:
    """Get an existing logger or create a new one with defaults."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
