#!/usr/bin/env python3
"""PX4-like MAVLink vehicle peer for the sidecar tests (test equipment, not shipped).

Runs over real UDP (`--udp-target HOST:PORT`) or a pseudo-terminal (`--pty`).
The first stdout line is JSON: {"ready": true, "udpPort": N} or {"pty": "/dev/pts/N"}.
Every received frame is appended to `--log` as one JSON line with its source.
SIGUSR1 toggles a mute (nothing is sent) for watchdog tests.
SIGUSR2 arms the vehicle by itself (state change while a dialog is open).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import signal
import socket
import struct
import sys
import time
import tty

from pymavlink.dialects.v20 import development as d

from sim_vehicle_log import LogServer
from sim_vehicle_params import ParamTable

PX4_AUTOPILOT, QUAD = 12, 2


class Peer:
    def __init__(self, args):
        self.args = args
        self.cfg = json.loads(args.config) if args.config else {}
        self.mav = d.MAVLink(None, srcSystem=args.sysid, srcComponent=1)
        self.rx = d.MAVLink(None)
        self.rx.robust_parsing = True
        self.log = open(args.log, "a", encoding="utf-8") if args.log else None
        self.armed = bool(self.cfg.get("armed", False))
        self.custom_mode = int(self.cfg.get("customMode", 3 << 16))  # Position by default
        self.intervals = {int(k): v for k, v in self.cfg.get("intervals", {"30": 20000, "105": 20000}).items()}
        self.params = ParamTable(self.cfg)
        self.muted = False
        self.gcs_addr = None
        self.sock = self.master = None
        self.started = time.monotonic()
        self.first_tx = None
        self.logs = LogServer(self.cfg["log"], self.record) if "log" in self.cfg else None
        signal.signal(signal.SIGUSR1, self._toggle_mute)
        signal.signal(signal.SIGUSR2, self._self_arm)

    def _toggle_mute(self, *_):
        self.muted = not self.muted
        self.record({"kind": "mute", "muted": self.muted})

    def _self_arm(self, *_):
        self.armed = True
        self.record({"kind": "self_arm"})
        self.heartbeat()

    # --- I/O ------------------------------------------------------------------
    def open(self):
        if self.args.pty:
            self.master, slave = os.openpty()
            tty.setraw(self.master)
            os.set_blocking(self.master, False)
            print(json.dumps({"pty": os.ttyname(slave)}), flush=True)
            self.slave = slave  # keep the slave open so the pty survives client reopen
        else:
            host, port = self.args.udp_target.rsplit(":", 1)
            self.gcs_addr = (host, int(port))
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("127.0.0.1", self.args.bind_port))
            self.sock.setblocking(False)
            print(json.dumps({"ready": True, "udpPort": self.sock.getsockname()[1]}), flush=True)

    def write(self, frame: bytes):
        if self.muted:
            return
        if self.first_tx is None:
            self.first_tx = time.monotonic()
            self.record({"kind": "first_tx"})
        try:
            if self.sock is not None:
                self.sock.sendto(frame, self.gcs_addr)
            else:
                os.write(self.master, frame)
        except OSError:
            pass

    def send(self, msg):
        self.write(msg.pack(self.mav))
        self.mav.seq = (self.mav.seq + 1) % 256

    def send_payload(self, msg, payload):
        self.write(msg._pack(self.mav, msg.crc_extra, payload))
        self.mav.seq = (self.mav.seq + 1) % 256

    def read(self):
        out = []
        try:
            if self.sock is not None:
                while True:
                    data, src = self.sock.recvfrom(65535)
                    out.append((data, list(src)))
            else:
                data = os.read(self.master, 4096)
                if data:
                    self.record({"kind": "rx_bytes", "n": len(data)})
                    out.append((data, "pty"))
        except (BlockingIOError, OSError):
            pass
        return out

    def record(self, entry):
        if self.log:
            entry["t"] = round(time.monotonic() - self.started, 3)
            self.log.write(json.dumps(entry) + "\n")
            self.log.flush()

    # --- vehicle behavior -----------------------------------------------------------
    def heartbeat(self):
        base = 0x80 if self.armed else 0
        self.send(d.MAVLink_heartbeat_message(QUAD, PX4_AUTOPILOT, base | 1, self.custom_mode, 4, 3))

    def telemetry(self, t):
        boot = int(t * 1000)
        self.send(d.MAVLink_attitude_message(boot, 0.1, -0.2, 1.5, 0.01, 0.02, 0.03))
        north, east, heading = 1.0, 2.0, 90.0
        circle = self.cfg.get("circle")
        if circle:
            # Fly a circle of `radius` metres every `period` seconds, heading along the tangent.
            angle = 2 * math.pi * t / circle.get("period", 20)
            radius = circle.get("radius", 50)
            north, east = radius * math.cos(angle), radius * math.sin(angle)
            heading = (math.degrees(angle) + 90) % 360
        lat = 10.5 + north / 110574.0
        lon = 106.6 + east / (111320.0 * math.cos(math.radians(10.5)))
        position = self.cfg.get("position", "both")  # both | global | none
        if position != "none":
            self.send(d.MAVLink_global_position_int_message(boot, int(lat * 1e7), int(lon * 1e7), 12000, 2000,
                                                            100, -50, 0, int(heading * 100)))
        if position == "both":
            self.send(d.MAVLink_local_position_ned_message(boot, north, east, -3.0, 0.1, 0.2, 0.0))
        self.send(d.MAVLink_gps_raw_int_message(boot * 1000, 3, 105000000, 1066000000, 12000, 80, 120, 0, 0, 12))
        self.send(d.MAVLink_sys_status_message(0, 0, 0, 250, 12100, 150, 87, 0, 0, 0, 0, 0, 0))
        self.send(d.MAVLink_vfr_hud_message(0.0, 1.0, 90, 0, 2.0, 0.0))
        if self.cfg.get("imu") == "scaled":
            self.send(d.MAVLink_scaled_imu_message(boot, 0, 0, -1000, 10, 20, 30, 200, 0, 400, 2500))
        else:
            self.send(d.MAVLink_highres_imu_message(boot * 1000, 0.0, 0.0, -9.81, 0.01, 0.02, 0.03,
                                                    0.2, 0.0, 0.4, 1013.0, 0.0, 12.0, 25.0, 0x1FFF))
        self.send(d.MAVLink_scaled_pressure_message(boot, 1013.25, 0.0, 2500))
        self.send(d.MAVLink_distance_sensor_message(boot, 10, 1200, 250, 0, 0, 25, 0))
        self.send(d.MAVLink_named_value_float_message(boot, b"ADS_A0", 1.25 + 0.1 * math.sin(t)))

    def statustext(self):
        self.send(d.MAVLink_statustext_message(6, b"Ready for takeoff", 0, 0))
        first = b"A" * 50
        self.send(d.MAVLink_statustext_message(4, first, 7, 0))
        self.send(d.MAVLink_statustext_message(4, b"BC end", 7, 1))
        for ident in range(100, 100 + self.cfg.get("statustextFlood", 0)):
            self.send(d.MAVLink_statustext_message(4, b"X" * 50, ident, 0))

    def ack(self, command, result, sysid=None, comp=1, target=255):
        msg = d.MAVLink_command_ack_message(command, result, 0, 0, target, 190)
        if sysid is None and comp == 1:
            self.send(msg)
            return
        other = d.MAVLink(None, srcSystem=sysid or self.args.sysid, srcComponent=comp)
        self.write(msg.pack(other))

    def on_command(self, m):
        cmd = m.command
        result = int(self.cfg.get("ackResults", {}).get(str(cmd), 0))
        if self.cfg.get("decoyAcks"):
            self.ack(176 if cmd != 176 else 400, 0)
            self.ack(cmd, 0, comp=2)
            self.ack(cmd, 0, target=7)
            time.sleep(0.2)
        if cmd == 510:
            self.ack(cmd, 0)
            self.send(d.MAVLink_message_interval_message(int(m.param1), self.intervals.get(int(m.param1), 0)))
            return
        if cmd == 511:
            msg_id, interval = int(m.param1), int(m.param2)
            self.record({"kind": "interval_set", "message": msg_id, "interval": interval})
            if interval < 0:
                self.intervals.pop(msg_id, None)
            elif interval == 0:
                self.intervals[msg_id] = "unlimited"
            else:
                self.intervals[msg_id] = interval
            self.ack(cmd, 0)
            return
        if cmd == 512 and int(m.param1) == 435 and self.cfg.get("availableModes"):
            self.ack(cmd, 0)
            for i, (main, sub) in enumerate([(1, 0), (3, 0), (4, 3), (4, 5), (4, 6)], start=1):
                self.send(d.MAVLink_available_modes_message(5, i, 0, (main << 16) | (sub << 24), 0, b"m"))
            return
        if cmd not in (400, 176, 246):
            self.ack(cmd, 3)  # UNSUPPORTED
            return
        self.ack(cmd, result)
        if result == 0 and cmd == 400:
            self.armed = m.param1 == 1.0
        if result == 0 and cmd == 176:
            self.custom_mode = (int(m.param2) << 16) | (int(m.param3) << 24)
        self.heartbeat()

    def on_serial_control(self, m):
        self.record({"kind": "shell", "flags": m.flags, "count": m.count})
        if m.device != 10 or m.count == 0:
            return
        text = bytes(m.data[:m.count])
        echo = text + (b"nsh> " if b"\n" in text else b"")
        for off in range(0, len(echo), 70):
            chunk = echo[off:off + 70]
            self.send(d.MAVLink_serial_control_message(10, 1, 0, 0, len(chunk), list(chunk) + [0] * (70 - len(chunk))))

    def on_log_list(self, _m):
        if self.cfg.get("logListSilent"):
            return
        if self.logs:
            for msg in self.logs.entries():
                self.send(msg)
            return
        for i in (1, 2):
            self.send(d.MAVLink_log_entry_message(i, 2, 2, 1731230000 + i, 1024 * i))

    def handle(self, m, src):
        kind = m.get_type()
        if kind == "BAD_DATA":
            return
        entry = {"kind": "rx", "type": kind, "src": src, "sysid": m.get_srcSystem(), "compid": m.get_srcComponent()}
        if kind == "COMMAND_LONG":
            entry.update(command=m.command, param1=m.param1, param2=m.param2)
        elif kind == "LOG_REQUEST_DATA":
            entry.update(id=m.id, ofs=m.ofs, count=m.count)
        self.record(entry)
        if kind == "COMMAND_LONG":
            self.on_command(m)
        elif kind == "SERIAL_CONTROL":
            self.on_serial_control(m)
        elif kind == "LOG_REQUEST_LIST":
            self.on_log_list(m)
        elif kind == "LOG_REQUEST_DATA" and self.logs:
            self.logs.request(m)
        elif kind == "LOG_REQUEST_END" and self.logs:
            self.logs.end()
        elif kind.startswith("PARAM_") and not self.cfg.get("paramSilent"):
            self.params.handle(self, m)

    def run(self):
        self.open()
        start_delay = float(self.cfg.get("startDelay", 0))
        next_hb = next_tel = next_text = time.monotonic() + start_delay
        while True:
            for data, src in self.read():
                for m in self.rx.parse_buffer(data) or []:
                    self.handle(m, src)
            now = time.monotonic()
            self.params.pump(self)
            if self.logs and not self.muted:
                self.logs.pump(self)
            if now >= next_hb:
                self.heartbeat()
                next_hb = now + float(self.cfg.get("heartbeatPeriod", 0.5))
            if now >= next_tel and not self.cfg.get("heartbeatOnly"):
                self.telemetry(now - self.started)
                next_tel = now + 0.1
            if now >= next_text and not self.cfg.get("heartbeatOnly"):
                self.statustext()
                next_text = now + 3.0
            time.sleep(0.005)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--udp-target")
    parser.add_argument("--bind-port", type=int, default=0)
    parser.add_argument("--pty", action="store_true")
    parser.add_argument("--sysid", type=int, default=1)
    parser.add_argument("--log")
    parser.add_argument("--config", help="JSON behavior options")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        Peer(args).run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
