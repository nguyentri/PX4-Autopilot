#!/usr/bin/env python3
"""Exercise the J-Link debug tools against fake probes, servers and shells:
the read-only one-shot GDB runner, the NSH marker mode, the RTT bridge
connect-reset guard, the loader retry and verify guards and the host
preflight. The PX4 health snippets are also resolved against the built ELFs
when they exist."""

import importlib.util
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEBUG = ROOT / 'platforms/nuttx/Debug'
ONESHOT = DEBUG / 'jlink-gdb-oneshot.py'
PREFLIGHT = DEBUG / 'jlink-debug-preflight.py'
LIB = DEBUG / 'rzv2h-ipc/rzv2h-ipc-demo-jlink-lib.sh'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executable(path, text):
    path.write_text(text)
    path.chmod(0o755)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


# Fake JLinkGDBServerCLExe: records its argv, prints $SERVER_SAYS, listens on -port.
FAKE_SERVER = '''#!/usr/bin/env python3
import os,socket,sys,time
open(os.environ['ARGV_LOG'],'a').write(' '.join(sys.argv[1:])+'\\n')
print(os.environ.get('SERVER_SAYS',''),flush=True)
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();time.sleep(60)
'''
# Fake gdb: records its argv; prints $GDB_STDERR; attaches unless GDB_ATTACH=0.
FAKE_GDB = '''#!/usr/bin/env python3
import os,sys
open(os.environ['GDB_LOG'],'a').write('\\0'.join(sys.argv[1:])+'\\n')
if os.environ.get('GDB_STDERR'): print(os.environ['GDB_STDERR'],file=sys.stderr)
if os.environ.get('GDB_ATTACH','1')=='1':
    print('ONESHOT_ATTACHED pc=0x40801234')
    print('Detaching from program: x, Remote target')
    print('[Inferior 1 (Remote target) detached]')
'''


class OneShotReadOnlyFilter(unittest.TestCase):
    def setUp(self):
        self.m = load(ONESHOT, 'oneshot')

    def test_inspection_commands_pass(self):
        for line in ('bt', 'p g_hrt', 'p/x $cpsr', 'x/4wx 0x10000000', 'info registers pc',
                     'p ((Px4IoCr8*)ModuleBase<Px4IoCr8>::_object._value)->_loop_count',
                     'printf "a=%d\\n", g_x', 'p a == b', 'p a <= b', 'p sizeof(struct s)',
                     'set pagination off', 'set print pretty on', 'set $i = 0',
                     'dump binary memory /tmp/x.bin buf buf+16', '# comment', '',
                     'p $_streq("a", "a")', 'while $i < 4', 'end'):
            self.assertIsNone(self.m.mutation_reason(line), line)

    def test_shipped_snippets_are_read_only(self):
        snippets = sorted((DEBUG / 'rzv2h-ipc').glob('rzv2h-px4-*.gdb'))
        self.assertTrue(snippets)
        for snippet in snippets:
            for line in snippet.read_text().splitlines():
                self.assertIsNone(self.m.mutation_reason(line), f'{snippet.name}: {line}')

    def test_shipped_snippets_resolve_against_their_elfs(self):
        gdb = shutil.which('gdb-multiarch')
        elfs = {'cr8_0': ROOT / 'build/renesas_rdk-rzv2h_dualcr8/renesas_rdk-rzv2h_dualcr8.elf',
                'cr8_1': ROOT / 'build/renesas_rdk-rzv2h-io-cr8_1_default/'
                'renesas_rdk-rzv2h-io-cr8_1_default.elf'}
        config = elfs['cr8_0'].parent/'boardconfig'
        if config.is_file() and 'CONFIG_BOARD_RDK_RZV2H_PX4IO_BRIDGE=y' not in config.read_text():
            self.skipTest('legacy bridge snippets require an image with the bridge selected')
        if not gdb or not all(elf.is_file() for elf in elfs.values()):
            self.skipTest('needs gdb-multiarch and the dualcr8 + io-cr8_1 builds')
        for snippet in sorted((DEBUG / 'rzv2h-ipc').glob('rzv2h-px4-cr8_*.gdb')):
            elf = elfs[re.search(r'cr8_\d', snippet.name).group(0)]
            args = []
            for line in snippet.read_text().splitlines():
                match = re.match(r'p(?:/\w+)?\s+(.+)', line)
                if match:  # ptype checks names and members without a target
                    args += ['-ex', f'ptype {match.group(1)}']
            self.assertTrue(args, snippet.name)
            result = subprocess.run([gdb, '-q', '-batch', '-nx', str(elf)] + args,
                                    capture_output=True, text=True, timeout=120)
            self.assertEqual(result.stderr.strip(), '', snippet.name)

    def test_target_changing_commands_are_refused(self):
        for line in ('load', 'restore f.bin binary 0', 'call foo()', 'jump *0x0', 'continue',
                     'c', 'step', 'si', 'monitor reset', 'monitor go', 'break main',
                     'hbreak arm_dataabort', 'watch x', 'source evil.gdb', 'shell ls', 'python 1',
                     'set var x = 1', 'set $pc = 0', 'set $cpsr=0x1d3', 'set {int}0x1000 = 1',
                     'p x = 1', 'p x++', 'p --x', 'p reset_board(1)', 'output g = 2', 'kill'):
            self.assertIsNotNone(self.m.mutation_reason(line), line)


class OneShotRunner(unittest.TestCase):
    def run_oneshot(self, args, tmp, **env_extra):
        executable(tmp / 'server', FAKE_SERVER)
        executable(tmp / 'gdb', FAKE_GDB)
        elf = tmp / 'image.elf'
        elf.write_bytes(b'\x7fELF')
        env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'),
                   JLINK_SERIAL='fixture', GDB_PORT=str(free_port()),
                   ARGV_LOG=str(tmp / 'server.argv'), GDB_LOG=str(tmp / 'gdb.argv'), **env_extra)
        return subprocess.run([sys.executable, str(ONESHOT)] + args[:1] + [str(elf)] + args[1:],
                              env=env, capture_output=True, text=True, timeout=60)

    def test_read_attaches_without_reset_and_always_detaches_last(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result = self.run_oneshot(['cr8_1', '-ex', 'bt', '-ex', 'p g_x'], tmp)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            server = (tmp / 'server.argv').read_text().split()
            for flag in ('-noreset', '-noir', '-singlerun', '-nogui'):
                self.assertIn(flag, server)
            self.assertEqual(server[server.index('-device') + 1], 'R9A09G057H44_R8_1')
            self.assertEqual(server[server.index('-select') + 1], 'usb=fixture')
            gdb = (tmp / 'gdb.argv').read_text().strip().split('\0')
            self.assertEqual(gdb[-2:], ['-ex', 'detach'])
            self.assertLess(gdb.index('bt'), gdb.index('p g_x'))
            self.assertLess(next(i for i, a in enumerate(gdb) if a.startswith('target remote')), gdb.index('bt'))

    def test_mutation_is_refused_before_the_probe_is_touched(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            script = tmp / 'cmds.gdb'
            script.write_text('bt\nset var g_x = 1\n')
            for args in (['cr8_0', '-ex', 'monitor reset'], ['cr8_0', '-x', str(script)], ['cm33', '-ex', 'bt']):
                result = self.run_oneshot(args, tmp)
                self.assertEqual(result.returncode, 2, args)
                self.assertFalse((tmp / 'server.argv').exists(), args)

    def test_reset_in_server_log_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result = self.run_oneshot(['cr8_0', '-ex', 'bt'], tmp,
                                      SERVER_SAYS='ERROR: Cortex-A/R (connect): Core internal signal DBGEN is not asserted.')
            self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
            self.assertIn('reset', result.stderr)

    def test_failed_gdb_command_is_reported_after_detaching(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result = self.run_oneshot(['cr8_0', '-ex', 'p g_missing'], tmp,
                                      GDB_STDERR='No symbol "g_missing" in current context.')
            self.assertEqual(result.returncode, 6, result.stdout + result.stderr)
            self.assertIn('g_missing', result.stderr)
            quiet = self.run_oneshot(['cr8_0', '-ex', 'bt'], tmp, GDB_STDERR='warning: no loadable sections')
            self.assertEqual(quiet.returncode, 0, quiet.stdout + quiet.stderr)

    def test_failed_attach_retries_three_times(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result = self.run_oneshot(['cr8_0', '-ex', 'bt'], tmp, GDB_ATTACH='0')
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(len((tmp / 'server.argv').read_text().splitlines()), 3)


class FakeNsh(threading.Thread):
    """A SEGGER-style RTT channel running NSH, where a task logs one line
    right after each command's prompt (as DEBUG_INFO builds do)."""

    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen()
        self.port = self.srv.getsockname()[1]

    def run(self):
        while True:
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            conn.sendall(b'SEGGER J-Link V0 - Real time terminal output\r\nProcess: JLinkExe\r\n')
            buf = b''
            while True:
                data = conn.recv(1024)
                if not data:
                    break
                buf += data
                while b'\r\n' in buf:
                    line, buf = buf.split(b'\r\n', 1)
                    conn.sendall(line + b'\r\n')
                    if line.startswith(b'echo '):
                        conn.sendall(line[5:] + b'\r\nnsh> ')
                    elif line:
                        conn.sendall(b'out:' + line + b'\r\nnsh> ')
                        time.sleep(0.05)
                        conn.sendall(b'[log] SCI6 clocks enabled\r\n')
                    else:
                        conn.sendall(b'nsh> ')
            conn.close()


class NshMarkerMode(unittest.TestCase):
    def test_marker_mode_survives_log_lines_after_the_prompt(self):
        nsh = FakeNsh()
        nsh.start()
        try:
            run = lambda *extra: subprocess.run(
                [sys.executable, str(DEBUG / 'nsh_console_exec.py'), '--rtt', str(nsh.port),
                 '--timeout', '2', *extra, 'ps', 'free'], capture_output=True, text=True, timeout=30)
            prompt = run()
            self.assertEqual(prompt.returncode, 1, prompt.stdout + prompt.stderr)
            marker = run('--marker')
            self.assertEqual(marker.returncode, 0, marker.stdout + marker.stderr)
            self.assertIn('out:ps', marker.stdout)
            self.assertIn('out:free', marker.stdout)
            self.assertNotIn('NSHX_', marker.stdout)
            self.assertNotIn('echo ', marker.stdout)
        finally:
            nsh.srv.close()


class RttBridgeConnectGuard(unittest.TestCase):
    def start_bridge(self, tmp, jlink_body, **extra_env):
        executable(tmp / 'JLinkExe', jlink_body)
        executable(tmp / 'nc', '''#!/usr/bin/env python3
import socket,sys
try: s=socket.create_connection((sys.argv[-2],int(sys.argv[-1])),.1);s.close()
except OSError: sys.exit(1)
''')
        port = free_port()
        env = dict(os.environ, PATH=f'{tmp}:{os.environ["PATH"]}', STATE_DIR=str(tmp / 'state'),
                   JLINK_SERIAL='fixture', RTT_PORT=str(port), **extra_env)
        command = ['sh', str(DEBUG / 'nuttx-rtt-bridge.sh')]
        result = subprocess.run(command + ['start', 'cr8_0', '0x081a2400'], env=env,
                                capture_output=True, text=True, timeout=30)
        subprocess.run(command + ['stop'], env=env, capture_output=True)
        return result, port

    def test_command_file_inhibits_reset_retries_before_connecting(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result, _ = self.start_bridge(tmp, '''#!/usr/bin/env python3
import os,shutil,socket,sys,time
shutil.copy(sys.argv[sys.argv.index('-CommandFile')+1], os.environ['STATE_DIR']+'/seen.jlink')
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(os.environ['RTT_PORT'])));s.listen()
print('Script processing completed.',flush=True);time.sleep(60)
''')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = (tmp / 'state/seen.jlink').read_text().splitlines()
            self.assertEqual(lines[0], 'exec InhibitConnectRetries = 1')
            self.assertEqual(lines[-1], 'connect')
            self.assertIn('exec SetRTTAddr 0x081a2400', lines)
            self.assertNotIn('rtt start', lines)

    def test_readiness_does_not_consume_a_single_client_boot_buffer(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result, _ = self.start_bridge(tmp, '''#!/usr/bin/env python3
import os,socket,time
seen=os.environ['STATE_DIR']+'/clients'
open(seen,'w').close()
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(os.environ['RTT_PORT'])));s.listen()
print('Script processing completed.',flush=True)
while True:
    conn,_=s.accept()
    with open(seen,'a') as output: output.write('boot buffer consumed\\n')
    try: conn.sendall(b'RETAINED BOOT RESULT\\r\\n')
    except OSError: pass
    conn.close()
''')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((tmp / 'state/clients').read_text(), '')

    def test_logged_reset_fails_the_start_and_releases_the_port(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result, port = self.start_bridge(tmp, '''#!/usr/bin/env python3
import os,socket,time
print('Connect failed. Resetting via Reset pin and trying again.',flush=True)
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(os.environ['RTT_PORT'])));s.listen();time.sleep(60)
''')
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertIn('RESET', result.stderr)
            with socket.socket() as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('127.0.0.1', port))

    def test_connect_failure_after_the_port_opens_still_fails(self):
        # JLinkExe serves the RTT port before its connect result is known.
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            # A /bin/sh fake keeps the JLinkExe process name the bridge checks.
            result, _ = self.start_bridge(tmp, '''#!/bin/sh
python3 -c "import os,socket,time
s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
s.bind(('127.0.0.1',int(os.environ['RTT_PORT'])));s.listen();time.sleep(60)" &
sleep 1
echo '****** Error: Cortex-A/R (connect): Core internal signal DBGEN is not asserted.'
echo 'Error occurred: Could not connect to the target device.'
echo 'Script processing completed.'
sleep 60
''')
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertNotIn('RESET', result.stderr)
            self.assertIn('held in reset or was never started', result.stderr)

    def test_connect_timeout_kills_a_stuck_jlinkexe_and_cleans_up(self):
        # On a stopped CR8 the J-Link InitTarget script blocks for 60 s and
        # JLinkExe ignores SIGTERM meanwhile.
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            result, _ = self.start_bridge(tmp, '''#!/bin/sh
trap '' TERM
echo '  Enabling CR8 clocks...'
sleep 60
''', CONNECT_TIMEOUT='2')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('not finished', result.stderr)
            self.assertNotIn('not released', result.stderr)
            self.assertEqual(sorted(p.name for p in (tmp / 'state').iterdir()), ['jlinkexe.log'])
            stuck = subprocess.run(['pgrep', '-f', str(tmp / 'JLinkExe')], capture_output=True)
            self.assertEqual(stuck.returncode, 1, stuck.stdout)

    def test_failed_connect_fails_fast_without_claiming_a_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            started = time.monotonic()
            result, _ = self.start_bridge(tmp, '''#!/usr/bin/env python3
import time
print('Cannot connect to target.',flush=True);time.sleep(60)
''')
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertNotIn('RESET', result.stderr)
            self.assertLess(time.monotonic() - started, 10)


class LoaderVerifyGuard(unittest.TestCase):
    def test_verify_attaches_without_reset_and_fails_on_a_logged_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', FAKE_SERVER)
            executable(tmp / 'gdb', '#!/bin/sh\necho "RUN_PC=0x4080be14 CPSR=0x1d3"\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'), JLINK_SERIAL='fixture',
                       GDB_PORT=str(free_port()), LOG_DIR=directory, LOADSTART='fixture', VERIFY='fixture',
                       ARGV_LOG=str(tmp / 'server.argv'))
            shell = '. "$1"; trap _stop_server EXIT; resolve_tools; verify_core fixture fixture.elf test'
            for says, status in (('', 0), ('ERROR: Core internal signal DBGEN is not asserted.', 1)):
                env['SERVER_SAYS'] = says
                result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, status, says + result.stdout + result.stderr)
            for argv in (tmp / 'server.argv').read_text().splitlines():
                self.assertIn('-noreset -noir', argv)

    def test_load_retry_judges_only_its_own_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            # First server start: the core is held in reset (dead image).
            executable(tmp / 'server', FAKE_SERVER.replace(
                "print(os.environ.get('SERVER_SAYS',''),flush=True)",
                "print('ERROR: Core internal signal DBGEN is not asserted.' if len(open(os.environ['ARGV_LOG'])"
                ".read().splitlines())==1 else '',flush=True)"))
            # First gdb run fails like the first remote connect does on the board.
            executable(tmp / 'gdb', '#!/bin/sh\nif [ -f "$GDB_RAN" ]; then echo "SET_PC=0x40800000"; '
                       'else : >"$GDB_RAN"; echo "Protocol error: QStartNoAckMode"; exit 1; fi\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'), JLINK_SERIAL='fixture',
                       GDB_PORT=str(free_port()), LOG_DIR=directory, LOADSTART='fixture', VERIFY='fixture',
                       ARGV_LOG=str(tmp / 'server.argv'), GDB_RAN=str(tmp / 'gdb.ran'))
            shell = '. "$1"; trap _stop_server EXIT; resolve_tools; load_core fixture fixture.elf test'
            result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr.count('DBGEN not asserted'), 1, result.stderr)
            self.assertNotIn('cold reset', result.stderr)

    def test_one_core_loader_loads_then_verifies(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', FAKE_SERVER)
            executable(tmp / 'gdb', '#!/bin/sh\necho "SET_PC=0x40800000"\necho "RUN_PC=0x4080be14"\n')
            elf = tmp / 'image.elf'
            elf.write_bytes(b'\x7fELF')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'), JLINK_SERIAL='fixture',
                       GDB_PORT=str(free_port()), LOG_DIR=directory, ARGV_LOG=str(tmp / 'server.argv'))
            loader = str(DEBUG / 'rzv2h-ipc/rzv2h-load-one-core.sh')
            bad = subprocess.run(['sh', loader, 'cm33', str(elf)], env=env, capture_output=True, timeout=30)
            self.assertEqual(bad.returncode, 2)
            result = subprocess.run(['sh', loader, 'cr8_0', str(elf)], env=env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            argvs = (tmp / 'server.argv').read_text().splitlines()
            self.assertEqual(len(argvs), 2)
            self.assertIn('R9A09G057H44_R8_0', argvs[0])
            self.assertNotIn('-noreset', argvs[0])
            self.assertIn('-noreset -noir', argvs[1])


class Preflight(unittest.TestCase):
    def test_elf_entry_maps_to_the_linked_core(self):
        m = load(PREFLIGHT, 'preflight')
        with tempfile.TemporaryDirectory() as directory:
            for entry, core in ((0x40800000, 'cr8_0'), (0x41800000, 'cr8_1'), (0x08002fc1, 'cm33'), (0x02000000, '?')):
                path = Path(directory) / f'{entry:x}.elf'
                path.write_bytes(b'\x7fELF\x01\x01' + bytes(0x12) + struct.pack('<I', entry))
                self.assertEqual(m.elf_entry(path), entry)
                self.assertEqual(m.core_of(entry), core)

    def test_report_runs_without_touching_a_probe(self):
        result = subprocess.run([sys.executable, str(PREFLIGHT)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        for section in ('== tools', '== USB', '== probe owners', '== ports', '== ELFs'):
            self.assertIn(section, result.stdout)


if __name__ == '__main__':
    unittest.main()
