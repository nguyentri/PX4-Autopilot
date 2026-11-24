"""Serial port enumeration, FTDI and PX4 USB devices first."""
from __future__ import annotations

import os
from pathlib import Path

from .protocol import BridgeError

PREFERRED_VIDS = {0x0403: 2, 0x26AC: 3, 0x3185: 3, 0x1209: 1}  # FTDI, 3DR/PX4, Holybro, pid.codes


def _by_id_map():
    directory = Path("/dev/serial/by-id")
    mapping = {}
    if directory.is_dir():
        for link in sorted(directory.iterdir()):
            try:
                mapping[str(link.resolve())] = str(link)
            except OSError:
                continue
    return mapping


def list_ports() -> list:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        raise BridgeError("MISSING_MODULE", "pyserial is not installed") from None
    by_id = _by_id_map()
    ports = []
    for info in lp.comports():
        real = os.path.realpath(info.device)
        rank = PREFERRED_VIDS.get(info.vid, 0) if info.vid is not None else -1
        ports.append({
            "device": info.device,
            "byId": by_id.get(real),
            "vid": info.vid, "pid": info.pid,
            "description": info.description if info.description and info.description != "n/a" else None,
            "manufacturer": info.manufacturer,
            "serialNumber": info.serial_number,
            "rank": rank,
        })
    ports.sort(key=lambda p: (-p["rank"], p["device"]))
    return ports
