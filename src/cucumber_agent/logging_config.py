"""Logging system for CucumberAgent."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".cucumber" / "logs"
DEFAULT_LOG_FILE = DEFAULT_LOG_DIR / "cucumber.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_BACKUP_COUNT = 3


def setup_logging(
    log_dir: Path | None = None,
    level: int = logging.INFO,
    verbose: bool = False,
) -> logging.Logger:
    """
    Setup logging with file rotation and console output.

    Args:
        log_dir: Directory for log files (default: ~/.cucumber/logs)
        level: Logging level (default: INFO)
        verbose: If True, set level to DEBUG and enable verbose console output

    Returns:
        The configured logger instance
    """
    if verbose:
        level = logging.DEBUG

    log_dir = log_dir or DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cucumber_agent")
    logger.setLevel(level)
    logger.handlers.clear()  # Remove any existing handlers

    # File handler with rotation
    log_file = log_dir / "cucumber.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=DEFAULT_MAX_BYTES,
        backupCount=DEFAULT_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Also log uncaught exceptions to file
    def handle_exception(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = handle_exception

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance for a specific module."""
    if name:
        return logging.getLogger(f"cucumber_agent.{name}")
    return logging.getLogger("cucumber_agent")


class LoggerMixin:
    """Mixin class to add logging capability to any class."""

    @property
    def logger(self) -> logging.Logger:
        """Get a logger for this class."""
        name = f"{self.__class__.__module__}.{self.__class__.__name__}"
        return logging.getLogger(name)


# Convenience functions for common logging scenarios
def log_error(error: Exception, context: str = "") -> None:
    """Log an error with optional context."""
    logger = get_logger()
    msg = f"ERROR: {error}"
    if context:
        msg = f"{context} → {msg}"
    logger.error(msg)

    # Also write to stderr for immediate visibility
    print(f"[ERROR] {msg}", file=sys.stderr)


def log_skill_execution(
    skill_name: str, args: str, success: bool, error: str | None = None
) -> None:
    """Log skill execution for debugging."""
    logger = get_logger("skills")
    status = "OK" if success else "FAILED"
    msg = f"SKILL: {skill_name} | args: '{args}' | {status}"
    if error:
        msg = f"{msg} | error: {error}"
    logger.info(msg)


def log_tool_execution(tool_name: str, args: dict, success: bool, error: str | None = None) -> None:
    """Log tool execution for debugging."""
    logger = get_logger("tools")
    status = "OK" if success else "FAILED"
    # Truncate long args for log
    args_str = str(args)[:200]
    msg = f"TOOL: {tool_name} | {args_str} | {status}"
    if error:
        msg = f"{msg} | error: {error}"
    logger.info(msg)


def log_provider_call(
    provider: str, model: str, tokens_used: int | None = None, error: str | None = None
) -> None:
    """Log provider API call."""
    logger = get_logger("provider")
    msg = f"PROVIDER: {provider}/{model}"
    if tokens_used is not None:
        msg = f"{msg} | tokens: {tokens_used}"
    if error:
        msg = f"{msg} | ERROR: {error}"
        logger.error(msg)
    else:
        logger.debug(msg)
