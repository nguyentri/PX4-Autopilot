"""MAVLink message to protocol event mapping with 20 Hz coalescing per key."""
from __future__ import annotations

import time

from . import px4_modes
from .statustext import StatusTextAssembler

MIN_PERIOD = 1.0 / 20
NAMED_VALUE_CAP = 64
G = 9.80665
MAV_MODE_FLAG_SAFETY_ARMED = 0x80


def _nan_none(value, scale=1.0, invalid=None):
    if value is None or (invalid is not None and value == invalid):
        return None
    return value * scale


class Telemetry:
    def __init__(self, emit):
        self._emit = emit
        self._last = {}
        self._pending = {}
        self._named_keys = set()
        self.dropped_named = 0
        self.statustext = StatusTextAssembler()
        self.armed = False
        self.mode = None

    def _post(self, key, name, data):
        now = time.monotonic()
        if now - self._last.get(key, 0.0) >= MIN_PERIOD:
            self._last[key] = now
            self._pending.pop(key, None)
            self._emit(name, data)
        else:
            self._pending[key] = (name, data)

    def tick(self) -> None:
        now = time.monotonic()
        for key in [k for k in self._pending if now - self._last.get(k, 0.0) >= MIN_PERIOD]:
            name, data = self._pending.pop(key)
            self._last[key] = now
            self._emit(name, data)
        for text in self.statustext.expire():
            self._emit("statustext", text)

    def heartbeat(self, msg) -> None:
        """Only autopilot (component 1) heartbeats of the pinned vehicle reach here."""
        self.armed = bool(msg.base_mode & MAV_MODE_FLAG_SAFETY_ARMED)
        self.mode = px4_modes.decode(msg.custom_mode)
        self._emit("heartbeat", {"armed": self.armed, "mode": self.mode["name"], "modeKey": self.mode["key"],
                                 "mainMode": self.mode["main"], "subMode": self.mode["sub"],
                                 "customMode": msg.custom_mode, "baseMode": msg.base_mode,
                                 "systemStatus": msg.system_status, "vehicleType": msg.type})

    def handle(self, msg) -> None:
        handler = getattr(self, "_on_" + msg.get_type(), None)
        if handler:
            handler(msg)

    def _on_ATTITUDE(self, m):
        self._post("attitude", "attitude", {"roll": m.roll, "pitch": m.pitch, "yaw": m.yaw,
                   "rollSpeed": m.rollspeed, "pitchSpeed": m.pitchspeed, "yawSpeed": m.yawspeed})

    def _on_GLOBAL_POSITION_INT(self, m):
        self._post("position", "position", {"lat": m.lat / 1e7, "lon": m.lon / 1e7, "alt": m.alt / 1000,
                   "relativeAlt": m.relative_alt / 1000, "vx": m.vx / 100, "vy": m.vy / 100, "vz": m.vz / 100,
                   "heading": None if m.hdg == 65535 else m.hdg / 100})

    def _on_LOCAL_POSITION_NED(self, m):
        self._post("local_position", "local_position",
                   {"x": m.x, "y": m.y, "z": m.z, "vx": m.vx, "vy": m.vy, "vz": m.vz})

    def _on_GPS_RAW_INT(self, m):
        self._post("gps", "gps", {"fixType": m.fix_type, "satellites": None if m.satellites_visible == 255
                   else m.satellites_visible, "lat": m.lat / 1e7, "lon": m.lon / 1e7, "alt": m.alt / 1000,
                   "eph": _nan_none(m.eph, 0.01, 65535), "epv": _nan_none(m.epv, 0.01, 65535)})

    def _on_SYS_STATUS(self, m):
        self._post("battery", "battery", {"voltage": _nan_none(m.voltage_battery, 0.001, 65535),
                   "current": _nan_none(m.current_battery, 0.01, -1),
                   "remaining": None if m.battery_remaining < 0 else m.battery_remaining,
                   "load": m.load / 10, "sensorsPresent": m.onboard_control_sensors_present,
                   "sensorsHealthy": m.onboard_control_sensors_health})

    def _on_VFR_HUD(self, m):
        self._post("vfr", "vfr", {"airspeed": m.airspeed, "groundspeed": m.groundspeed, "heading": m.heading,
                   "throttle": m.throttle, "alt": m.alt, "climb": m.climb})

    def _on_STATUSTEXT(self, m):
        for text in self.statustext.add(m):
            self._emit("statustext", text)

    def _imu(self, source, accel, gyro, mag, temperature=None, raw=False):
        self._post("sensors:imu", "sensors", {"kind": "imu", "source": source, "accel": accel, "gyro": gyro,
                   "mag": mag, "temperature": temperature, "raw": raw})

    def _on_HIGHRES_IMU(self, m):
        self._imu("HIGHRES_IMU", [m.xacc, m.yacc, m.zacc], [m.xgyro, m.ygyro, m.zgyro],
                  [m.xmag, m.ymag, m.zmag], m.temperature)
        self._post("sensors:baro", "sensors", {"kind": "baro", "source": "HIGHRES_IMU",
                   "pressure": m.abs_pressure, "altitude": m.pressure_alt, "temperature": m.temperature})

    def _on_SCALED_IMU(self, m, source="SCALED_IMU"):
        a, g, s = G / 1000, 1 / 1000, 1 / 1000
        temperature = getattr(m, "temperature", 0)
        self._imu(source, [m.xacc * a, m.yacc * a, m.zacc * a], [m.xgyro * g, m.ygyro * g, m.zgyro * g],
                  [m.xmag * s, m.ymag * s, m.zmag * s], temperature / 100 if temperature else None)

    def _on_RAW_IMU(self, m):
        self._imu("RAW_IMU", [m.xacc, m.yacc, m.zacc], [m.xgyro, m.ygyro, m.zgyro],
                  [m.xmag, m.ymag, m.zmag], None, raw=True)

    def _on_SCALED_PRESSURE(self, m):
        self._post("sensors:baro", "sensors", {"kind": "baro", "source": "SCALED_PRESSURE",
                   "pressure": m.press_abs, "altitude": None, "temperature": m.temperature / 100})

    def _on_DISTANCE_SENSOR(self, m):
        self._post(f"sensors:distance:{m.id}", "sensors", {"kind": "distance", "source": "DISTANCE_SENSOR",
                   "sensorId": m.id, "current": m.current_distance / 100, "min": m.min_distance / 100,
                   "max": m.max_distance / 100, "orientation": m.orientation})

    def _on_NAMED_VALUE_FLOAT(self, m):
        name = m.name.rstrip("\0") if isinstance(m.name, str) else m.name.decode("utf-8", "replace").rstrip("\0")
        if name not in self._named_keys:
            if len(self._named_keys) >= NAMED_VALUE_CAP:
                self.dropped_named += 1
                return
            self._named_keys.add(name)
        self._post(f"named_value:{name}", "named_value", {"name": name, "value": m.value,
                   "timeBootMs": m.time_boot_ms})
