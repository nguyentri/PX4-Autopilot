"""Stream request and release with exact restoration.

`stream_request` first reads the current interval (GET_MESSAGE_INTERVAL ->
MESSAGE_INTERVAL), stores it, then sets the new one. `stream_release` restores
exactly the stored value, so only a positive current interval can be saved.
PX4 reports 0 when the stream is not configured and a negative value when it
runs unlimited; sending either back (0 = default rate, negative = stop) would
not restore it, so the request is refused and the stream left alone. A SET
interval of 0 is never sent.
"""
from __future__ import annotations

import threading

from .protocol import BridgeError

MAV_CMD_SET_MESSAGE_INTERVAL = 511
MAV_CMD_GET_MESSAGE_INTERVAL = 510
INTERVAL_TIMEOUT = 2.0
MAX_INTERVAL_US = 10_000_000

ALLOWED = {
    30: "ATTITUDE", 31: "ATTITUDE_QUATERNION", 32: "LOCAL_POSITION_NED", 33: "GLOBAL_POSITION_INT",
    24: "GPS_RAW_INT", 141: "ALTITUDE", 242: "HOME_POSITION",
    1: "SYS_STATUS", 74: "VFR_HUD", 147: "BATTERY_STATUS", 230: "ESTIMATOR_STATUS", 245: "EXTENDED_SYS_STATE",
    105: "HIGHRES_IMU", 26: "SCALED_IMU", 27: "RAW_IMU", 116: "SCALED_IMU2", 29: "SCALED_PRESSURE",
    132: "DISTANCE_SENSOR", 241: "VIBRATION",
    36: "SERVO_OUTPUT_RAW", 65: "RC_CHANNELS", 375: "ACTUATOR_OUTPUT_STATUS",
    251: "NAMED_VALUE_FLOAT", 250: "DEBUG_VECT",
}


class Streams:
    def __init__(self, link, commands):
        self.link, self.commands = link, commands
        self._lock = threading.Lock()
        self.saved = {}  # message id -> original interval in us

    def _current_interval(self, message_id: int, cancel=None) -> int:
        box = self.link.subscribe(lambda m: m.get_type() == "MESSAGE_INTERVAL" and m.message_id == message_id
                                  and self.link.pin.is_autopilot(m))
        try:
            try:
                self.commands.command_long(MAV_CMD_GET_MESSAGE_INTERVAL, [float(message_id)], cancel)
            except BridgeError as error:
                if error.code != "TIMEOUT":
                    raise
            answer = self.link.wait_for(box, INTERVAL_TIMEOUT, cancel)
        finally:
            self.link.unsubscribe(box)
        if answer is None:
            raise BridgeError("TIMEOUT", "the vehicle did not report the current interval")
        return answer.interval_us

    def request(self, message_id: int, interval_us: int, cancel=None) -> dict:
        if message_id not in ALLOWED:
            raise BridgeError("BAD_ARGUMENT", f"message {message_id} is not on the stream allow-list")
        if not 0 < interval_us <= MAX_INTERVAL_US:
            raise BridgeError("BAD_ARGUMENT", "intervalUs must be between 1 and 10000000")
        with self._lock:
            original = self.saved.get(message_id)
            if original is None:
                current = self._current_interval(message_id, cancel)
                if current <= 0:
                    raise BridgeError("DENIED", f"{ALLOWED[message_id]} has no current stream; left alone",
                                      {"current": current})
                original = current
            self.commands.command_long(MAV_CMD_SET_MESSAGE_INTERVAL, [float(message_id), float(interval_us)], cancel)
            self.saved[message_id] = original
        return {"message": message_id, "name": ALLOWED[message_id], "intervalUs": interval_us,
                "originalUs": original}

    def release(self, message_id: int, timeout: float | None = None) -> dict:
        with self._lock:
            if message_id not in self.saved:
                raise BridgeError("BAD_ARGUMENT", f"message {message_id} was not requested")
            original = self.saved[message_id]
            kwargs = {} if timeout is None else {"timeout": timeout}
            self.commands.command_long(MAV_CMD_SET_MESSAGE_INTERVAL, [float(message_id), float(original)], **kwargs)
            del self.saved[message_id]
        return {"message": message_id, "restoredUs": original}

    def release_all(self, timeout: float = 0.5) -> list:
        failed = []
        for message_id in list(self.saved):
            try:
                self.release(message_id, timeout)
            except BridgeError:
                failed.append(message_id)
                self.saved.pop(message_id, None)
        return failed
