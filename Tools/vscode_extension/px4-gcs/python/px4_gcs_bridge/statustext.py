"""STATUSTEXT reassembly: chunks share an `id`; a chunk shorter than 50 bytes ends it."""
from __future__ import annotations

import time

PENDING_CAP = 16
CHUNK_TIMEOUT = 1.0
CHUNK_BYTES = 50


def _text(value) -> str:
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    return value.split("\0", 1)[0]


class StatusTextAssembler:
    def __init__(self):
        self._pending = {}  # id -> [severity, {seq: text}, started]
        self.dropped = 0

    def add(self, msg) -> list:
        text = _text(msg.text)
        raw_len = len(msg.text.encode("utf-8") if isinstance(msg.text, str) else msg.text)
        ident = getattr(msg, "id", 0)
        complete = raw_len < CHUNK_BYTES
        if not ident:
            return [{"severity": msg.severity, "text": text, "id": 0, "partial": False}]
        out = []
        entry = self._pending.get(ident)
        if entry is None:
            if len(self._pending) >= PENDING_CAP:
                self.dropped += 1
                return out
            entry = self._pending[ident] = [msg.severity, {}, time.monotonic()]
        entry[1][getattr(msg, "chunk_seq", 0)] = text
        if complete:
            del self._pending[ident]
            out.append(self._join(ident, entry, partial=False))
        return out

    def expire(self) -> list:
        now = time.monotonic()
        out = []
        for ident in [i for i, e in self._pending.items() if now - e[2] > CHUNK_TIMEOUT]:
            out.append(self._join(ident, self._pending.pop(ident), partial=True))
        return out

    @staticmethod
    def _join(ident, entry, partial):
        severity, chunks, _ = entry
        expected = range(max(chunks) + 1)
        gaps = any(seq not in chunks for seq in expected)
        return {"severity": severity, "text": "".join(chunks.get(seq, "") for seq in expected),
                "id": ident, "partial": partial or gaps}
