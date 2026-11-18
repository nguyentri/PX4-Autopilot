"""Onboard logs: list (LOG_REQUEST_LIST / LOG_ENTRY) and download (LOG_REQUEST_DATA / LOG_DATA).

PX4 sends nothing when it has no logs, so `answered` is false when no
LOG_ENTRY came within the wait while the link stayed up.

PX4 serves one LOG_REQUEST_DATA at a time and a new request replaces the
running one, so the download asks for the whole file once and then for one
missing run at a time (nearby runs merged). Chunks are written into a
`<path>.part` file at their offset; the file is renamed to `path` only when
every chunk arrived. LOG_REQUEST_END is sent on success, cancel, error and
disconnect (the caller's cancel event fires on disconnect).
"""
from __future__ import annotations

import hashlib
import os
import time

from .mavlink_codec import require_dialect
from .protocol import BridgeError, arg

ENTRY_WAIT_S = 3.0
ENTRY_IDLE_S = 1.0
MAX_ENTRIES = 2000

CHUNK = 90                 # LOG_DATA payload bytes
RUN_IDLE_S = 0.4           # no LOG_DATA for this long: the active request is over (its tail was lost)
MERGE_CHUNKS = 8           # missing runs closer than this are asked for as one range
MAX_FRUITLESS = 25         # consecutive requests that brought no new chunk: give up
PROGRESS_S = 0.25


def log_list(link, cancel) -> dict:
    d = require_dialect()
    box = link.subscribe(lambda m: m.get_type() == "LOG_ENTRY" and link.pin.is_autopilot(m))
    entries, total = {}, None
    try:
        link.send(d.MAVLink_log_request_list_message(link.pin.system_id, 1, 0, 0xFFFF))
        started = last = time.monotonic()
        while len(entries) < MAX_ENTRIES:
            if cancel.is_set():
                raise BridgeError("CANCELLED", "log list cancelled")
            msg = link.wait_for(box, 0.1, cancel)
            now = time.monotonic()
            if msg is not None:
                last, total = now, msg.num_logs
                if msg.num_logs:
                    entries[msg.id] = {"id": msg.id, "size": msg.size, "timeUtc": msg.time_utc or None}
                if total is not None and len(entries) >= total:
                    break
            elif total is None and now - started > ENTRY_WAIT_S:
                break
            elif total is not None and now - last > ENTRY_IDLE_S:
                break
    finally:
        link.unsubscribe(box)
    if total is None and link.state != "connected":
        raise BridgeError("TIMEOUT", "link lost while waiting for the log list")
    return {"entries": sorted(entries.values(), key=lambda e: e["id"]), "answered": total is not None,
            "total": total, "truncated": len(entries) >= MAX_ENTRIES}


def _checked_args(args) -> tuple[int, int, str]:
    log_id = arg(args, "id", int, required=True)
    size = arg(args, "size", int, required=True)
    path = arg(args, "path", str, required=True)
    if not 0 <= log_id <= 0xFFFF:
        raise BridgeError("BAD_ARGUMENT", "log id must be 0-65535")
    if not 0 < size < 1 << 32:
        raise BridgeError("BAD_ARGUMENT", "log size must be 1 byte to 4 GiB")
    if not os.path.isabs(path) or not os.path.isdir(os.path.dirname(path)):
        raise BridgeError("BAD_ARGUMENT", "the destination must be an absolute path in an existing folder")
    return log_id, size, path


def next_run(have: bytearray, low: int) -> tuple[int, int] | None:
    """First missing chunk run at or after `low` as [start, end), runs closer than MERGE_CHUNKS merged."""
    start = have.find(0, low)
    if start < 0:
        return None
    end = have.find(1, start)
    while end >= 0:
        following = have.find(0, end)
        if following < 0 or following - end > MERGE_CHUNKS:
            break
        end = have.find(1, following)
    return start, len(have) if end < 0 else end


def log_download(link, args, cancel, emit, command_id) -> dict:
    log_id, size, path = _checked_args(args)
    d = require_dialect()
    chunks = (size + CHUNK - 1) // CHUNK
    have = bytearray(chunks)
    state = {"chunks": 0, "bytes": 0, "requests": 0}
    part = path + ".part"
    box = link.subscribe(lambda m: m.get_type() == "LOG_DATA" and m.id == log_id and link.pin.is_autopilot(m))
    started = time.monotonic()
    done = False

    def request(first: int, end: int) -> int:
        state["requests"] += 1
        ofs = first * CHUNK
        link.send(d.MAVLink_log_request_data_message(link.pin.system_id, 1, log_id, ofs, min(end * CHUNK, size) - ofs))
        return end

    def progress() -> None:
        emit("log_progress", {"id": command_id, "received": state["bytes"], "total": size})

    try:
        with open(part, "wb") as out:
            out.truncate(size)
            active_end = request(0, chunks)
            low, last_data, last_progress, fruitless, before = 0, time.monotonic(), 0.0, 0, 0
            while state["chunks"] < chunks:
                if cancel.is_set():
                    raise BridgeError("CANCELLED", "log download cancelled")
                msg = link.wait_for(box, 0.1, cancel)
                now = time.monotonic()
                run_over = False
                if msg is not None:
                    last_data = now
                    index = msg.ofs // CHUNK
                    expected = min(CHUNK, size - msg.ofs) if msg.ofs < size else 0
                    if msg.ofs % CHUNK == 0 and expected and msg.count >= expected and not have[index]:
                        out.seek(msg.ofs)
                        out.write(bytes(msg.data[:expected]))
                        have[index] = 1
                        state["chunks"] += 1
                        state["bytes"] += expected
                    run_over = index >= active_end - 1
                    if now - last_progress >= PROGRESS_S:
                        last_progress = now
                        progress()
                elif now - last_data > RUN_IDLE_S:
                    run_over = True
                if not run_over or state["chunks"] >= chunks:
                    continue
                fruitless = fruitless + 1 if state["chunks"] == before else 0
                if fruitless > MAX_FRUITLESS:
                    raise BridgeError("TIMEOUT", "the vehicle stopped sending log data",
                                      {"received": state["bytes"], "total": size})
                before = state["chunks"]
                run = next_run(have, low)
                if run is None:
                    break
                low = run[0]
                active_end = request(*run)
                last_data = now
        done = True
    finally:
        link.unsubscribe(box)
        try:
            link.send(d.MAVLink_log_request_end_message(link.pin.system_id, 1))
        except Exception:  # noqa: BLE001 - the link may already be gone
            pass
        if not done:
            try:
                os.remove(part)
            except OSError:
                pass
    os.replace(part, path)
    progress()
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    seconds = max(time.monotonic() - started, 1e-3)
    return {"id": log_id, "size": size, "path": path, "sha256": digest.hexdigest(), "seconds": round(seconds, 3),
            "rateBps": round(size / seconds), "requests": state["requests"]}
