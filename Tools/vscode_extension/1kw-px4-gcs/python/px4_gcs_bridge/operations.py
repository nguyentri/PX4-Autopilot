"""Registry of running long commands so `cancel` can find them by id."""
from __future__ import annotations

import threading

from .protocol import BridgeError


class Operations:
    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[int, tuple[str, threading.Event]] = {}

    def start(self, command_id: int, kind: str, exclusive: bool = True) -> threading.Event:
        with self._lock:
            if exclusive and any(k == kind for k, _ in self._running.values()):
                raise BridgeError("BAD_ARGUMENT", f"{kind} is already running")
            event = threading.Event()
            self._running[command_id] = (kind, event)
            return event

    def finish(self, command_id: int) -> None:
        with self._lock:
            self._running.pop(command_id, None)

    def cancel(self, target: int) -> bool:
        with self._lock:
            entry = self._running.get(target)
        if entry is None:
            return False
        entry[1].set()
        return True

    def cancel_all(self) -> None:
        with self._lock:
            entries = list(self._running.values())
        for _, event in entries:
            event.set()
