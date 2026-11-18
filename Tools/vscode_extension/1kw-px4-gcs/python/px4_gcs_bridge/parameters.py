"""Parameter list (with gap retry), read by name, and set with read-back.

Hidden: names starting with `_` and index 65535 (`_HASH_CHECK`). `param_set`
refuses `_` names, sends the type the vehicle reported, and when the echo is
missing reads the value back by name: equal means applied, otherwise "not
applied" with the value the vehicle holds.
"""
from __future__ import annotations

import struct
import time

from . import param_codec
from .mavlink_codec import require_dialect
from .protocol import BridgeError

GAP_IDLE_S = 1.0
GAP_ROUNDS = 3
GAP_BATCH = 16
# Backstop only: the extension cancels a list with no progress for 5 s first.
START_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 2.0
HIDDEN_INDEX = 65535


def hidden(name: str, index: int) -> bool:
    return name.startswith("_") or index == HIDDEN_INDEX


class Parameters:
    def __init__(self, link, emit):
        self.link, self._emit = link, emit
        self.cache = {}  # name -> {"type", "raw", "index"}

    def _from_vehicle(self, msg) -> bool:
        return msg.get_type() == "PARAM_VALUE" and self.link.pin.is_autopilot(msg)

    def _record(self, msg) -> dict:
        name, raw = param_codec.param_name(msg), param_codec.raw_value_bytes(msg)
        entry = {"name": name, "index": msg.param_index, "type": param_codec.type_name(msg.param_type),
                 "typeId": msg.param_type, "value": param_codec.decode(raw, msg.param_type)}
        if not hidden(name, msg.param_index):
            self.cache[name] = {"type": msg.param_type, "raw": raw, "index": msg.param_index}
        return entry

    def _request_read(self, name: str = "", index: int = -1) -> None:
        d = require_dialect()
        self.link.send(d.MAVLink_param_request_read_message(self.link.pin.system_id, 1, name.encode("ascii"), index))

    def list(self, command_id: int, cancel) -> dict:
        d = require_dialect()
        box = self.link.subscribe(self._from_vehicle)
        params, seen, total, rounds = {}, set(), None, 0
        last_progress = 0.0
        try:
            self.link.send(d.MAVLink_param_request_list_message(self.link.pin.system_id, 1))
            last_rx = time.monotonic()
            while True:
                if cancel.is_set():
                    raise BridgeError("CANCELLED", "parameter list cancelled")
                msg = self.link.wait_for(box, 0.1, cancel)
                now = time.monotonic()
                if msg is not None:
                    last_rx = now
                    entry = self._record(msg)
                    if msg.param_index != HIDDEN_INDEX:
                        total = msg.param_count
                        seen.add(msg.param_index)
                    if not hidden(entry["name"], msg.param_index):
                        params[entry["name"]] = entry
                    if now - last_progress > 0.1:
                        last_progress = now
                        self._emit("param_progress", {"id": command_id, "received": len(seen), "total": total})
                missing = sorted(set(range(total)) - seen) if total is not None else None
                if missing == []:
                    break
                if total is None and now - last_rx > START_TIMEOUT_S:
                    raise BridgeError("TIMEOUT", "the vehicle sent no parameters")
                if missing and now - last_rx > GAP_IDLE_S:
                    if rounds >= GAP_ROUNDS:
                        break
                    rounds += 1
                    for index in missing[:GAP_BATCH]:
                        self._request_read(index=index)
                    last_rx = now
        finally:
            self.link.unsubscribe(box)
        missing = sorted(set(range(total or 0)) - seen)
        self._emit("param_progress", {"id": command_id, "received": len(seen), "total": total})
        return {"params": sorted(params.values(), key=lambda p: p["name"]), "count": total, "missing": missing}

    def read(self, name: str, cancel=None) -> dict:
        _check_name(name, allow_hidden=False)
        box = self.link.subscribe(lambda m: self._from_vehicle(m) and param_codec.param_name(m) == name)
        try:
            self._request_read(name=name)
            msg = self.link.wait_for(box, READ_TIMEOUT_S, cancel)
        finally:
            self.link.unsubscribe(box)
        if msg is None:
            if cancel is not None and cancel.is_set():
                raise BridgeError("CANCELLED", "parameter read cancelled")
            raise BridgeError("TIMEOUT", f"no value for {name}")
        return self._record(msg)

    def set(self, name: str, value, cancel=None) -> dict:
        _check_name(name, allow_hidden=False)
        if name not in self.cache:
            self.read(name, cancel)
        param_type = self.cache[name]["type"]
        raw = param_codec.encode(value, param_type)
        requested = param_codec.decode(raw, param_type)
        d = require_dialect()
        msg = d.MAVLink_param_set_message(self.link.pin.system_id, 1, name.encode("ascii"), 0.0, param_type)
        payload = raw + struct.pack("<BB16sB", self.link.pin.system_id, 1, name.encode("ascii"), param_type)
        box = self.link.subscribe(lambda m: self._from_vehicle(m) and param_codec.param_name(m) == name)
        try:
            self.link.send_payload(msg, payload)
            echo = self.link.wait_for(box, READ_TIMEOUT_S, cancel)
        finally:
            self.link.unsubscribe(box)
        entry = self._record(echo) if echo is not None else self.read(name, cancel)
        applied = self.cache[name]["raw"] == raw
        return {"name": name, "applied": applied, "value": entry["value"], "requested": requested,
                "type": entry["type"], "echoed": echo is not None}


def _check_name(name, allow_hidden: bool) -> None:
    if not isinstance(name, str) or not 0 < len(name) <= 16 or not name.isascii():
        raise BridgeError("BAD_ARGUMENT", "parameter name must be 1-16 ASCII characters")
    if name.startswith("_") and not allow_hidden:
        raise BridgeError("BAD_ARGUMENT", f"{name} is an internal parameter")
