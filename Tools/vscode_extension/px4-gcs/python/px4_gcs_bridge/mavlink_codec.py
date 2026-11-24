"""pymavlink dialect selection and a parser per traffic source.

AVAILABLE_MODES lives in the `development` dialect; fall back to `common`.
"""
from __future__ import annotations

from .protocol import BridgeError

try:
    from pymavlink.dialects.v20 import development as dialect
except ImportError:  # older pymavlink without the development dialect
    try:
        from pymavlink.dialects.v20 import common as dialect
    except ImportError:
        dialect = None

GCS_SYSTEM_ID = 255
GCS_COMPONENT_ID = 190


def require_dialect():
    if dialect is None:
        raise BridgeError("MISSING_MODULE", "pymavlink is not installed")
    return dialect


def new_parser():
    mav = require_dialect().MAVLink(None, srcSystem=GCS_SYSTEM_ID, srcComponent=GCS_COMPONENT_ID)
    mav.robust_parsing = True
    return mav


def parse(mav, data: bytes) -> list:
    """Decoded messages; bad data is dropped (counted by the caller)."""
    try:
        messages = mav.parse_buffer(data) or []
    except Exception:  # noqa: BLE001 - a malformed frame must never stop the I/O loop
        return []
    return messages
