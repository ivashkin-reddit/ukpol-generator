"""Shared helpers for narrowing loosely typed decoded JSON into concrete types.

Decoded JSON (from :func:`json.loads` or ``requests`` responses) arrives as
untyped :class:`object` values. These helpers isolate the ``isinstance`` checks
and casts at the adapter boundary so the rest of the codebase never handles
untyped payloads.
"""

from __future__ import annotations

from typing import cast


def mapping_get(value: object, key: str) -> object:
    """Read a key from a value only when it is a JSON object."""
    if isinstance(value, dict):
        return cast("dict[str, object]", value).get(key)
    return None


def sequence(value: object) -> list[object]:
    """Return the value as a list only when it is a JSON array."""
    if isinstance(value, list):
        return cast("list[object]", value)
    return []


def coerce_str(value: object) -> str | None:
    """Return the value only when it is a string."""
    return value if isinstance(value, str) else None


def coerce_int(value: object) -> int | None:
    """Return the value only when it is a non-boolean integer."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None
