"""`.tlog` recording of the pinned vehicle's link.

A `.tlog` is a sequence of records: an 8-byte big-endian wall-clock
timestamp in microseconds, then the raw MAVLink frame. Received frames come
from the link after the vehicle pin accepted them; sent frames are recorded
as they are written. Recording starts and stops only on command; it also
stops (and the file is closed) on disconnect and on sidecar shutdown, which
both run the session teardown.
"""
from __future__ import annotations

import os
import struct
import threading
import time

from .protocol import BridgeError, arg


class Recorder:
    def __init__(self, path: str):
        self.path = path
        self._file = open(path, "xb")  # never overwrite an earlier recording
        self._lock = threading.Lock()
        self.frames = 0
        self.bytes = 0
        self.started = time.time()

    def write(self, frame) -> None:
        record = struct.pack(">Q", int(time.time() * 1e6)) + bytes(frame)
        with self._lock:
            if self._file is None:
                return
            self._file.write(record)
            self.frames += 1
            self.bytes += len(record)

    def close(self) -> dict:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None
        return {"path": self.path, "frames": self.frames, "bytes": self.bytes,
                "seconds": round(time.time() - self.started, 3)}


def record_start(session, args) -> dict:
    link = session.require()
    path = arg(args, "path", str, required=True)
    if not os.path.isabs(path) or not path.endswith(".tlog") or not os.path.isdir(os.path.dirname(path)):
        raise BridgeError("BAD_ARGUMENT", "the recording path must be an absolute .tlog path in an existing folder")
    with session.lock:
        if session.recorder is not None:
            raise BridgeError("BAD_ARGUMENT", "already recording", {"path": session.recorder.path})
        try:
            recorder = Recorder(path)
        except FileExistsError:
            raise BridgeError("BAD_ARGUMENT", "a file with that name already exists") from None
        except OSError as error:
            raise BridgeError("PERMISSION_DENIED", f"cannot create the recording: {error.strerror}") from None
        session.recorder = link.recorder = recorder
    session.emit("recording", {"state": "started", "path": path})
    return {"path": path}


def stop(session, reason: str) -> dict | None:
    """Close the running recording, if any, and announce it; returns the summary."""
    recorder, session.recorder = session.recorder, None
    if recorder is None:
        return None
    if session.link is not None:
        session.link.recorder = None
    summary = recorder.close()
    session.emit("recording", {"state": "stopped", "reason": reason, **summary})
    return summary


def record_stop(session, _args) -> dict:
    with session.lock:
        summary = stop(session, "operator")
    return {"stopped": summary is not None, **(summary or {})}
