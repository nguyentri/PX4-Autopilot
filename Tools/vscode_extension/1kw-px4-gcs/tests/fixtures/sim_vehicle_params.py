"""PX4-like parameter protocol for the vehicle peer (test equipment).

About 40 REAL32/INT32 parameters; the list ends with `_HASH_CHECK` at index
65535. Options (peer config): `dropOnce` (indices skipped once during the list),
`silentWrite` ({name: "apply" | "reject"}: no echo, value applied or not, as PX4
does for unknown names or type mismatches), `paramRate` (values per second).
The peer option `paramSilent` ignores every parameter request (no progress at all).
"""
from __future__ import annotations

import struct
import time

from pymavlink.dialects.v20 import development as d

REAL32, INT32, UINT32 = 9, 6, 5
FORMATS = {REAL32: "<f", INT32: "<i", UINT32: "<I"}


def _initial():
    table = [("MPC_LAND_SPEED", REAL32, 0.7), ("MPC_XY_VEL_MAX", REAL32, 12.0), ("COM_RC_IN_MODE", INT32, 4),
             ("SYS_AUTOSTART", INT32, 4001), ("NEG_INT_PARAM", INT32, -1), ("NAN_BITS_INT", INT32, 0x7F800001),
             ("_INTERNAL_X", INT32, 3), ("BAT1_N_CELLS", INT32, 3), ("MAV_SYS_ID", INT32, 1), ("MAV_0_RATE", INT32, 4000),
             ("CAL_ACC0_ID", INT32, 2490378)]
    table += [(f"TEST_F{n:02d}", REAL32, n * 0.5) for n in range(15)]
    table += [(f"TEST_I{n:02d}", INT32, n * 10) for n in range(15)]
    return table


def raw_value(msg) -> bytes:
    buf = bytes(msg.get_msgbuf())
    offset = 10 if buf[:1] == b"\xfd" else 6
    return (buf[offset:offset + buf[1]][:4] + b"\0\0\0\0")[:4]


class ParamTable:
    def __init__(self, cfg):
        self.names, self.raw, self.types = [], {}, {}
        for name, kind, value in _initial():
            self.names.append(name)
            self.types[name] = kind
            self.raw[name] = struct.pack(FORMATS[kind], value)
        self.drop_once = set(cfg.get("dropOnce", []))
        self.silent = cfg.get("silentWrite", {})
        self.period = 1.0 / float(cfg.get("paramRate", 400))
        self.queue = []
        self.next_send = 0.0

    def _value_msg(self, peer, name, index):
        kind = self.types.get(name, UINT32)
        raw = self.raw.get(name, b"\x2a\0\0\0")
        msg = d.MAVLink_param_value_message(name.encode(), 0.0, kind, len(self.names), index)
        payload = raw + struct.pack("<HH16sB", len(self.names), index, name.encode(), kind)
        peer.send_payload(msg, payload)

    def pump(self, peer):
        now = time.monotonic()
        while self.queue and now >= self.next_send:
            name, index = self.queue.pop(0)
            self._value_msg(peer, name, index)
            self.next_send = now + self.period

    def handle(self, peer, m):
        kind = m.get_type()
        if kind == "PARAM_REQUEST_LIST":
            self.queue = []
            for index, name in enumerate(self.names):
                if index in self.drop_once:
                    self.drop_once.discard(index)
                    continue
                self.queue.append((name, index))
            self.queue.append(("_HASH_CHECK", 65535))
        elif kind == "PARAM_REQUEST_READ":
            name = m.param_id.split("\0", 1)[0] if m.param_index < 0 else None
            if name is None and 0 <= m.param_index < len(self.names):
                name = self.names[m.param_index]
            if name in self.raw:
                self.queue.append((name, self.names.index(name)))
        elif kind == "PARAM_SET":
            name = m.param_id.split("\0", 1)[0]
            raw = raw_value(m)
            peer.record({"kind": "param_set", "name": name, "type": m.param_type, "raw": raw.hex()})
            if name not in self.raw or m.param_type != self.types[name]:
                return  # PX4 stays silent on an unknown name or a type mismatch
            mode = self.silent.get(name)
            if mode != "reject":
                self.raw[name] = raw
            if mode is None:
                self.queue.append((name, self.names.index(name)))
