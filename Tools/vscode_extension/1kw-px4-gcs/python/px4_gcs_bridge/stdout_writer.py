"""Bounded stdout writer thread.

Replies and state events are never dropped. When the queue is full the oldest
droppable telemetry event is discarded and counted; the count is reported in the
next `link` event. A broken pipe starts shutdown through `on_broken`.
"""
from __future__ import annotations

import collections
import sys
import threading

from .protocol import encode

DROPPABLE = frozenset({"attitude", "position", "local_position", "gps", "battery", "vfr",
                       "sensors", "named_value", "inspector", "heartbeat"})


class StdoutWriter:
    def __init__(self, stream=None, limit: int = 256, on_broken=None):
        self._stream = stream or sys.stdout
        self._limit = limit
        self._queue: collections.deque = collections.deque()
        self._droppable = 0
        self._cond = threading.Condition()
        self._closed = False
        self._dropped = 0
        self._on_broken = on_broken
        self._thread = threading.Thread(target=self._run, name="stdout-writer", daemon=True)
        self._thread.start()

    def put(self, message: dict) -> None:
        drop = message.get("type") == "event" and message.get("name") in DROPPABLE
        with self._cond:
            if self._closed:
                return
            if drop and self._droppable >= self._limit:
                for index, (queued, is_droppable) in enumerate(self._queue):
                    if is_droppable:
                        del self._queue[index]
                        self._droppable -= 1
                        self._dropped += 1
                        break
            self._queue.append((message, drop))
            self._droppable += drop
            self._cond.notify()

    def take_dropped(self) -> int:
        with self._cond:
            count, self._dropped = self._dropped, 0
            return count

    def close(self, timeout: float = 1.0) -> None:
        """Flush what is queued (bounded by `timeout`), then stop."""
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._closed:
                    self._cond.wait()
                if not self._queue:
                    return
                message, is_droppable = self._queue.popleft()
                self._droppable -= is_droppable
            try:
                self._stream.write(encode(message) + "\n")
                self._stream.flush()
            except (BrokenPipeError, OSError, ValueError):
                with self._cond:
                    self._closed = True
                    self._queue.clear()
                if self._on_broken:
                    self._on_broken()
                return
