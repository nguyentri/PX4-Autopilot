"""Entry point: `python3 -m px4_gcs_bridge` (stdio protocol) or `... doctor`.

stdin end-of-file, SIGTERM/SIGINT/SIGHUP and a broken stdout pipe each
disconnect (streams, shell, port, lease) and exit with code 0.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys

from . import doctor
from .handlers import Handlers
from .operations import Operations
from .protocol import BridgeError, encode, event, parse_command, reply_error
from .session import Session
from .stdout_writer import StdoutWriter


class _Shutdown(Exception):
    pass


def _raise_shutdown(_signum, _frame):
    raise _Shutdown()


def serve() -> int:
    for signum in (signal.SIGTERM, signal.SIGINT, getattr(signal, "SIGHUP", None)):
        if signum is not None:
            signal.signal(signum, _raise_shutdown)
    out = sys.stdout
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol stream
    writer = StdoutWriter(out, on_broken=lambda: os.kill(os.getpid(), signal.SIGTERM))
    session = Session(writer, lambda name, data: writer.put(event(name, data)))
    operations = Operations()
    handlers = Handlers(session, operations, writer.put)
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                command_id, cmd, args = parse_command(line)
            except BridgeError as error:
                known = (error.details or {}).get("id")
                writer.put(reply_error(known, BridgeError(error.code, error.message)))
                continue
            handlers.submit(command_id, cmd, args)
    except (_Shutdown, KeyboardInterrupt):
        pass
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        operations.cancel_all()
        try:
            session.disconnect()
        except Exception as error:  # noqa: BLE001 - shutdown must finish
            print(f"px4_gcs_bridge: disconnect failed: {error}", file=sys.stderr)
        writer.close(timeout=0.5)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="px4_gcs_bridge", description=__doc__)
    parser.add_argument("command", nargs="?", choices=["serve", "doctor"], default="serve")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(encode(doctor.report()))
        return 0
    return serve()


if __name__ == "__main__":
    sys.exit(main())
