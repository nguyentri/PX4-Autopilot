"""Per-message rate and last value; a 2 Hz snapshot while subscribed."""
from __future__ import annotations

import time

SNAPSHOT_S = 0.5
RATE_WINDOW_S = 2.0
MAX_FIELD_ITEMS = 32


def _fields(msg) -> dict:
    out = {}
    for name in msg.get_fieldnames()[:MAX_FIELD_ITEMS]:
        value = getattr(msg, name, None)
        if isinstance(value, (list, tuple)):
            value = list(value)[:MAX_FIELD_ITEMS]
        elif isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8", "replace")
        out[name] = value
    return out


class Inspector:
    def __init__(self, emit):
        self._emit = emit
        self._stats = {}  # (name, component) -> [id, count, window_count, window_start, rate, last]
        self.subscribed = False
        self._next = 0.0
        self.unknown = 0

    def observe(self, msg) -> None:
        if msg.get_type().startswith("UNKNOWN"):
            self.unknown += 1
            return
        key = (msg.get_type(), msg.get_srcComponent())
        now = time.monotonic()
        entry = self._stats.get(key)
        if entry is None:
            entry = self._stats[key] = [msg.get_msgId(), 0, 0, now, 0.0, None]
        entry[1] += 1
        entry[2] += 1
        if now - entry[3] >= RATE_WINDOW_S:
            entry[4] = entry[2] / (now - entry[3])
            entry[2], entry[3] = 0, now
        entry[5] = msg if self.subscribed else None

    def tick(self) -> None:
        if not self.subscribed or time.monotonic() < self._next:
            return
        self._next = time.monotonic() + SNAPSHOT_S
        self._emit("inspector", {"messages": [
            {"name": name, "id": e[0], "component": comp, "count": e[1], "rateHz": round(e[4], 2),
             "last": _fields(e[5]) if e[5] is not None else None}
            for (name, comp), e in sorted(self._stats.items())], "unknown": self.unknown})
