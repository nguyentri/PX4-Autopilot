"""Command dispatch: argument checks and the handler for each protocol command."""
from __future__ import annotations

import threading

from . import BRIDGE_VERSION, doctor, log_download, ports, px4_modes, recorder
from .protocol import COMMANDS, PROTOCOL_VERSION, BridgeError, arg, reply_error, reply_ok

# Commands answered inline on the stdin thread (fast, never wait on the vehicle).
INLINE = {"hello", "doctor", "cancel", "shell_write", "inspector_subscribe", "inspector_unsubscribe"}
LONG = {"connect", "param_list", "log_list", "log_download"}
# PX4's log handler serves one request at a time: LOG_REQUEST_LIST switches it
# from sending data to listing, which ends a running download. So a list and a
# download never overlap; every other long command excludes only itself.
LOG_COMMANDS = {"log_list", "log_download"}
EXCLUDES = {kind: LOG_COMMANDS for kind in LOG_COMMANDS}


class Handlers:
    def __init__(self, session, operations, put):
        self.session, self.operations, self._put = session, operations, put

    def submit(self, command_id: int, cmd: str, args: dict) -> None:
        if cmd in INLINE:
            self._run(command_id, cmd, args)
            return
        threading.Thread(target=self._run, args=(command_id, cmd, args), name=f"cmd-{cmd}", daemon=True).start()

    def _run(self, command_id, cmd, args) -> None:
        try:
            # Inside the try: a refused start still gets its one reply.
            cancel = self.operations.start(command_id, cmd, EXCLUDES.get(cmd)) if cmd in LONG else threading.Event()
            data = getattr(self, "cmd_" + cmd)(args, command_id, cancel)
            self._put(reply_ok(command_id, data))
        except BridgeError as error:
            self._put(reply_error(command_id, error))
        except Exception as error:  # noqa: BLE001 - every command gets exactly one reply
            self._put(reply_error(command_id, BridgeError("INTERNAL", f"{type(error).__name__}: {error}")))
        finally:
            self.operations.finish(command_id)

    # --- session --------------------------------------------------------------
    def cmd_hello(self, _args, *_):
        return {"protocolVersion": PROTOCOL_VERSION, "bridgeVersion": BRIDGE_VERSION,
                "commands": list(COMMANDS), "modes": px4_modes.table()}

    def cmd_doctor(self, _args, *_):
        return doctor.report()

    def cmd_list_ports(self, _args, *_):
        return {"ports": ports.list_ports()}

    def cmd_connect(self, args, _id, cancel):
        transport = arg(args, "transport", str, "serial")
        if transport not in ("serial", "udp"):
            raise BridgeError("BAD_ARGUMENT", "transport must be serial or udp")
        checked = {"transport": transport, "controlEnabled": arg(args, "controlEnabled", bool, True),
                   "sessionId": arg(args, "sessionId", str)}
        probe = arg(args, "probeSeconds", (int, float))
        if probe is not None:
            if not 0.2 <= probe <= 30:
                raise BridgeError("BAD_ARGUMENT", "probeSeconds must be between 0.2 and 30")
            checked["probeSeconds"] = probe
        if transport == "udp":
            checked["host"] = arg(args, "host", str, "127.0.0.1")
            checked["port"] = _port(arg(args, "port", int, 14550))
        else:
            checked["device"] = arg(args, "device", str, required=True)
            bauds = arg(args, "baudCandidates", list, [115200, 57600])
            if not bauds or len(bauds) > 8 or not all(isinstance(b, int) and not isinstance(b, bool)
                                                      and 1200 <= b <= 4_000_000 for b in bauds):
                raise BridgeError("BAD_ARGUMENT", "baudCandidates must list 1-8 baud rates")
            checked["baudCandidates"] = bauds
        return self.session.connect(checked, cancel)

    def cmd_disconnect(self, *_):
        self.operations.cancel_all()
        return self.session.disconnect()

    def cmd_cancel(self, args, *_):
        return {"cancelled": self.operations.cancel(arg(args, "target", int, required=True))}

    # --- parameters -----------------------------------------------------------
    def cmd_param_list(self, _args, command_id, cancel):
        self.session.require()
        return self.session.params.list(command_id, cancel)

    def cmd_param_read(self, args, _id, cancel):
        self.session.require()
        return self.session.params.read(arg(args, "name", str, required=True), cancel)

    def cmd_param_set(self, args, _id, cancel):
        self.session.require_control()
        return self.session.params.set(arg(args, "name", str, required=True),
                                       arg(args, "value", (int, float), required=True), cancel)

    # --- control --------------------------------------------------------------
    def cmd_arm(self, *_):
        self.session.require_control()
        return self.session.commands.arm()

    def cmd_disarm(self, *_):
        self.session.require_control()
        return self.session.commands.disarm()

    def cmd_set_mode(self, args, *_):
        self.session.require_control()
        return self.session.commands.set_mode(arg(args, "mode", str, required=True))

    def cmd_reboot(self, *_):
        self.session.require_control()
        return self.session.commands.reboot()

    # --- streams --------------------------------------------------------------
    def cmd_stream_request(self, args, _id, cancel):
        self.session.require()
        return self.session.streams.request(arg(args, "message", int, required=True),
                                            arg(args, "intervalUs", int, required=True), cancel)

    def cmd_stream_release(self, args, *_):
        self.session.require()
        return self.session.streams.release(arg(args, "message", int, required=True))

    # --- shell ------------------------------------------------------------------
    def cmd_shell_open(self, *_):
        self.session.require()
        return self.session.shell.start()

    def cmd_shell_write(self, args, *_):
        self.session.require_control()
        text = arg(args, "data", str, required=True)
        if len(text) > 4096:
            raise BridgeError("BAD_ARGUMENT", "shell input is limited to 4096 characters per command")
        return self.session.shell.write(text)

    def cmd_shell_close(self, *_):
        self.session.require()
        return self.session.shell.close()

    # --- inspector --------------------------------------------------------------
    def cmd_inspector_subscribe(self, *_):
        self.session.require()
        self.session.inspector.subscribed = True
        return {"subscribed": True}

    def cmd_inspector_unsubscribe(self, *_):
        self.session.require()
        self.session.inspector.subscribed = False
        return {"subscribed": False}

    # --- logs and recording -----------------------------------------------------
    def cmd_log_list(self, _args, _id, cancel):
        return log_download.log_list(self.session.require(), cancel)

    def cmd_log_download(self, args, command_id, cancel):
        return log_download.log_download(self.session.require(), args, cancel, self.session.emit, command_id)

    def cmd_record_start(self, args, *_):
        return recorder.record_start(self.session, args)

    def cmd_record_stop(self, args, *_):
        return recorder.record_stop(self.session, args)


def _port(value: int) -> int:
    if not 1 <= value <= 65535:
        raise BridgeError("BAD_ARGUMENT", "port must be 1-65535")
    return value
