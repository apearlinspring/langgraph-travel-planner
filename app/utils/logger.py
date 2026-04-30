"""
Application logging setup.
"""
import sys

from loguru import logger

from app.config import settings


def _safe_console_sink(message) -> None:
    """Write logs to the current console without crashing on non-UTF-8 encodings."""
    text = str(message)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    sys.stdout.write(safe_text)


def setup_logger():
    """Configure console and file logging."""
    logger.remove()

    logger.add(
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

    logger.add(
        "logs/app.log",
        rotation="500 MB",
        retention="10 days",
        compression="zip",
        serialize=True,
        level="INFO",
    )

    logger.add(
        "logs/error.log",
        rotation="100 MB",
        retention="30 days",
        compression="zip",
        level="ERROR",
        backtrace=True,
        diagnose=True,
    )

    logger.info("Log system initialized")
    return logger


app_logger = setup_logger()
