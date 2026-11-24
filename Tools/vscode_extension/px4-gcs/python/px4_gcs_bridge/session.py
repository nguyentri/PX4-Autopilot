"""Connection lifecycle: lease, transport, listen-only probe, pin, start, release."""
from __future__ import annotations

import threading
import time
import uuid

from . import px4_modes, recorder
from .commands import CommandSender
from .inspector import Inspector
from .link import Link
from .mavlink_codec import require_dialect
from .parameters import Parameters
from .protocol import BridgeError
from .serial_lease import SerialLease
from .shell import Shell
from .streams import Streams
from .telemetry import Telemetry
from .transport import SerialTransport, UdpTransport
from .vehicle_pin import VehiclePin

PROBE_SERIAL_S = 2.0
PROBE_UDP_S = 5.0
LINK_STATUS_S = 1.0
MAV_CMD_REQUEST_MESSAGE = 512
AVAILABLE_MODES_ID = 435


class Session:
    def __init__(self, writer, emit):
        self.writer, self.emit = writer, emit
        self.lock = threading.Lock()
        self.link = self.lease = self.transport = None
        self.recorder = None
        self.control_enabled = True
        self._next_status = 0.0

    @property
    def connected(self) -> bool:
        return self.link is not None

    def require(self) -> Link:
        if self.link is None:
            raise BridgeError("NOT_CONNECTED", "no vehicle connected")
        return self.link

    def require_control(self) -> Link:
        link = self.require()
        if not self.control_enabled:
            raise BridgeError("DENIED", "control is disabled for this connection", {"result": "CONTROL_DISABLED"})
        return link

    def status(self, state: str) -> dict:
        link = self.link
        data = {"state": state}
        if self.transport is not None:
            data.update(self.transport.describe())
        if link is not None and link.pin.pinned:
            data.update({"systemId": link.pin.system_id, "componentId": 1, "autopilot": link.pin.autopilot,
                         "vehicleType": link.pin.vehicle_type, "foreignFrames": link.pin.foreign_frames,
                         "badFrames": link.bad_frames, "ignoredAcks": self.commands.ignored_acks,
                         "droppedStatusText": self.telemetry.statustext.dropped,
                         "droppedNamedValues": self.telemetry.dropped_named})
        data["droppedEvents"] = self.writer.take_dropped()
        return data

    def _emit_link(self, state: str) -> None:
        self.emit("link", self.status(state))

    def connect(self, args: dict, cancel) -> dict:
        with self.lock:
            if self.link is not None:
                raise BridgeError("BAD_ARGUMENT", "already connected; disconnect first")
            self.control_enabled = args.get("controlEnabled", True) is not False
            try:
                return self._connect(args, cancel)
            except BaseException:
                self._teardown()
                raise

    def _open(self, args):
        kind = args.get("transport", "serial")
        if kind == "udp":
            self.transport = UdpTransport(args.get("host", "127.0.0.1"), args.get("port", 14550))
            return [None], float(args.get("probeSeconds", PROBE_UDP_S))
        device = args.get("device")
        if not isinstance(device, str) or not device:
            raise BridgeError("BAD_ARGUMENT", "serial connect needs a device")
        bauds = args.get("baudCandidates") or [57600, 115200]
        session_id = args.get("sessionId") or str(uuid.uuid4())
        self.lease = SerialLease(device, session_id)
        self.lease.acquire()
        self.transport = SerialTransport(str(self.lease.canonical), bauds[0])
        return bauds, float(args.get("probeSeconds", PROBE_SERIAL_S))

    def _connect(self, args, cancel) -> dict:
        bauds, seconds = self._open(args)
        pin = VehiclePin()
        self.telemetry = Telemetry(self.emit)
        self.inspector = Inspector(self.emit)
        # The dispatcher keeps this connection's pin: `self.link` is cleared during
        # teardown while the I/O thread may still deliver a frame.
        link = Link(self.transport, pin, self._emit_link, lambda msg: self._dispatch(msg, pin))
        self.commands = CommandSender(link)
        self.emit("link", {"state": "connecting", **self.transport.describe(), "droppedEvents": 0})
        tried = []
        for baud in bauds:
            if baud is not None and self.transport.baud != baud:
                self.transport.set_baud(baud)
            link.reset_parser()
            tried.append(baud)
            if link.listen_for_pin(seconds, cancel):
                break
            if cancel.is_set():
                raise BridgeError("CANCELLED", "connect cancelled")
        else:
            raise BridgeError("NO_HEARTBEAT", "no MAVLink heartbeat from a vehicle",
                              {"baudsTried": [b for b in tried if b is not None]})
        self.shell = Shell(link, self.emit)
        self.shell.close()  # first frame after the pin: end any shell an old session left open
        self.params = Parameters(link, self.emit)
        self.streams = Streams(link, self.commands)
        link.tick_hooks = [self.telemetry.tick, self.inspector.tick, self._periodic_status]
        self.link = link
        link.start()
        self._emit_link("connected")
        threading.Thread(target=self._request_modes, name="modes", daemon=True).start()
        return self.status("connected")

    def _periodic_status(self) -> None:
        now = time.monotonic()
        if now >= self._next_status:
            self._next_status = now + LINK_STATUS_S
            if self.link is not None:
                self._emit_link(self.link.state)

    def _dispatch(self, msg, pin) -> None:
        self.inspector.observe(msg)
        if not pin.is_autopilot(msg):
            return
        kind = msg.get_type()
        if kind == "HEARTBEAT":
            self.telemetry.heartbeat(msg)
        elif kind == "SERIAL_CONTROL":
            self.shell.handle(msg)
        else:
            self.telemetry.handle(msg)

    def _request_modes(self) -> None:
        link = self.link
        if link is None or not hasattr(require_dialect(), "MAVLink_available_modes_message"):
            return
        box = link.subscribe(lambda m: m.get_type() == "AVAILABLE_MODES" and link.pin.is_autopilot(m))
        found, total = {}, None
        try:
            self.commands.command_long(MAV_CMD_REQUEST_MESSAGE, [float(AVAILABLE_MODES_ID), 0.0])
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and (total is None or len(found) < total):
                msg = link.wait_for(box, 0.2)
                if msg is not None:
                    total, found[msg.mode_index] = msg.number_modes, msg.custom_mode
        except BridgeError:
            pass
        finally:
            link.unsubscribe(box)
        if found and self.link is link:
            self.emit("modes", {"reported": True, "available": px4_modes.availability(found.values())})

    def disconnect(self) -> dict:
        with self.lock:
            was = self.link is not None
            if was and self.link.state == "connected":
                self.streams.release_all()
            self._teardown()
            if was:
                self.emit("link", {"state": "disconnected", "droppedEvents": self.writer.take_dropped()})
            return {"disconnected": was}

    def _teardown(self) -> None:
        recorder.stop(self, "disconnect")
        link, self.link = self.link, None
        if link is not None:
            try:
                self.shell.close()
            except Exception:  # noqa: BLE001
                pass
            link.stop()
        if self.transport is not None:
            self.transport.close()
            self.transport = None
        if self.lease is not None:
            self.lease.release()
            self.lease = None
