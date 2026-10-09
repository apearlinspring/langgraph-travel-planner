"""Small runtime resilience helpers shared by startup and scripts."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar


T = TypeVar("T")


class RuntimeDependencyTimeout(TimeoutError):
    """Raised when a runtime dependency probe exceeds its startup budget."""

    def __init__(self, label: str, timeout_seconds: float) -> None:
        self.label = label
        self.timeout_seconds = timeout_seconds
        super().__init__(f"{label} exceeded {timeout_seconds:.1f}s startup timeout")


@dataclass(frozen=True)
class RuntimeStepResult:
    """Redacted, serializable result for one bounded runtime step."""

    status: str
    elapsed_seconds: float
    timeout_seconds: float | None = None
    error_type: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds,
            "timeout_seconds": self.timeout_seconds,
            "error_type": self.error_type,
            "error": self.error,
        }


def format_runtime_error(error: BaseException) -> str:
    message = str(error).strip()
    return message or error.__class__.__name__


async def run_with_timeout(
    label: str,
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float | None,
) -> T:
    """Run an async operation with an optional timeout and a clearer error."""

    if timeout_seconds is None or timeout_seconds <= 0:
        return await operation()
    try:
        return await asyncio.wait_for(operation(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise RuntimeDependencyTimeout(label, timeout_seconds) from exc


async def capture_runtime_step(
    label: str,
    operation: Callable[[], Awaitable[T]],
    *,
    timeout_seconds: float | None,
) -> tuple[T | None, RuntimeStepResult]:
    """Capture success/failure metadata for a runtime operation."""

    started_at = time.perf_counter()
    try:
        result = await run_with_timeout(
            label,
            operation,
            timeout_seconds=timeout_seconds,
        )
    except RuntimeDependencyTimeout as exc:
        return None, RuntimeStepResult(
            status="timeout",
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
            timeout_seconds=timeout_seconds,
            error_type=exc.__class__.__name__,
            error=format_runtime_error(exc),
        )
    except Exception as exc:
        return None, RuntimeStepResult(
            status="failed",
            elapsed_seconds=round(time.perf_counter() - started_at, 3),
            timeout_seconds=timeout_seconds,
            error_type=exc.__class__.__name__,
            error=format_runtime_error(exc),
        )

    return result, RuntimeStepResult(
        status="ready",
        elapsed_seconds=round(time.perf_counter() - started_at, 3),
        timeout_seconds=timeout_seconds,
    )
