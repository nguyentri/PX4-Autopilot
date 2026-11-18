"""Vehicle pin: the first autopilot heartbeat fixes the system (and UDP source).

Frames from another system, or from another address on UDP, are dropped and
counted. Other components of the pinned system pass (PX4 camera, gimbal ...).
"""
from __future__ import annotations

MAV_AUTOPILOT_INVALID = 8
MAV_TYPE_GCS = 6
AUTOPILOT_COMPONENT = 1


class VehiclePin:
    def __init__(self):
        self.system_id = None
        self.address = None
        self.autopilot = None
        self.vehicle_type = None
        self.foreign_frames = 0

    @property
    def pinned(self) -> bool:
        return self.system_id is not None

    def try_pin(self, msg, source) -> bool:
        """Pin on an autopilot heartbeat; returns True when this frame pinned."""
        if self.pinned or msg.get_type() != "HEARTBEAT":
            return False
        if msg.get_srcComponent() != AUTOPILOT_COMPONENT:
            return False
        if msg.autopilot == MAV_AUTOPILOT_INVALID or msg.type == MAV_TYPE_GCS:
            return False
        self.system_id = msg.get_srcSystem()
        self.address = source
        self.autopilot, self.vehicle_type = msg.autopilot, msg.type
        return True

    def accepts(self, msg, source) -> bool:
        if not self.pinned:
            return False
        if msg.get_srcSystem() != self.system_id or (self.address is not None and source != self.address):
            self.foreign_frames += 1
            return False
        return True

    def is_autopilot(self, msg) -> bool:
        return msg.get_srcSystem() == self.system_id and msg.get_srcComponent() == AUTOPILOT_COMPONENT
