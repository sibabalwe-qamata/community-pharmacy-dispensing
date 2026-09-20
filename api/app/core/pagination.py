"""Keyset (cursor) pagination.

Offset pagination degrades as the offset grows and shifts rows under the reader when
new rows arrive. Every listing here has a stable, unique sort key, so the cursor is
just the last row's sort key, base64-encoded so clients treat it as opaque.
"""
import base64
import json
from typing import Any, Sequence

from .problems import UnprocessableRequest

# The response model lives in app/schemas/common.py; this module is only the mechanics.


def encode_cursor(values: dict[str, Any]) -> str:
    raw = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception as exc:  # malformed cursors are a client error, not a 500
        raise UnprocessableRequest("INVALID_CURSOR", "The cursor is not valid.") from exc


def take_page(rows: Sequence[Any], limit: int) -> tuple[list[Any], bool]:
    """Queries fetch limit+1 rows; the extra row tells us whether a next page exists."""
    return list(rows[:limit]), len(rows) > limit
