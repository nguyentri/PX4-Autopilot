#!/usr/bin/env python3
"""Exercise debug script ownership using isolated host processes and tools."""

import os
import importlib.util
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
    def test_pair_loader_never_connects_again_after_first_verify_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp=Path(directory)
            loader=tmp/'rzv2h-ipc-demo-load-both-auto.sh'
            loader.write_text((DEBUG/'rzv2h-ipc'/loader.name).read_text())
            (tmp/LIB.name).write_text('''resolve_tools() { return 0; }
_stop_server() { return 0; }
load_core() { echo "load $3" >>"$CORE_LOG"; }
verify_core() {
 echo "verify $3" >>"$CORE_LOG"
 if [ "$3" = CR8-0 ] && [ "$FAIL_FIRST_VERIFY" = 1 ]; then return 1; fi
 return 0
}
''')
            for name in ('rzv2h-ipc-hil-loadstart.gdb','rzv2h-ipc-hil-verify-resume.gdb','core0.elf','core1.elf'):
                (tmp/name).touch()
            for fail,expected in (('1',1),('0',0)):
                log=tmp/('events-'+fail)
                env=dict(os.environ,JLINK_SERIAL='fixture',LOG_DIR=str(tmp),CORE_LOG=str(log),FAIL_FIRST_VERIFY=fail)
                result=subprocess.run(['sh',str(loader),str(tmp/'core0.elf'),str(tmp/'core1.elf')],
                                      env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
                events=['load CR8-0','load CR8-1','verify CR8-0']
                if fail=='0':events.append('verify CR8-1')
                self.assertEqual(log.read_text().splitlines(),events)

    def test_manual_verify_stops_before_peer_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            loader = tmp / 'rzv2h-ipc-demo-load-both-manual.sh'
            loader.write_text((DEBUG / 'rzv2h-ipc' / loader.name).read_text())
            (tmp / LIB.name).write_text("""resolve_tools() { return 0; }
_stop_server() { return 0; }
verify_core() { echo "$3" >>"$CORE_LOG"; return 1; }
""")
            for name in ('rzv2h-ipc-hil-verify-resume.gdb', 'core0.elf', 'core1.elf'):
                (tmp / name).touch()
            log = tmp / 'events'
            result = subprocess.run(['sh', str(loader), 'verify', str(tmp / 'core0.elf'), str(tmp / 'core1.elf')],
                                    env=dict(os.environ, JLINK_SERIAL='fixture', LOG_DIR=directory, CORE_LOG=str(log)),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(log.read_text().splitlines(), ['CR8-0 (SCI4 console)'])

    def test_legacy_loader_delegates_exact_paths_to_guarded_loader(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            loader = tmp / 'rzv2h-ipc-demo-load-both.sh'
            loader.write_text((DEBUG / 'rzv2h-ipc' / loader.name).read_text())
            executable(tmp / 'rzv2h-ipc-demo-load-both-auto.sh',
                       '#!/bin/sh\nprintf "%s\\n" "$@" >"$ARG_LOG"\nexit 7\n')
            log = tmp / 'args'
            result = subprocess.run(['sh', str(loader), 'core 0.elf', 'core 1.elf'],
                                    env=dict(os.environ, ARG_LOG=str(log)), capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(log.read_text().splitlines(), ['core 0.elf', 'core 1.elf'])

    def test_loader_waits_for_target_connection_after_listener_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', """#!/usr/bin/env python3
import os,socket,sys,time
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen()
time.sleep(.4)
open(os.environ['READY_FILE'],'w').close()
print('Waiting for GDB connection...',flush=True)
time.sleep(60)
""")
            executable(tmp / 'gdb', '#!/bin/sh\n[ -f "$READY_FILE" ] || exit 7\necho SET_PC=0x40800000\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'),
                       JLINK_SERIAL='fixture', GDB_PORT=str(free_port()), LOG_DIR=directory,
                       LOADSTART='fixture', READY_FILE=str(tmp / 'ready'))
            result = subprocess.run(['sh', '-c', '. "$1"; trap _stop_server EXIT; resolve_tools; load_core dev elf core',
                                     'fixture', str(LIB)], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_loader_observes_buffered_c_server_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / 'server.c').write_text(r"""
#include <arpa/inet.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
int main(int argc,char **argv)
{
 int port=0;
 for(int i=1;i+1<argc;i++) if(strcmp(argv[i],"-port")==0) port=atoi(argv[i+1]);
 int fd=socket(AF_INET,SOCK_STREAM,0);
 struct sockaddr_in addr={.sin_family=AF_INET,.sin_addr.s_addr=htonl(INADDR_LOOPBACK),.sin_port=htons(port)};
 if(bind(fd,(void *)&addr,sizeof(addr))<0 || listen(fd,1)<0) return 2;
 /* Native stdio is fully buffered when redirected, including the failure
  * markers and the final readiness message without a trailing newline. */
 printf("Connected to target\nWaiting for GDB connection...");
 for(;;) pause();
}
""")
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(tmp / 'server.c'), '-o', str(tmp / 'server')], check=True)
            executable(tmp / 'gdb', '#!/bin/sh\necho "ENTRY=0x40800000 SET_PC=0x40800000 CPSR=0x1d3"\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'),
                       JLINK_SERIAL='fixture', GDB_PORT=str(free_port()), LOG_DIR=directory, LOADSTART='fixture')
            result = subprocess.run(['sh', '-c', '. "$1"; trap _stop_server EXIT; resolve_tools; load_core dev elf core',
                                     'fixture', str(LIB)], env=env, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_manual_rtt_requires_exact_elf_and_uses_managed_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            ipc = tmp / 'ipc'; ipc.mkdir()
            wrapper = ipc / 'rzv2h-ipc-demo-load-both-manual.sh'
            wrapper.write_text((DEBUG / 'rzv2h-ipc' / wrapper.name).read_text())
            (ipc / LIB.name).write_text('_stop_server() { return 0; }\n')
            executable(tmp / 'nuttx-rtt-bridge.sh', '#!/bin/sh\nprintf "%s\\n" "$@" >"$ARG_LOG"\n')
            elf = tmp / 'exact peer.elf'; elf.touch()
            env = dict(os.environ, JLINK_SERIAL='fixture', ARG_LOG=str(tmp / 'args'))
            missing = subprocess.run(['sh', str(wrapper), 'rtt'], env=env, capture_output=True)
            self.assertEqual(missing.returncode, 2)
            result = subprocess.run(['sh', str(wrapper), 'rtt', str(elf)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((tmp / 'args').read_text().splitlines(), ['start', 'cr8_1', str(elf)])

    def test_interactive_wrapper_preserves_paths_and_cleans_owned_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory); ipc = tmp / 'Debug/rzv2h-ipc'; ipc.mkdir(parents=True)
            (tmp / 'NuttX/nuttx').mkdir(parents=True)
            wrapper = ipc / 'rzv2h-ipc-demo-run.sh'
            wrapper.write_text((DEBUG / 'rzv2h-ipc' / wrapper.name).read_text())
            (ipc / LIB.name).write_text(LIB.read_text())
            executable(ipc / 'rzv2h-ipc-demo-load-both-auto.sh',
                       '#!/bin/sh\nprintf "%s\\n" "$@" >"$LOAD_ARGS"\n')
            executable(tmp / 'Debug/nuttx-rtt-bridge.sh', """#!/bin/sh
case "$1" in status) exit 1 ;; esac
printf '%s\\n' "$@" >>"$BRIDGE_ARGS"
""")
            bins = tmp / 'bin'; bins.mkdir()
            executable(bins / 'tmux', '#!/bin/sh\nexit 1\n')
            executable(bins / 'telnet', '#!/bin/sh\nexit 0\n')
            elf0 = tmp / 'exact core 0.elf'; elf0.touch()
            elf1 = tmp / 'exact core 1.elf'; elf1.touch()
            env = dict(os.environ, JLINK_SERIAL='fixture', PATH=str(bins)+':'+os.environ['PATH'],
                       LOAD_ARGS=str(tmp / 'loads'), BRIDGE_ARGS=str(tmp / 'bridge'))
            result = subprocess.run(['sh', str(wrapper), '--no-tmux', str(elf0), str(elf1)],
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual((tmp / 'loads').read_text().splitlines(), [str(elf0), str(elf1)])
            self.assertEqual((tmp / 'bridge').read_text().splitlines(), ['start', 'cr8_1', str(elf1), 'stop'])

    def test_preflight_distinguishes_compiler_from_truncated_gdb_name(self):
        spec=importlib.util.spec_from_file_location('preflight',DEBUG/'jlink-debug-preflight.py')
        preflight=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preflight)
        for executable in ('arm-none-eabi-gcc','arm-none-eabi-g++','python3','sleep'):
            self.assertFalse(preflight.probe_command(('/opt/bin/'+executable+'\0args').encode()))
        for executable in ('arm-none-eabi-gdb','gdb-multiarch','JLinkExe','JLinkGDBServerCLExe'):
            self.assertTrue(preflight.probe_command(('/opt/bin/'+executable+'\0args').encode()))

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
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();print('Waiting for GDB connection...',flush=True);time.sleep(60)
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
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();print('Waiting for GDB connection...',flush=True);time.sleep(60)
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

    def test_single_attempt_loader_stops_on_failure_or_reset(self):
        for gdb_result, marker, expected in (
                ('0', '', 0), ('1', '', 1),
                ('0', 'Resetting via Reset pin', 1),
                ('0', 'DBGEN is not asserted', 1),
                ('0', 'Connect failed', 1)):
            with self.subTest(gdb_result=gdb_result, marker=marker), \
                    tempfile.TemporaryDirectory() as directory:
                tmp = Path(directory)
                executable(tmp / 'server', '''#!/usr/bin/env python3
import json,os,socket,sys,time
with open(os.environ['ARG_LOG'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
print(os.environ['CONNECT_MARKER'],flush=True)
s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[sys.argv.index('-port')+1])));s.listen();print('Waiting for GDB connection...',flush=True);time.sleep(60)
''')
                executable(tmp / 'gdb', '#!/bin/sh\nprintf \"%s\\n\" \"$@\" >\"$GDB_ARGS\"\necho SET_PC=0x40800000\nexit \"$GDB_RESULT\"\n')
                env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'),
                           JLINK_SERIAL='fixture', GDB_PORT=str(free_port()), LOG_DIR=directory,
                           LOADSTART='fixture', GDB_RESULT=gdb_result, GDB_ARGS=str(tmp / 'gdb-args'),
                           CONNECT_MARKER=marker, ARG_LOG=str(tmp / 'arguments'))
                shell = '. "$1"; trap _stop_server EXIT; resolve_tools; load_core fixture fixture.elf test'
                result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                attempts = (tmp / 'arguments').read_text().splitlines()
                self.assertEqual(len(attempts), 1, result.stdout + result.stderr)
                self.assertIn('-noreset', attempts[0])
                self.assertIn('-noir', attempts[0])
                if not marker:
                    self.assertIn(f'target remote 127.0.0.1:{env["GDB_PORT"]}', (tmp / 'gdb-args').read_text())
                else:
                    self.assertFalse((tmp / 'gdb-args').exists(), 'GDB must not run after failed connect')

    def test_loader_rechecks_failures_after_readiness_observation(self):
        for marker in ('', 'DBGEN is not asserted', 'Resetting via Reset pin',
                       'Connect failed'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                tmp = Path(directory)
                executable(tmp / 'server', '#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n')
                executable(tmp / 'gdb', '#!/bin/sh\necho ran >"$GDB_ARGS"\necho SET_PC=0x40800000\n')
                env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB=str(tmp / 'gdb'),
                           JLINK_SERIAL='fixture', GDB_PORT='50000', LOG_DIR=directory,
                           LOADSTART='fixture', GDB_ARGS=str(tmp / 'gdb-args'),
                           CONNECT_MARKER=marker)
                # Append failure and readiness between the initial failure
                # scan and the readiness check. No listening socket or probe.
                shell = r'''
. "$1"
trap _stop_server EXIT
resolve_tools
preflight_probe_free() { return 0; }
_server_owns_port() {
    printf '%s\n' "$CONNECT_MARKER" 'Waiting for GDB connection...' >>"$log"
    return 0
}
load_core fixture fixture.elf test
'''
                result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, int(bool(marker)),
                                 result.stdout + result.stderr)
                self.assertEqual((tmp / 'gdb-args').exists(), not bool(marker),
                                 'GDB must not run after a failure before readiness')

    def test_invalid_loader_attempt_limit_is_rejected_before_probe_access(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            executable(tmp / 'server', '#!/bin/sh\necho touched >>"$PROBE_LOG"\nexit 1\n')
            env = dict(os.environ, JLINK_GDB=str(tmp / 'server'), GDB='/bin/false',
                       JLINK_SERIAL='fixture', GDB_PORT=str(free_port()), LOG_DIR=directory,
                       LOADSTART='fixture', LOAD_ATTEMPTS='0', PROBE_LOG=str(tmp / 'probe'))
            shell = '. "$1"; trap _stop_server EXIT; resolve_tools; load_core fixture fixture.elf test'
            result = subprocess.run(['sh', '-c', shell, 'fixture', str(LIB)], env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse((tmp / 'probe').exists())

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
