"""The single I/O loop: read, parse, pin, dispatch; send; watchdog; GCS heartbeat."""
from __future__ import annotations

import queue
import sys
import threading
import time
import traceback

from .mavlink_codec import new_parser, parse, require_dialect

WATCHDOG_S = 3.0
GCS_HEARTBEAT_S = 1.0


class Link:
    def __init__(self, transport, pin, emit_link, on_message):
        self.transport, self.pin = transport, pin
        self._emit_link = emit_link          # callable(state) -> None
        self._on_message = on_message        # callable(msg) for accepted frames
        self._rx = new_parser()
        self._tx = new_parser()
        self._tx_lock = threading.Lock()
        self._waiters_lock = threading.Lock()
        self._waiters = []
        self._stop = threading.Event()
        self._thread = None
        self.state = "connecting"
        self.last_frame = time.monotonic()
        self.bad_frames = 0
        self.tick_hooks = []
        self.recorder = None                 # recorder.Recorder while a .tlog is being written
        self.loop_errors = 0
        self._reported_errors = set()

    # --- outgoing -----------------------------------------------------------
    def send(self, msg) -> None:
        with self._tx_lock:
            self._write(msg.pack(self._tx))
            self._tx.seq = (self._tx.seq + 1) % 256

    def send_payload(self, msg, payload: bytes) -> None:
        """Pack a message from a raw payload (keeps int32 parameter bytes exact)."""
        with self._tx_lock:
            self._write(msg._pack(self._tx, msg.crc_extra, payload))
            self._tx.seq = (self._tx.seq + 1) % 256

    def _write(self, frame: bytes) -> None:
        if not self.pin.pinned:
            return  # never transmit before a vehicle heartbeat decoded
        recorder = self.recorder
        if recorder is not None:
            recorder.write(frame)
        try:
            self.transport.write(frame, self.pin.address)
        except Exception:  # noqa: BLE001 - a write failure shows up as a lost link
            pass

    # --- waiters ------------------------------------------------------------
    def subscribe(self, predicate) -> queue.Queue:
        box = queue.Queue()
        with self._waiters_lock:
            self._waiters.append((predicate, box))
        return box

    def unsubscribe(self, box) -> None:
        with self._waiters_lock:
            self._waiters = [w for w in self._waiters if w[1] is not box]

    def wait_for(self, box, timeout, cancel=None):
        """Next message from a subscription, or None on timeout/cancel."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (cancel is not None and cancel.is_set()):
                return None
            try:
                return box.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue

    # --- probe (listen-only, before the loop starts) --------------------------
    def listen_for_pin(self, seconds: float, cancel=None) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not (cancel and cancel.is_set()):
            for data, source in self.transport.read():
                for msg in parse(self._rx, data):
                    if msg.get_type() == "BAD_DATA":
                        continue
                    if self.pin.try_pin(msg, source):
                        self.last_frame = time.monotonic()
                        return True
        return False

    def reset_parser(self) -> None:
        self._rx = new_parser()

    # --- loop -----------------------------------------------------------------
    def start(self) -> None:
        self.state = "connected"
        self._thread = threading.Thread(target=self._run, name="mavlink-io", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        dialect = require_dialect()
        heartbeat = dialect.MAVLink_heartbeat_message(dialect.MAV_TYPE_GCS, dialect.MAV_AUTOPILOT_INVALID, 0, 0,
                                                      dialect.MAV_STATE_ACTIVE, 3)
        next_heartbeat = 0.0
        while not self._stop.is_set():
            try:
                chunks = self.transport.read()
            except Exception:  # noqa: BLE001 - device gone: the watchdog reports lost
                chunks = []
                time.sleep(0.05)
            for data, source in chunks:
                for msg in parse(self._rx, data):
                    self._guarded("message handler", self._accept, msg, source)
            now = time.monotonic()
            if now >= next_heartbeat:
                self.send(heartbeat)
                next_heartbeat = now + GCS_HEARTBEAT_S
            if self.state == "connected" and now - self.last_frame > WATCHDOG_S:
                self.state = "lost"
                self._emit_link("lost")
            for hook in self.tick_hooks:
                self._guarded("tick hook", hook)

    def _guarded(self, where, fn, *args) -> None:
        """Run one handler or hook; an exception is logged, never allowed to end the loop.

        The loop also runs the watchdog and the GCS heartbeat, so if it died the
        host would keep seeing `connected` with frozen telemetry. Each distinct
        error is printed once to stderr (the host's Output channel); repeats are
        only counted.
        """
        try:
            fn(*args)
        except Exception as error:  # noqa: BLE001 - see docstring
            self.loop_errors += 1
            key = (where, type(error).__name__, str(error))
            if key not in self._reported_errors and len(self._reported_errors) < 32:
                self._reported_errors.add(key)
                print(f"px4_gcs_bridge: {where} failed (I/O loop continues):", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)

    def _accept(self, msg, source) -> None:
        if msg.get_type() == "BAD_DATA":
            self.bad_frames += 1
            return
        if not self.pin.accepts(msg, source):
            return
        self.last_frame = time.monotonic()  # any accepted frame (LOG_DATA too) keeps the watchdog quiet
        recorder = self.recorder
        if recorder is not None:
            recorder.write(msg.get_msgbuf())
        if self.state == "lost" and msg.get_type() == "HEARTBEAT" and self.pin.is_autopilot(msg):
            self.state = "connected"
            self._emit_link("connected")
        with self._waiters_lock:
            waiters = list(self._waiters)
        for predicate, box in waiters:
            try:
                if predicate(msg):
                    box.put(msg)
            except Exception:  # noqa: BLE001
                pass
        self._on_message(msg)
