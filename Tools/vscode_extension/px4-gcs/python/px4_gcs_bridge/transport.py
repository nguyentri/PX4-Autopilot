"""Byte transports the sidecar owns: serial (after the lease) and UDP.

Both expose `read() -> list[(bytes, source)]`, `write(bytes, dest)` and `close()`.
"""
from __future__ import annotations

import errno
import socket

from .protocol import BridgeError

READ_TIMEOUT = 0.05


class SerialTransport:
    kind = "serial"

    def __init__(self, device: str, baud: int):
        try:
            import serial
        except ImportError:
            raise BridgeError("MISSING_MODULE", "pyserial is not installed") from None
        self.device, self.baud = device, baud
        try:
            self._port = serial.Serial(device, baud, timeout=READ_TIMEOUT, write_timeout=1, exclusive=True)
        except serial.SerialException as error:
            raise _serial_error(device, error) from None

    def set_baud(self, baud: int) -> None:
        self._port.baudrate = baud
        self._port.reset_input_buffer()
        self.baud = baud

    def read(self):
        data = self._port.read(max(1, min(self._port.in_waiting, 4096)))
        return [(data, None)] if data else []

    def write(self, data: bytes, _dest=None) -> None:
        self._port.write(data)

    def describe(self) -> dict:
        return {"transport": "serial", "port": self.device, "baud": self.baud}

    def close(self) -> None:
        try:
            self._port.close()
        except Exception:  # noqa: BLE001 - closing a vanished device must not raise
            pass


def _serial_error(device, error):
    code = getattr(error, "errno", None)
    text = str(error)
    if code == errno.ENOENT or "No such file" in text:
        return BridgeError("PORT_NOT_FOUND", f"{device} does not exist")
    if code in (errno.EACCES, errno.EPERM) or "Permission denied" in text:
        return BridgeError("PERMISSION_DENIED", f"no access to {device}")
    if "lock" in text.lower() or code in (errno.EAGAIN, errno.EBUSY):
        return BridgeError("PORT_BUSY", f"{device} is held exclusively by another process")
    return BridgeError("INTERNAL", f"cannot open {device}: {text}")


class UdpTransport:
    kind = "udp"

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.bind((host, port))
        except OSError as error:
            self._sock.close()
            if error.errno == errno.EADDRINUSE:
                raise BridgeError("PORT_BUSY", f"UDP {host}:{port} is already bound") from None
            if error.errno in (errno.EACCES, errno.EPERM):
                raise BridgeError("PERMISSION_DENIED", f"cannot bind UDP {host}:{port}") from None
            raise BridgeError("BAD_ARGUMENT", f"cannot bind UDP {host}:{port}: {error}") from None
        self._sock.settimeout(READ_TIMEOUT)

    def read(self):
        try:
            data, source = self._sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            return []
        except ConnectionRefusedError:
            return []
        return [(data, source)]

    def write(self, data: bytes, dest=None) -> None:
        if dest is not None:
            try:
                self._sock.sendto(data, dest)
            except OSError:
                pass

    def describe(self) -> dict:
        return {"transport": "udp", "host": self.host, "udpPort": self.port}

    def close(self) -> None:
        self._sock.close()
