"""COMMAND_LONG with a strict acknowledgement match; arm, disarm, set mode, reboot.

An ACK completes a command only when its `command` equals the one sent, it
comes from the pinned autopilot, and it targets this GCS or zero. Anything
else is counted. IN_PROGRESS extends the wait. Nothing is retried, and `arm`
never sends the force magic number.
"""
from __future__ import annotations

from . import px4_modes
from .mavlink_codec import GCS_COMPONENT_ID, GCS_SYSTEM_ID, require_dialect
from .protocol import BridgeError

ACK_TIMEOUT = 3.0
MAV_CMD_COMPONENT_ARM_DISARM = 400
MAV_CMD_DO_SET_MODE = 176
MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN = 246
MAV_MODE_FLAG_CUSTOM_MODE_ENABLED = 1
MAV_RESULT_ACCEPTED = 0
MAV_RESULT_IN_PROGRESS = 5


def result_name(result: int) -> str:
    enum = require_dialect().enums.get("MAV_RESULT", {})
    entry = enum.get(result)
    return entry.name if entry else f"MAV_RESULT_{result}"


class CommandSender:
    def __init__(self, link):
        self.link = link
        self.ignored_acks = 0

    def _matches(self, command):
        pin = self.link.pin

        def predicate(msg):
            if msg.get_type() != "COMMAND_ACK":
                return False
            ok = (msg.command == command and pin.is_autopilot(msg)
                  and getattr(msg, "target_system", 0) in (0, GCS_SYSTEM_ID)
                  and getattr(msg, "target_component", 0) in (0, GCS_COMPONENT_ID))
            if not ok:
                self.ignored_acks += 1
            return ok
        return predicate

    def command_long(self, command: int, params, cancel=None, timeout: float = ACK_TIMEOUT) -> dict:
        dialect = require_dialect()
        values = list(params) + [0.0] * (7 - len(params))
        box = self.link.subscribe(self._matches(command))
        try:
            self.link.send(dialect.MAVLink_command_long_message(self.link.pin.system_id, 1, command, 0, *values))
            while True:
                ack = self.link.wait_for(box, timeout, cancel)
                if ack is None:
                    if cancel is not None and cancel.is_set():
                        raise BridgeError("CANCELLED", "command cancelled")
                    raise BridgeError("TIMEOUT", f"no acknowledgement for command {command}")
                if ack.result == MAV_RESULT_IN_PROGRESS:
                    continue
                if ack.result != MAV_RESULT_ACCEPTED:
                    name = result_name(ack.result)
                    raise BridgeError("DENIED", f"vehicle answered {name}", {"result": name})
                return {"command": command, "result": result_name(ack.result)}
        finally:
            self.link.unsubscribe(box)

    def arm(self) -> dict:
        return self.command_long(MAV_CMD_COMPONENT_ARM_DISARM, [1.0, 0.0])

    def disarm(self) -> dict:
        return self.command_long(MAV_CMD_COMPONENT_ARM_DISARM, [0.0, 0.0])

    def set_mode(self, key: str) -> dict:
        pair = px4_modes.encode(key)
        if pair is None:
            raise BridgeError("BAD_ARGUMENT", f"unknown mode {key!r}")
        reply = self.command_long(MAV_CMD_DO_SET_MODE, [float(MAV_MODE_FLAG_CUSTOM_MODE_ENABLED),
                                                        float(pair[0]), float(pair[1])])
        reply["mode"] = key
        return reply

    def reboot(self) -> dict:
        return self.command_long(MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN, [1.0])
