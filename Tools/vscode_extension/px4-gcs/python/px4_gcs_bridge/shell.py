"""MAVLink NSH shell over SERIAL_CONTROL (device 10, 70-byte frames).

PX4 pushes shell output by itself; a frame with flags 0 closes the shell. The
sidecar closes it on every connect (before other traffic) and disconnect.
"""
from __future__ import annotations

import codecs

from .mavlink_codec import require_dialect

SERIAL_CONTROL_DEV_SHELL = 10
FLAG_REPLY, FLAG_RESPOND, FLAG_EXCLUSIVE = 1, 2, 4
CHUNK = 70


class Shell:
    def __init__(self, link, emit):
        self.link, self._emit = link, emit
        self.open = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _frame(self, flags: int, data: bytes):
        dialect = require_dialect()
        padded = list(data) + [0] * (CHUNK - len(data))
        return dialect.MAVLink_serial_control_message(SERIAL_CONTROL_DEV_SHELL, flags, 0, 0, len(data), padded)

    def start(self) -> dict:
        self.open = True
        self._decoder.reset()
        self.write("\n")
        return {"open": True}

    def write(self, text: str) -> dict:
        data = text.encode("utf-8")
        flags = FLAG_EXCLUSIVE | FLAG_RESPOND
        for offset in range(0, len(data), CHUNK):
            self.link.send(self._frame(flags, data[offset:offset + CHUNK]))
        if not data:
            self.link.send(self._frame(flags, b""))
        return {"bytes": len(data)}

    def close(self) -> dict:
        self.link.send(self._frame(0, b""))
        self.open = False
        return {"open": False}

    def handle(self, msg) -> None:
        if msg.device != SERIAL_CONTROL_DEV_SHELL or msg.count == 0 or not (msg.flags & FLAG_REPLY):
            return
        text = self._decoder.decode(bytes(msg.data[:min(msg.count, CHUNK)]))
        if text:
            self._emit("shell_data", {"text": text})
