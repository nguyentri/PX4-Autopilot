#!/usr/bin/env python3
"""Exercise debug script ownership using isolated host processes and tools."""

import os
import re
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / 'platforms/nuttx/Debug'
LIB = DEBUG / 'rzv2h-ipc/rzv2h-ipc-demo-jlink-lib.sh'


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class ProcessOwnership(unittest.TestCase):
    def test_stale_bridge_pid_does_not_signal_foreign_group(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            foreign = subprocess.Popen(['sleep', '60'], start_new_session=True)
            try:
                env = dict(os.environ, STATE_DIR=directory)
                for identity in (None, f"{Path(f'/proc/{foreign.pid}/stat').read_text().rsplit(') ',1)[1].split()[19]}\n/tmp/foreign.jlink\nfixture\nR9A09G057H44_R8_0\n"):
                    (state / 'bridge.pid').write_text(str(foreign.pid))
                    if identity:
                        (state / 'bridge.pid.identity').write_text(identity)
                    subprocess.run(['sh', str(DEBUG / 'nuttx-rtt-bridge.sh'), 'stop'], env=env, check=True, capture_output=True)
                    self.assertIsNone(foreign.poll())
                    self.assertFalse((state / 'bridge.pid').exists())
            finally:
                foreign.terminate()
                foreign.wait(timeout=5)

    def test_owned_rtt_bridge_stops_and_releases_port(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'JLinkExe', '''#!/usr/bin/env python3
import os,socket,sys,time
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(os.environ['RTT_PORT'])));s.listen()
print('Script processing completed.',flush=True);time.sleep(60)
''')
            executable(tmp / 'nc', '''#!/usr/bin/env python3
import socket,sys
try: s=socket.create_connection((sys.argv[-2],int(sys.argv[-1])),.1);s.close()
except OSError: sys.exit(1)
''')
            port = free_port()
            env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', STATE_DIR=str(tmp / 'state'), JLINK_SERIAL='fixture', RTT_PORT=str(port))
            command = ['sh', str(DEBUG / 'nuttx-rtt-bridge.sh')]
            pid = None
            try:
                started = subprocess.run(command + ['start', 'cr8_0'], env=env, capture_output=True, text=True, timeout=25)
                self.assertEqual(started.returncode, 0, started.stdout + started.stderr)
                pid = int((tmp / 'state/bridge.pid').read_text())
                status = subprocess.run(command + ['status'], env=env, capture_output=True, text=True, check=True)
                self.assertIn(f'running pid {pid}', status.stdout)
                subprocess.run(command + ['stop'], env=env, check=True, capture_output=True)
                with socket.socket() as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(('127.0.0.1', port))
            finally:
                subprocess.run(command + ['stop'], env=env, capture_output=True)

    def test_foreign_listener_survives_loader_preflight(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            port = sock.getsockname()[1]
            result = subprocess.run(['sh', '-c', '. "$1"; GDB_PORT="$2"; preflight_probe_free', 'fixture', str(LIB), str(port)], capture_output=True)
            self.assertEqual(result.returncode, 1)
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                pass

    def test_loader_reaps_owned_servers_and_rejects_failed_gdb_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', '''#!/usr/bin/env python3
import os,socket,sys,time
with open(os.environ['PID_LOG'],'a') as f:f.write(str(os.getpid())+'\\n')
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();time.sleep(60)
''')
            executable(tmp / 'gdb', '#!/bin/sh\necho SET_PC=0x1000\necho RUN_PC=0x1000\nexit "$GDB_RESULT"\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'), JLINK_SERIAL='fixture', GDB_PORT=str(free_port()), LOG_DIR=directory, LOADSTART='fixture', VERIFY='fixture', PID_LOG=str(tmp / 'pids'))
            shell = '. "$1"; trap _stop_server EXIT; resolve_tools; load_core fixture fixture.elf test'
            for status in ('1', '0'):
                env['GDB_RESULT'] = status
                result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, int(status), result.stdout + result.stderr)
                for pid in (tmp / 'pids').read_text().splitlines():
                    self.assertFalse(Path(f'/proc/{pid}').exists(), f'owned child {pid} was not reaped')

    def test_verify_rejects_a_core_parked_at_the_reset_vector(self):
        # The verify script prints RUN_PC with printf "%#x", which renders a
        # parked core's zero PC as a bare "0" rather than "0x0".
        self.assertIn('printf "RUN_PC=%#x', (DEBUG / 'rzv2h-ipc/rzv2h-ipc-hil-verify-resume.gdb').read_text())
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', '''#!/usr/bin/env python3
import socket,sys,time
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();time.sleep(60)
''')
            executable(tmp / 'gdb', '#!/bin/sh\necho "RUN_PC=$RUN_PC CPSR=0x1d3"\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'), JLINK_SERIAL='fixture',
                       GDB_PORT=str(free_port()), LOG_DIR=directory, LOADSTART='fixture', VERIFY='fixture')
            shell = '. "$1"; trap _stop_server EXIT; resolve_tools; verify_core fixture fixture.elf test'
            for pc, status in (('0', 1), ('0x0', 1), ('0x4080be14', 0)):
                env['RUN_PC'] = pc
                result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, status, pc + result.stdout + result.stderr)

    def test_uploader_leaves_external_server_alone_and_removes_command_file(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'gdb-multiarch', '#!/bin/sh\nwhile [ "$1" != -x ]; do shift; done\nshift\necho "$1" >>"$COMMAND_LOG"\nexit "$GDB_RESULT"\n')
            executable(tmp / 'killall', '#!/bin/sh\necho forbidden >>"$KILL_LOG"\n')
            executable(tmp / 'sleep', '#!/bin/sh\nexit 0\n')
            elf = tmp / 'fixture image.elf'
            elf.write_bytes(b'fixture')
            env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', TMPDIR=directory, COMMAND_LOG=str(tmp / 'commands'), KILL_LOG=str(tmp / 'kills'))
            for status in ('1', '0'):
                env['GDB_RESULT'] = status
                result = subprocess.run(['sh', str(DEBUG / 'upload_jlink_gdb.sh'), str(elf)], env=env, capture_output=True)
                self.assertEqual(result.returncode, int(status))
                self.assertFalse((tmp / 'kills').exists())
                for path in (tmp / 'commands').read_text().splitlines():
                    self.assertFalse(Path(path).exists())


class WarmStart(unittest.TestCase):
    """A halt-load-jump start must not inherit the halted image's CPSR: with
    IRQs unmasked, a still-pending GTM/HRT interrupt fires on the first
    __start instruction, before the new image installs any handler."""

    RESET_CPSR = 0x1d3

    def test_reset_cpsr_is_svc_with_async_abort_irq_and_fiq_masked(self):
        self.assertEqual(self.RESET_CPSR & 0x1f, 0x13)
        self.assertEqual(self.RESET_CPSR & 0x1c0, 0x1c0)
        self.assertEqual(self.RESET_CPSR & 0x20, 0)

    def assert_each_start_masks_interrupts(self, lines, name):
        starts = [i for i, line in enumerate(lines) if re.match(r'set \$pc = &?__start$', line)]
        self.assertTrue(starts, name)
        for i in starts:
            self.assertEqual(lines[i + 1], f'set $cpsr = {self.RESET_CPSR:#x}', f'{name}:{i + 1}')

    def test_ram_loaders_enter_start_with_reset_cpsr(self):
        gdb = [line.strip() for line in (DEBUG / 'rzv2h-ipc/rzv2h-ipc-hil-loadstart.gdb').read_text().splitlines()]
        self.assert_each_start_masks_interrupts(gdb, 'loadstart.gdb')
        self.assertLess(gdb.index('set $cpsr = 0x1d3'), gdb.index('monitor go'))
        launch = re.findall(r'^\s*"([^"]*)",?\s*$', (DEBUG / 'launch_renesas.json.in').read_text(), re.M)
        self.assert_each_start_masks_interrupts(launch, 'launch_renesas.json.in')


if __name__ == '__main__':
    unittest.main()
