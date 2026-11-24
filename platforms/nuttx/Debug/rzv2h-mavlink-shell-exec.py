#!/usr/bin/env python3
"""Run PX4 shell commands non-interactively over the MAVLink shell.

PX4 images on the RZ/V2H CR8-0 expose NSH only through MAVLink SERIAL_CONTROL
(device SHELL) on SCI5; there is no NSH on that UART. This is the scripted
counterpart of Tools/mavlink_shell.py, with the output framing of
nsh_console_exec.py:

  rzv2h-mavlink-shell-exec.py 'ver all' 'rzv2h_heartbeat status'
  rzv2h-mavlink-shell-exec.py --port /dev/ttyUSB0 --baud 115200 --log run.log 'mavlink status'

Each command is followed by `echo <marker>`; its output ends at the line that
is exactly the marker. A command whose marker never arrives (the telemetry link
drops bytes while telemetry streams) is retried once, never more.
Output is printed as `### <command>` blocks, ANSI sequences stripped.

Exit: 0 all commands framed, 1 no heartbeat or a command timed out twice,
2 usage. The tool never needs the J-Link, so a halted CR8-1 does not affect it.
Never send commands the user did not ask for; read-only commands are safe.
"""
import argparse
import re
import sys
import time

ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CHUNK = 70                      # SERIAL_CONTROL payload size
DEVICE_SHELL = 10               # SERIAL_CONTROL_DEV_SHELL
FLAGS_EXCLUSIVE_RESPOND = 2 | 4  # SERIAL_CONTROL_FLAG_RESPOND | _EXCLUSIVE


def recv_match(conn, **kw):
    """conn.recv_match that survives pymavlink's message-cache TypeError.

    pymavlink's add_message() raises TypeError when a message type was first
    cached without an instance value and later arrives with one; garbled frames
    on a lossy telemetry link trigger it. The failing message is never the
    SERIAL_CONTROL or HEARTBEAT being waited for, so treat it as no message.
    """
    try:
        return conn.recv_match(**kw)
    except TypeError as exc:
        if 'item assignment' not in str(exc):
            raise

        return None


def wait_heartbeat(conn, timeout_s, clock=time.monotonic):
    """First vehicle HEARTBEAT within timeout_s, or None."""
    deadline = clock() + timeout_s

    while clock() < deadline:
        m = recv_match(conn, type='HEARTBEAT', blocking=True, timeout=max(0.0, min(1.0, deadline - clock())))

        if m is not None:
            return m

    return None


class MavShell:
    """SERIAL_CONTROL shell session over an open pymavlink connection."""

    def __init__(self, conn, poll_s=0.03, heartbeat_s=1.0, clock=time.monotonic):
        self.conn = conn
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s
        self.clock = clock
        self.next_heartbeat = 0.0
        self.serial = 0

    def write(self, text):
        data = text.encode()

        while data:
            part, data = data[:CHUNK], data[CHUNK:]
            self.conn.mav.serial_control_send(DEVICE_SHELL, FLAGS_EXCLUSIVE_RESPOND, 0, 0, len(part),
                                              list(part) + [0] * (CHUNK - len(part)))

    def read_some(self):
        # GCS heartbeats keep the vehicle's MAVLink instance treating us as a peer.
        now = self.clock()

        if now >= self.next_heartbeat:
            self.next_heartbeat = now + self.heartbeat_s
            self.conn.mav.heartbeat_send(6, 8, 0, 0, 0)  # MAV_TYPE_GCS, MAV_AUTOPILOT_INVALID

        m = recv_match(self.conn, condition='SERIAL_CONTROL.count!=0', type='SERIAL_CONTROL',
                                 blocking=True, timeout=self.poll_s)
        return bytes(m.data[:m.count]).decode(errors='replace') if m is not None else ''

    def drain(self, quiet_s=0.3):
        """Discard pending output until the shell has been quiet for quiet_s."""
        end = self.clock() + quiet_s

        while self.clock() < end:
            if self.read_some():
                end = self.clock() + quiet_s

    def run(self, command, timeout_s, marker_base='MAVSH_DONE', retries=1):
        """Return (ok, cleaned output) for one command."""
        for _ in range(retries + 1):
            self.serial += 1
            marker = '%s_%d' % (marker_base, self.serial)
            self.write(command + '\n')
            self.write('echo ' + marker + '\n')
            buf = ''
            deadline = self.clock() + timeout_s

            while self.clock() < deadline:
                buf += self.read_some()
                text = ANSI_CSI.sub('', buf).replace('\r', '')
                lines = text.split('\n')

                # The last element may be a partial line; the marker counts
                # only as a whole line, never inside the echoed `echo marker`.
                if any(line.strip() == marker for line in lines[:-1]):
                    return True, clean(text, marker)

            self.drain()

        return False, clean(ANSI_CSI.sub('', buf).replace('\r', ''), None)


def clean(text, marker):
    """Drop prompt/echo lines and everything from the marker line on."""
    out = []

    for line in text.split('\n'):
        if marker is not None and line.strip() == marker:
            break

        if line.startswith('nsh>') or not line.strip():
            continue

        out.append(line)

    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', default='/dev/ttyUSB0', help='MAVLink serial device (default /dev/ttyUSB0)')
    ap.add_argument('--baud', type=int, default=115200, help='baud rate (default 115200)')
    ap.add_argument('--timeout', type=float, default=8.0, help='seconds per command attempt (default 8)')
    ap.add_argument('--heartbeat-timeout', type=float, default=10.0, help='seconds to wait for a vehicle heartbeat')
    ap.add_argument('--marker', default='MAVSH_DONE', help='marker prefix echoed after each command')
    ap.add_argument('--log', help='also append the output to this file')
    ap.add_argument('commands', nargs='+', help='shell commands, run in order')
    args = ap.parse_args(argv)

    try:
        from pymavlink import mavutil
    except ImportError as exc:
        print('pymavlink missing (%s): pip3 install --user pymavlink pyserial' % exc, file=sys.stderr)
        return 2

    conn = mavutil.mavlink_connection(args.port, baud=args.baud, autoreconnect=True)
    conn.mav.heartbeat_send(6, 8, 0, 0, 0)

    if wait_heartbeat(conn, args.heartbeat_timeout) is None:
        print('no MAVLink heartbeat on %s @%d within %.0f s' % (args.port, args.baud, args.heartbeat_timeout),
              file=sys.stderr)
        return 1

    shell = MavShell(conn)
    shell.write('\n')   # start the shell
    shell.drain()
    log = open(args.log, 'a') if args.log else None
    failed = 0

    try:
        for command in args.commands:
            ok, text = shell.run(command, args.timeout, args.marker)
            block = '### %s\n%s\n' % (command, text) + ('' if ok else '!! no marker: command timed out\n')
            sys.stdout.write(block)
            sys.stdout.flush()

            if log:
                log.write(block)

            failed += not ok
    finally:
        conn.mav.serial_control_send(DEVICE_SHELL, 0, 0, 0, 0, [0] * CHUNK)  # release the shell

        if log:
            log.close()

    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
