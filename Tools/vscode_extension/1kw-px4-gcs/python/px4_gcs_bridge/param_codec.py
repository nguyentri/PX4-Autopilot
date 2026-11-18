"""Parameter value bytes: PX4 sends integers as the raw bytes of the float field.

Decoding reads the four payload bytes straight from the frame so integer bit
patterns that look like NaN (e.g. 0x7F800001) survive; encoding packs the raw
bytes into the PARAM_SET payload without a float round trip.
"""
from __future__ import annotations

import math
import struct

from .protocol import BridgeError

# MAV_PARAM_TYPE -> (struct format, name)
TYPES = {1: ("<B", "UINT8"), 2: ("<b", "INT8"), 3: ("<H", "UINT16"), 4: ("<h", "INT16"),
         5: ("<I", "UINT32"), 6: ("<i", "INT32"), 9: ("<f", "REAL32")}
REAL32 = 9


def raw_value_bytes(msg) -> bytes:
    """The first four payload bytes of a PARAM_VALUE frame (zero-padded)."""
    buf = bytes(msg.get_msgbuf())
    offset = 10 if buf[:1] == b"\xfd" else 6
    length = buf[1] if len(buf) > 1 else 0
    payload = buf[offset:offset + length]
    return (payload[:4] + b"\0\0\0\0")[:4]


def decode(raw: bytes, param_type: int):
    fmt = TYPES.get(param_type, ("<f", None))[0]
    size = struct.calcsize(fmt)
    value = struct.unpack(fmt, raw[:size])[0]
    if fmt == "<f" and not math.isfinite(value):
        return None
    return value


def encode(value, param_type: int) -> bytes:
    """Raw four bytes for the PARAM_SET value field; validates range and type."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError("BAD_ARGUMENT", "parameter value must be a number")
    if param_type not in TYPES:
        raise BridgeError("BAD_ARGUMENT", f"unsupported parameter type {param_type}")
    fmt = TYPES[param_type][0]
    if param_type == REAL32:
        if not math.isfinite(value):
            raise BridgeError("BAD_ARGUMENT", "parameter value must be finite")
        return struct.pack("<f", float(value))
    if isinstance(value, float):
        if not value.is_integer():
            raise BridgeError("BAD_ARGUMENT", f"{TYPES[param_type][1]} parameter needs an integer")
        value = int(value)
    try:
        packed = struct.pack(fmt, value)
    except struct.error:
        raise BridgeError("BAD_ARGUMENT", f"value out of range for {TYPES[param_type][1]}") from None
    return (packed + b"\0\0\0\0")[:4]


def type_name(param_type: int) -> str:
    return TYPES.get(param_type, (None, f"TYPE_{param_type}"))[1]


def param_name(msg) -> str:
    name = msg.param_id
    if isinstance(name, (bytes, bytearray)):
        name = bytes(name).decode("ascii", "replace")
    return name.split("\0", 1)[0]
