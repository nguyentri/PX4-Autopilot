"""Onboard log server for the simulated vehicle (MAVLink log protocol).

Config `log: {size, seed, loss, chunksPerPass}` serves one log, id 1: the
ULog magic and header, then seeded pseudo-random bytes. LOG_REQUEST_DATA
replaces any running transfer (as PX4 does); LOG_REQUEST_END stops it.
`loss` drops that fraction of LOG_DATA chunks with a seeded generator, so a
lossy run is repeatable. The source SHA-256 is written to the peer log as
`{"kind": "log_source"}` for the tests to compare against.
"""
from __future__ import annotations

import hashlib
import random
import struct

from pymavlink.dialects.v20 import development as d

CHUNK = 90
LOG_ID = 1
ULOG_HEADER = b"ULog\x01\x12\x35" + b"\x01" + struct.pack("<Q", 1_731_230_000_000_000)


class LogServer:
    def __init__(self, cfg: dict, record):
        self.size = int(cfg.get("size", 400_000))
        seed = int(cfg.get("seed", 7))
        body = random.Random(seed).randbytes(max(self.size - len(ULOG_HEADER), 0))
        self.data = (ULOG_HEADER + body)[:self.size]
        self.loss = float(cfg.get("loss", 0.0))
        self.per_pass = int(cfg.get("chunksPerPass", 10))
        self.drop = random.Random(seed + 1)
        self.queue: list[int] = []  # pending offsets, sent front first
        self.sent = self.dropped = 0
        record({"kind": "log_source", "size": self.size, "sha256": hashlib.sha256(self.data).hexdigest()})

    def entries(self):
        return [d.MAVLink_log_entry_message(LOG_ID, 1, 1, 1731230000, self.size)]

    def request(self, m) -> None:
        if m.id != LOG_ID:
            self.queue = []
            return
        start = min(m.ofs - m.ofs % CHUNK, self.size)
        end = min(self.size, m.ofs + m.count)
        self.queue = list(range(start, end, CHUNK))
        self.queue.reverse()  # pop() from the end gives ascending offsets

    def end(self) -> None:
        self.queue = []

    def pump(self, peer) -> None:
        for _ in range(min(self.per_pass, len(self.queue))):
            ofs = self.queue.pop()
            if self.loss and self.drop.random() < self.loss:
                self.dropped += 1
                continue
            chunk = self.data[ofs:ofs + CHUNK]
            peer.send(d.MAVLink_log_data_message(LOG_ID, ofs, len(chunk), list(chunk) + [0] * (CHUNK - len(chunk))))
            self.sent += 1
