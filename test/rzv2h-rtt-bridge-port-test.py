#!/usr/bin/env python3
"""Check that nuttx-rtt-bridge.sh serves RTT on the requested TCP port.

A fake JLinkExe on PATH records its argv, listens on the port it was told to
use and reports that its command file finished, so no probe is touched.
"""
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / 'platforms/nuttx/Debug/nuttx-rtt-bridge.sh'

FAKE_JLINKEXE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, socket, sys
    args = sys.argv[1:]
    with open(os.environ['FAKE_ARGV'], 'w') as out:
        out.write('\\n'.join(args))
    port = int(args[args.index('-RTTTelnetPort') + 1]) if '-RTTTelnetPort' in args else 19021
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', port))
    listener.listen(1)
    print('Script processing completed', flush=True)
    sys.stdin.read()
    ''')


def port_free(port):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


class RttBridgePort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / 'bin').mkdir()
        fake = tmp / 'bin/JLinkExe'
        fake.write_text(FAKE_JLINKEXE)
        fake.chmod(0o755)
        self.argv = tmp / 'argv'
        self.env = dict(os.environ, PATH='%s:%s' % (tmp / 'bin', os.environ['PATH']),
                        STATE_DIR=str(tmp / 'state'), JLINK_SERIAL='123456', FAKE_ARGV=str(self.argv),
                        CONNECT_TIMEOUT='10')

    def tearDown(self):
        self.bridge('stop')
        self.tmp.cleanup()

    def bridge(self, *args, **env):
        return subprocess.run(['sh', str(BRIDGE), *args], env=dict(self.env, **env),
                              capture_output=True, text=True, timeout=30)

    def start_and_check(self, port):
        if not port_free(port):
            self.skipTest('port %d is in use on this host' % port)
        started = self.bridge('start', 'cr8_1', '0x081E2400', RTT_PORT=str(port))
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertIn('127.0.0.1:%d' % port, started.stdout)
        status = self.bridge('status')
        self.assertIn('core R9A09G057H44_R8_1, port %d up' % port, status.stdout)
        # stop must wait on the port the bridge was started with.
        stopped = self.bridge('stop')
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertTrue(port_free(port))
        return self.argv.read_text().split('\n')

    def test_non_default_port_is_passed_on_the_command_line(self):
        argv = self.start_and_check(19131)
        self.assertEqual(argv[argv.index('-RTTTelnetPort') + 1], '19131')
        command_file = argv[argv.index('-CommandFile') + 1]
        self.assertFalse(Path(command_file).exists())

    def test_default_port_uses_the_jlinkexe_default(self):
        argv = self.start_and_check(19021)
        self.assertNotIn('-RTTTelnetPort', argv)

    def test_reserved_and_invalid_ports_are_rejected(self):
        for port in ('19022', '19030', '19080', '19081', 'abc', '19021x'):
            with self.subTest(port=port):
                result = self.bridge('start', 'cr8_1', '0x081E2400', RTT_PORT=port)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(self.argv.exists())


if __name__ == '__main__':
    unittest.main()
