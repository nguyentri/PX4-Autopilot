"""Serve a leased UART as raw TCP on 127.0.0.1 for the editor's RTT Monitor.

The caller holds the kernel flock device lease for the whole relay lifetime.
One client at a time; UART output that arrives with no client connected is
kept (last 256 KiB) and replayed to the next one, so the boot banner after a
load is not lost. The J-Link probe is not involved.
"""
from __future__ import annotations

import os
import selectors
import signal
import socket
import termios
import tty

BACKLOG = 256 * 1024


def open_raw_uart(device) -> int:
    fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    tty.setraw(fd)
    attributes = termios.tcgetattr(fd)
    attributes[4] = attributes[5] = termios.B115200
    attributes[2] = (attributes[2] & ~(termios.CSTOPB | termios.PARENB | termios.CRTSCTS)) | termios.CLOCAL | termios.CREAD
    termios.tcsetattr(fd, termios.TCSANOW, attributes)
    return fd


def relay(device, port: int, announce) -> int:
    """Runs until SIGTERM/SIGINT/SIGHUP (exit 130) or a UART error (exit 1)."""
    stopping = []
    previous = {number: signal.signal(number, lambda *_: stopping.append(True))
                for number in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)}
    uart = open_raw_uart(device)
    listener = socket.create_server(("127.0.0.1", port))
    listener.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(uart, selectors.EVENT_READ, "uart")
    selector.register(listener, selectors.EVENT_READ, "listen")
    client = None
    pending = bytearray()
    try:
        announce(f"serial relay up: {device} -> 127.0.0.1:{listener.getsockname()[1]}")
        while not stopping:
            for key, _ in selector.select(0.1):
                if key.data == "listen":
                    conn, _ = listener.accept()
                    if client:
                        conn.sendall(b"\r\n<<serial-relay: console already has a client>>\r\n")
                        conn.close()
                        continue
                    conn.setblocking(False)
                    client = conn
                    selector.register(client, selectors.EVENT_READ, "client")
                elif key.data == "uart":
                    try:
                        data = os.read(uart, 4096)
                    except BlockingIOError:
                        continue
                    pending += data
                    del pending[:max(0, len(pending) - BACKLOG)]
                else:
                    try:
                        data = client.recv(4096)
                    except BlockingIOError:
                        continue
                    except OSError:
                        data = b""
                    if data:
                        os.write(uart, data)
                    else:
                        selector.unregister(client)
                        client.close()
                        client = None
            if client and pending:
                try:
                    del pending[:client.send(pending)]
                except BlockingIOError:
                    pass
                except OSError:
                    selector.unregister(client)
                    client.close()
                    client = None
        return 130
    except OSError as error:
        announce(f"serial relay stopped: {error}")
        return 1
    finally:
        if client:
            client.close()
        listener.close()
        selector.close()
        os.close(uart)
        for number, handler in previous.items():
            signal.signal(number, handler)
