"""
Application logging setup.
"""
import os
import sys
import logging

from loguru import logger

from app.config import settings
from app.utils.security import redact_sensitive_text


def _is_test_runtime() -> bool:
    return settings.runtime_environment == "test" or "PYTEST_CURRENT_TEST" in os.environ


def _configure_langsmith_noise_policy() -> None:
    """Keep optional LangSmith upload failures from flooding unit-test output."""

    if not _is_test_runtime():
        return
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
    for logger_name in ("langsmith", "langchain.callbacks.tracers.langchain"):
        logging.getLogger(logger_name).setLevel(logging.CRITICAL)


def _redact_log_record(record: dict) -> None:
    record["message"] = redact_sensitive_text(str(record["message"]))


def _safe_console_sink(message) -> None:
    """Write logs to the current console without crashing on non-UTF-8 encodings."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(safe_text)


def setup_logger():
    """Configure console and file logging."""
    logger.remove()
    _configure_langsmith_noise_policy()
    safe_logger = logger.patch(_redact_log_record)
    suppress_console = os.getenv("ZHIXING_SUPPRESS_CONSOLE_LOGS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    if not suppress_console:
        safe_logger.add(
            _safe_console_sink,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            level="DEBUG" if settings.debug else "INFO",
        )

    safe_logger.add(
        "logs/app.log",
        rotation="500 MB",
        retention="10 days",
        compression="zip",
        serialize=True,
        level="INFO",
    )

    safe_logger.add(
        "logs/error.log",
        rotation="100 MB",
        retention="30 days",
        compression="zip",
        level="ERROR",
        backtrace=True,
        diagnose=False,
    )

    if not suppress_console:
        safe_logger.info("Log system initialized")
    return safe_logger


app_logger = setup_logger()
