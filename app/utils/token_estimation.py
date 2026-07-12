"""Provider-independent token estimation shared by runtime telemetry."""
from __future__ import annotations

import math


def estimate_token_count(text: str) -> int:
    """Estimate token usage with a stable character-based approximation."""

    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4) + math.ceil(non_ascii_chars / 2))
