"""Registry of running long commands so `cancel` can find them by id."""
from __future__ import annotations

import threading

from .protocol import BridgeError


class Operations:
    def __init__(self):
        self._lock = threading.Lock()
        self._running: dict[int, tuple[str, threading.Event]] = {}

    def start(self, command_id: int, kind: str, excludes=None) -> threading.Event:
        """Register a long command; refuse it while one of the kinds in `excludes` runs (default: its own)."""
        blocked = {kind} if excludes is None else set(excludes)
        with self._lock:
            running = next((k for k, _ in self._running.values() if k in blocked), None)
            if running is not None:
                what = f"{kind} is already running" if running == kind else f"{kind} must wait: {running} is running"
                raise BridgeError("BAD_ARGUMENT", what)
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
