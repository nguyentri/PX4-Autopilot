"""JSON-lines framing, reply and event builders, error codes."""
from __future__ import annotations

import json
import math
import time

PROTOCOL_VERSION = 1

ERROR_CODES = (
    "PORT_BUSY", "PORT_NOT_FOUND", "PERMISSION_DENIED", "NO_HEARTBEAT", "NOT_CONNECTED",
    "TIMEOUT", "CANCELLED", "DENIED", "BAD_ARGUMENT", "MISSING_MODULE", "NOT_IMPLEMENTED",
    "INTERNAL",
)

COMMANDS = (
    "hello", "doctor", "list_ports", "connect", "disconnect", "cancel",
    "param_list", "param_read", "param_set",
    "arm", "disarm", "set_mode", "reboot",
    "stream_request", "stream_release",
    "shell_open", "shell_write", "shell_close",
    "inspector_subscribe", "inspector_unsubscribe",
    "log_list", "log_download", "record_start", "record_stop",
)

MAX_LINE = 1 << 20


class BridgeError(Exception):
    """An error that becomes an `ok: false` reply."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        assert code in ERROR_CODES, code
        self.code = code
        self.message = message
        self.details = details


def sanitize(value):
    """Make a value JSON-safe: non-finite floats become null, bytes become text."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def encode(message: dict) -> str:
    return json.dumps(sanitize(message), separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def reply_ok(command_id, data: dict | None = None) -> dict:
    return {"type": "reply", "id": command_id, "ok": True, "data": data or {}}


def reply_error(command_id, error: BridgeError) -> dict:
    body = {"code": error.code, "message": error.message}
    if error.details is not None:
        body["details"] = error.details
    return {"type": "reply", "id": command_id, "ok": False, "error": body}


def event(name: str, data: dict) -> dict:
    return {"type": "event", "name": name, "ts": round(time.time(), 3), "data": data}


def parse_command(line: str):
    """Returns (id, cmd, args); raises BridgeError with the id when it is known."""
    if len(line) > MAX_LINE:
        raise BridgeError("BAD_ARGUMENT", "command line too long")
    try:
        obj = json.loads(line)
    except ValueError as error:
        raise BridgeError("BAD_ARGUMENT", f"invalid JSON: {error}") from None
    if not isinstance(obj, dict) or not isinstance(obj.get("id"), int) or isinstance(obj.get("id"), bool):
        raise BridgeError("BAD_ARGUMENT", "a command needs an integer id")
    cmd, args = obj.get("cmd"), obj.get("args", {})
    if cmd not in COMMANDS:
        raise BridgeError("BAD_ARGUMENT", f"unknown command {cmd!r}", {"id": obj["id"]})
    if not isinstance(args, dict):
        raise BridgeError("BAD_ARGUMENT", "args must be an object", {"id": obj["id"]})
    return obj["id"], cmd, args


def arg(args: dict, name: str, kind, default=None, required=False):
    """Typed argument reader; bool is never accepted as a number."""
    if name not in args or args[name] is None:
        if required:
            raise BridgeError("BAD_ARGUMENT", f"missing argument {name!r}")
        return default
    value = args[name]
    ok = isinstance(value, kind) and not (kind in (int, float, (int, float)) and isinstance(value, bool))
    if not ok:
        raise BridgeError("BAD_ARGUMENT", f"argument {name!r} has the wrong type")
    return value
