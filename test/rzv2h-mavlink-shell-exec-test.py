#!/usr/bin/env python3
"""Host test for platforms/nuttx/Debug/rzv2h-mavlink-shell-exec.py.

A fake pymavlink connection plays the PX4 MAVLink shell: it echoes each line,
answers known commands and echoes markers. Covers marker framing, ANSI and
prompt stripping, chunking, the single retry after a dropped marker and the
timeout result.
"""
import importlib.util
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('mavsh', ROOT / 'platforms/nuttx/Debug/rzv2h-mavlink-shell-exec.py')
mavsh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mavsh)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeShell:
    """Line-oriented fake of the PX4 shell behind SERIAL_CONTROL."""

    def __init__(self, clock, answers, drop_markers=0, silent=False, cache_errors=0):
        self.clock = clock
        self.cache_errors = cache_errors
        self.answers = answers
        self.drop_markers = drop_markers
        self.silent = silent
        self.rx = ''
        self.out = []
        self.frames = []
        self.heartbeats = 0
        self.mav = types.SimpleNamespace(serial_control_send=self._send, heartbeat_send=self._heartbeat)

    def _heartbeat(self, *args):
        self.heartbeats += 1

    def _send(self, device, flags, timeout, baud, count, data):
        assert device == mavsh.DEVICE_SHELL and len(data) == mavsh.CHUNK
        self.frames.append(count)
        self.rx += bytes(data[:count]).decode()

        while '\n' in self.rx:
            line, self.rx = self.rx.split('\n', 1)
            self._line(line)

    def _line(self, line):
        if self.silent:
            return

        reply = 'nsh> \x1b[K' + line + '\r\n'

        if line.startswith('echo '):
            if self.drop_markers:
                self.drop_markers -= 1
                self.out.append(reply)
                return

            reply += line[5:] + '\r\n'
        elif line:
            reply += self.answers.get(line, 'nsh: %s: command not found\r\n' % line.split()[0])

        # Deliver in odd-sized pieces like SERIAL_CONTROL frames do.
        for i in range(0, len(reply), 7):
            self.out.append(reply[i:i + 7])

    def recv_match(self, type, blocking, timeout, condition=None):
        self.clock.t += timeout

        if self.cache_errors:
            self.cache_errors -= 1
            raise TypeError("'NoneType' object does not support item assignment")

        if not self.out:
            return None

        data = list(self.out.pop(0).encode())
        return types.SimpleNamespace(count=len(data), data=data + [0] * (70 - len(data)))


class MavShellTest(unittest.TestCase):
    def make(self, **kw):
        clock = FakeClock()
        fake = FakeShell(clock, {'rzv2h_heartbeat status': 'INFO  [rzv2h_heartbeat] peer: alive age_ms 40\r\n'
                                 'INFO  [rzv2h_heartbeat] role: initiator\r\n'}, **kw)
        return fake, mavsh.MavShell(fake, poll_s=0.03, clock=clock)

    def test_marker_frames_output_and_strips_prompt_echo_ansi(self):
        fake, shell = self.make()
        ok, text = shell.run('rzv2h_heartbeat status', 5.0)
        self.assertTrue(ok)
        self.assertEqual(text, 'INFO  [rzv2h_heartbeat] peer: alive age_ms 40\nINFO  [rzv2h_heartbeat] role: initiator')
        self.assertNotIn('\x1b', text)
        self.assertNotIn('MAVSH_DONE', text)
        self.assertGreater(fake.heartbeats, 0)

    def test_unknown_command_is_framed_not_hidden(self):
        _, shell = self.make()
        ok, text = shell.run('nope', 5.0)
        self.assertTrue(ok)
        self.assertIn('command not found', text)

    def test_markers_are_unique_per_attempt(self):
        _, shell = self.make()
        self.assertTrue(shell.run('rzv2h_heartbeat status', 5.0)[0])
        ok, text = shell.run('rzv2h_heartbeat status', 5.0)
        self.assertTrue(ok)
        self.assertEqual(shell.serial, 2)
        self.assertNotIn('MAVSH_DONE_1', text)

    def test_long_command_is_chunked_to_70_bytes(self):
        fake, shell = self.make()
        shell.write('x' * 150 + '\n')
        self.assertEqual(fake.frames, [70, 70, 11])

    def test_dropped_marker_is_retried_once(self):
        _, shell = self.make(drop_markers=1)
        ok, text = shell.run('rzv2h_heartbeat status', 2.0)
        self.assertTrue(ok)
        self.assertEqual(shell.serial, 2)
        self.assertIn('role: initiator', text)

    def test_two_dropped_markers_fail_without_third_attempt(self):
        _, shell = self.make(drop_markers=2)
        ok, _ = shell.run('rzv2h_heartbeat status', 2.0)
        self.assertFalse(ok)
        self.assertEqual(shell.serial, 2)

    def test_silent_link_times_out(self):
        fake, shell = self.make(silent=True)
        ok, text = shell.run('ver all', 1.0)
        self.assertFalse(ok)
        self.assertEqual(text, '')
        self.assertGreaterEqual(fake.clock.t, 2.0)

    def test_pymavlink_cache_type_error_is_skipped(self):
        _, shell = self.make(cache_errors=3)
        ok, text = shell.run('rzv2h_heartbeat status', 5.0)
        self.assertTrue(ok)
        self.assertIn('role: initiator', text)

    def test_wait_heartbeat_survives_cache_errors_and_times_out(self):
        clock = FakeClock()
        fake = FakeShell(clock, {}, cache_errors=2)
        self.assertIsNone(mavsh.wait_heartbeat(fake, 3.0, clock=clock))
        self.assertGreaterEqual(clock.t, 3.0)

    def test_other_type_errors_propagate(self):
        conn = types.SimpleNamespace(recv_match=lambda **kw: None + 1)
        with self.assertRaises(TypeError):
            mavsh.recv_match(conn, type='HEARTBEAT')

    def test_usage_error_exits_2(self):
        with self.assertRaises(SystemExit) as cm:
            mavsh.main([])
        self.assertEqual(cm.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
