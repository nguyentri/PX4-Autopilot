#!/usr/bin/env python3
"""Host regressions for receipt, admission, ownership and recovery boundaries."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Tools'))
from firmware_workspace import artifacts, build, console, debug, load, sessions
from firmware_workspace.artifacts import compute_sha256
from firmware_workspace.catalog import group_fingerprint, load_groups, resolve_selection
from firmware_workspace.locks import BuildLock, inherited_fds, process_start
from firmware_workspace.probe import ProbeLease, probe_directory
from firmware_workspace.target_state import TargetState
from firmware_workspace.verification import OperationError, admitted_inputs


class OperationFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='firmware-regression-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'FIRMWARE_WORKSPACE_RUNTIME': str(self.root / 'runtime')})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.selection = {'schemaVersion': 1, 'id': 'simple', 'board': 'rdk-rzv2h', 'core': 'cr8_0',
                          'build': {'family': 'px4', 'target': 'renesas_rdk-rzv2h_default', 'mode': 'incremental'},
                          'load': {'recipe': 'rzv-cr8-ram'}, 'debug': {'mode': 'attach'}}
        self.image = self.root / 'firmware image.elf'
        self.image.write_bytes(b'fixture deliberately not an ARM ELF')
        self.receipt = {'schemaVersion': 1, 'receiptId': 'receipt', 'timestamp': '2026-10-25T00:00:00Z',
                        'family': 'px4', 'board': 'rdk-rzv2h', 'core': 'cr8_0', 'selectionId': 'simple',
                        'target': self.selection['build']['target'], 'config': None, 'group': None,
                        'gitRevision': 'fixture', 'gitDirty': True, 'compiler': 'fixture', 'status': 'committed',
                        'artifacts': [{'path': str(self.image), 'sha256': compute_sha256(self.image),
                                       'size': self.image.stat().st_size, 'core': 'cr8_0', 'rttAddress': '0x081a2400'}]}
        self.args = SimpleNamespace(selection=str(self.root / 'selection.json'), receipt=str(self.root / 'receipt.json'),
                                    serial='host-fixture', core=None, json=True, recover=False, action='start')
        self.write_inputs()

    def write_inputs(self):
        Path(self.args.selection).write_text(json.dumps(self.selection))
        Path(self.args.receipt).write_text(json.dumps(self.receipt))

    def invoke(self, command):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = command(self.args)
        return code, json.loads(output.getvalue())

    def test_non_elf_rejected_by_real_canonical_checker_before_loader(self):
        # Canonical checker is host-only; no J-Link process is substituted or started.
        with patch.object(load, 'require_probe_available') as probe:
            code, result = self.invoke(load.cmd_load)
        self.assertEqual(code, 2)
        self.assertEqual(result['diagnostics'][0]['code'], 'ALLOWLIST_VIOLATION')
        probe.assert_not_called()

    def test_missing_checker_fails_closed(self):
        with patch.object(load, 'ALLOWLIST_SCRIPT', self.root / 'missing.py'), patch.object(load, 'ManagedProcess') as child:
            with self.assertRaises(OperationError):
                load.check_rz_allowlist(self.image, 'R9A09G057H44_R8_0', compute_sha256(self.image))
            child.assert_not_called()

    def test_checker_receives_exact_device_and_digest(self):
        with patch.object(load, 'ManagedProcess') as child:
            child.return_value.run.return_value = (0, 'RESULT=ADDRESS_CONTRACT_VERIFIED', '')
            load.check_rz_allowlist(self.image, 'R9A09G057H44_R8_1', compute_sha256(self.image))
            argv = child.call_args.args[0]
            self.assertEqual(Path(argv[1]), ROOT / 'platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py')
            self.assertEqual(argv[2:], ['--elf', str(self.image), '--device', 'R9A09G057H44_R8_1', '--expect-sha256', compute_sha256(self.image)])

    def test_loader_consumes_the_exact_private_admitted_snapshot(self):
        admitted = []
        digest = self.receipt['artifacts'][0]['sha256']
        def admit(snapshot, device, expected):
            self.assertEqual(compute_sha256(snapshot), expected)
            admitted.append(snapshot)
            self.image.write_bytes(b'original output replaced after admission')
        class LoaderChild:
            def __init__(child, argv, **kwargs):
                self.assertEqual(Path(argv[-1]), admitted[0])
                self.assertNotEqual(Path(argv[-1]), self.image)
                self.assertEqual(compute_sha256(Path(argv[-1])), digest)
            def run(child, **kwargs):
                return 0, '', ''
        with patch.object(load, 'check_rz_allowlist', side_effect=admit), patch.object(load, 'require_probe_available'), patch.object(load, 'ManagedProcess', LoaderChild):
            self.assertEqual(self.invoke(load.cmd_load)[0], 0)
        self.assertFalse(admitted[0].exists(), 'private load snapshot must be cleaned after consumption')

    def test_receipt_identity_and_commit_required_for_every_consumer(self):
        for field, value in [('status', 'provisional'), ('board', 'evk-ra8p1'), ('core', 'cm85'),
                             ('selectionId', 'other'), ('target', 'other'), ('family', 'nuttx'), ('group', 'other')]:
            original = self.receipt[field]
            self.receipt[field] = value
            self.write_inputs()
            for operation in ('load', 'debug', 'console'):
                with self.subTest(field=field, operation=operation), self.assertRaises(OperationError):
                    admitted_inputs(self.args, operation)
            self.receipt[field] = original

    def test_modified_artifact_rejected_by_all_consumers(self):
        self.image.write_bytes(b'changed')
        for operation in ('load', 'debug', 'console'):
            with self.subTest(operation=operation), self.assertRaisesRegex(OperationError, 'changed'):
                admitted_inputs(self.args, operation)

    def test_debug_missing_core_has_no_symbol_fallback(self):
        self.args.core = 'cr8_1'
        code, result = self.invoke(debug.cmd_debug_config)
        self.assertEqual(code, 2)
        self.assertEqual(result['diagnostics'][0]['code'], 'RECEIPT_CORE_MISMATCH')

    def test_group_receipt_detects_definition_change_and_duplicate_core(self):
        self.selection.update(core='multicore', group='rzv-px4-dualcr8', id='rzv-px4-dualcr8')
        self.selection['build'].pop('target')
        self.receipt.update(core='multicore', group='rzv-px4-dualcr8', selectionId='rzv-px4-dualcr8', target=None)
        self.receipt['groupDefinitionSha256'] = group_fingerprint(load_groups()['groups']['rzv-px4-dualcr8'])
        self.receipt['artifacts'].append(dict(self.receipt['artifacts'][0], core='cr8_1'))
        self.write_inputs()
        admitted_inputs(self.args, 'load')
        self.receipt['groupDefinitionSha256'] = '0' * 64
        self.write_inputs()
        with self.assertRaisesRegex(OperationError, 'Group definition'):
            admitted_inputs(self.args, 'load')
        self.receipt['groupDefinitionSha256'] = group_fingerprint(load_groups()['groups']['rzv-px4-dualcr8'])
        self.receipt['artifacts'][1]['core'] = 'cr8_0'
        self.write_inputs()
        with self.assertRaisesRegex(OperationError, 'duplicated'):
            admitted_inputs(self.args, 'load')

    def test_debug_symbols_are_immutable_snapshot(self):
        with patch('firmware_workspace.verification.ARTIFACTS_ROOT', self.root):
            code, result = self.invoke(debug.cmd_debug_config)
        self.assertEqual(code, 0)
        snapshot = Path(result['data']['configuration']['executable'])
        self.assertNotEqual(snapshot, self.image)
        self.image.write_bytes(b'selection output changed')
        self.assertEqual(compute_sha256(snapshot), self.receipt['artifacts'][0]['sha256'])
        self.assertEqual(snapshot.stat().st_mode & 0o222, 0)

    def test_leased_debug_uses_owned_server_wrapper_and_selected_python(self):
        with patch('firmware_workspace.verification.ARTIFACTS_ROOT', self.root), \
             patch.object(debug, 'check_tool', return_value='/fixture path/JLinkGDBServer'), \
             ProbeLease(self.args.serial) as lease:
            code, result = self.invoke(debug.cmd_debug_config)
            self.assertEqual(code, 0)
            config = result['data']['configuration']
            self.assertEqual(config['serverpath'], str(ROOT / 'Tools/firmware_workspace/jlink-server.sh'))
            self.assertIn('--firmware-lease=' + lease.token, config['serverArgs'])
            self.assertIn('--firmware-core=cr8_0', config['serverArgs'])
            self.assertIn('--firmware-python=' + sys.executable, config['serverArgs'])

    def test_failed_load_requires_explicit_recovery_and_other_probe_is_independent(self):
        with patch.object(load, 'check_rz_allowlist'), patch.object(load, 'require_probe_available'), patch.object(load, 'ManagedProcess') as child:
            child.return_value.run.return_value = (1, '', 'simulated load failure')
            self.assertEqual(self.invoke(load.cmd_load)[0], 1)
            child.reset_mock()
            code, result = self.invoke(load.cmd_load)
            self.assertEqual(code, 3)
            self.assertTrue(result['data']['recoveryRequired'])
            child.assert_not_called()
            state = TargetState(probe_directory(self.args.serial) / 'target-state.json')
            with self.assertRaises(OperationError):
                state.require_ready(['cr8_1'])  # A failed connect can reset sibling images too.
            TargetState(probe_directory('another-probe') / 'target-state.json').require_ready(['cr8_0'])
            self.args.recover = True
            child.return_value.run.return_value = (0, '', '')
            self.assertEqual(self.invoke(load.cmd_load)[0], 0)
            self.assertEqual(TargetState(state.path).value['cores']['cr8_0']['state'], 'verified')

    def test_interrupted_started_journal_blocks_other_core(self):
        state = TargetState(probe_directory(self.args.serial) / 'target-state.json')
        state.record(['cr8_0'], 'started', 'receipt')
        with self.assertRaises(OperationError):
            TargetState(state.path).require_ready(['cr8_1'])

    def test_console_receives_serial_as_environment_and_concrete_core(self):
        self.args.core = 'cr8_0'
        with patch.object(console, 'require_probe_available'), patch.object(console, 'debug_snapshot', return_value=self.image), patch.object(console, 'ManagedProcess') as child:
            child.return_value.run.return_value = (0, '', '')
            with ProbeLease(self.args.serial) as lease:
                data = console.start_owned_console(self.args, self.args.serial, lease.token)
                call = child.call_args
                self.assertEqual(call.args[0][1:3], ['start', 'cr8_0'])
                self.assertEqual(call.kwargs['env']['JLINK_SERIAL'], self.args.serial)
                self.assertNotIn(self.args.serial, call.args[0])
                self.assertTrue(data['running'])
                self.assertEqual(call.kwargs['env']['RTT_PORT'], '19021')
                self.assertEqual(data['endpoint'], '127.0.0.1:19021')
                console.stop_owned_console(self.args.serial, lease.token)

    def test_console_endpoint_follows_configured_port_and_status_reports_it(self):
        self.args.core = 'cr8_0'
        with patch.dict(os.environ, {'FIRMWARE_RTT_PORT': '19031'}), patch.object(console, 'require_probe_available'), \
                patch.object(console, 'debug_snapshot', return_value=self.image), patch.object(console, 'ManagedProcess') as child:
            child.return_value.run.return_value = (0, '', '')
            with ProbeLease(self.args.serial) as lease:
                data = console.start_owned_console(self.args, self.args.serial, lease.token)
                self.assertEqual(child.call_args.kwargs['env']['RTT_PORT'], '19031')
                self.assertEqual(data['endpoint'], '127.0.0.1:19031')
                status_args = SimpleNamespace(action='status', serial=self.args.serial)
                with patch.object(console, 'bridge_running', return_value=True), patch('builtins.print') as shown:
                    self.assertEqual(console.cmd_console(status_args), 0)
                status = json.loads(shown.call_args.args[0])['data']
                self.assertEqual((status['core'], status['endpoint']), ('cr8_0', '127.0.0.1:19031'))
                console.stop_owned_console(self.args.serial, lease.token)
        with patch.dict(os.environ, {'FIRMWARE_RTT_PORT': 'x'}):
            with self.assertRaises(OperationError):
                console.rtt_port()

    def dual_inputs(self, console_map):
        selection = dict(self.selection, core='multicore', group='rzv-px4-demo')
        resolved = {'groupMeta': {'console': console_map}}
        artifacts = {core: {'path': str(self.image), 'core': core} for core in ('cr8_0', 'cr8_1')}
        return selection, resolved, {'receiptId': 'receipt'}, artifacts

    def test_dual_console_serves_both_cores_from_one_bridge(self):
        self.args.dual = True
        with patch.object(console, 'admitted_inputs', return_value=self.dual_inputs({'cr8_0': 'rtt', 'cr8_1': 'rtt'})), \
                patch.object(console, 'require_probe_available'), patch.object(console, 'debug_snapshot', return_value=self.image), \
                patch.object(console, 'ManagedProcess') as child:
            child.return_value.run.return_value = (0, '', '')
            with ProbeLease(self.args.serial) as lease:
                data = console.start_owned_console(self.args, self.args.serial, lease.token)
                argv, env = child.call_args.args[0], child.call_args.kwargs['env']
                self.assertEqual(Path(argv[1]), ROOT / 'platforms/nuttx/Debug/rzv2h-dual-rtt-bridge.py')
                self.assertEqual(argv[2:], ['start', str(self.image), str(self.image)])
                self.assertEqual((env['RTT_PORT_CR8_0'], env['RTT_PORT_CR8_1']), ('19021', '19031'))
                self.assertEqual(data['endpoints'], {'cr8_0': '127.0.0.1:19021', 'cr8_1': '127.0.0.1:19031'})
                self.assertEqual(data['mode'], 'dual')
                status_args = SimpleNamespace(action='status', serial=self.args.serial)
                with patch.object(console, 'bridge_running', return_value=True), patch('builtins.print') as shown:
                    self.assertEqual(console.cmd_console(status_args), 0)
                status = json.loads(shown.call_args.args[0])['data']
                self.assertEqual((status['mode'], status['endpoints']['cr8_1']), ('dual', '127.0.0.1:19031'))
                child.reset_mock()
                console.stop_owned_console(self.args.serial, lease.token)
                self.assertEqual(child.call_args.args[0][1:], [str(ROOT / 'platforms/nuttx/Debug/rzv2h-dual-rtt-bridge.py'), 'stop'])

    def test_dual_console_requires_rtt_on_both_cores(self):
        self.args.dual = True
        with patch.object(console, 'admitted_inputs', return_value=self.dual_inputs({'cr8_0': 'rtt', 'cr8_1': 'serial'})), \
                patch.object(console, 'ManagedProcess') as child, ProbeLease(self.args.serial) as lease:
            with self.assertRaisesRegex(OperationError, 'UART'):
                console.start_owned_console(self.args, self.args.serial, lease.token)
            child.assert_not_called()
        with patch.dict(os.environ, {'FIRMWARE_RTT_PORT_CR8_1': '19021'}), \
                patch.object(console, 'admitted_inputs', return_value=self.dual_inputs({'cr8_0': 'rtt', 'cr8_1': 'rtt'})), \
                patch.object(console, 'require_probe_available'), patch.object(console, 'ManagedProcess') as child, \
                ProbeLease(self.args.serial) as lease:
            with self.assertRaisesRegex(OperationError, 'differ'):
                console.start_owned_console(self.args, self.args.serial, lease.token)
            child.assert_not_called()

    def test_uart_console_reports_unsupported_without_starting_rtt(self):
        self.selection['build'] = {'family': 'nuttx', 'config': 'nsh-scif', 'mode': 'incremental'}
        self.receipt.update(family='nuttx', config='nsh-scif', target=None)
        self.write_inputs()
        with patch.object(console, 'ManagedProcess') as child, ProbeLease(self.args.serial) as lease:
            with self.assertRaisesRegex(OperationError, 'UART'):
                console.start_owned_console(self.args, self.args.serial, lease.token)
            child.assert_not_called()

    def test_console_stop_failure_keeps_ownership_record(self):
        from firmware_workspace.target_state import atomic_json
        path = probe_directory(self.args.serial) / 'console.json'
        atomic_json(path, {'root': str(ROOT.resolve()), 'token': 'owned', 'pid': os.getpid(), 'detached': False})
        with patch.object(console, 'ManagedProcess') as child:
            child.return_value.run.return_value = (1, '', 'busy')
            with self.assertRaises(OperationError):
                console.stop_owned_console(self.args.serial, 'owned')
        self.assertTrue(path.exists())

    def test_build_only_selection_does_not_gate_on_saved_debug(self):
        selection = {'schemaVersion': 1, 'id': 'ra8', 'board': 'fpb-ra8e1', 'core': 'cm85',
                     'build': {'family': 'px4', 'target': 'renesas_fpb-ra8e1_default', 'mode': 'incremental'},
                     'debug': {'mode': 'attach'}}
        self.assertIsNotNone(resolve_selection(selection, operation='build')[0])
        self.assertIsNone(resolve_selection(selection, operation='debug')[0])

    def test_build_and_clean_do_not_start_probe_or_target_operations(self):
        """Saved load/debug settings never make a build acquire target hardware."""
        self.selection['debug'] = {'mode': 'load-and-debug'}
        self.write_inputs()
        output = self.root / 'build' / self.selection['build']['target'] / (self.selection['build']['target'] + '.elf')
        calls = []

        class BuildChild:
            def __init__(child, argv, **kwargs):
                calls.append(argv)

            def run(child, **kwargs):
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b'host build fixture')
                return 0, '', ''

        with patch.dict(os.environ, {'FIRMWARE_BUILD_LOCK_PATH': str(self.root / 'build.lock')}), \
             patch.object(build, 'REPO_ROOT', self.root), patch.object(artifacts, 'REPO_ROOT', self.root), \
             patch.object(artifacts, 'ARTIFACTS_ROOT', self.root / 'build/workspace-artifacts'), \
             patch.object(artifacts, 'get_git_info', return_value={'revision': 'fixture', 'dirty': False}), \
             patch.object(build, 'ManagedProcess', BuildChild), \
             patch.object(ProbeLease, 'acquire') as acquire, patch.object(load, 'cmd_load') as load_target, \
             patch.object(debug, 'cmd_debug_config') as attach, patch.object(console, 'start_owned_console') as start_console:
            for clean in (False, True):
                with self.subTest(clean=clean):
                    self.args.clean = clean
                    code, result = self.invoke(build.cmd_build)
                    self.assertEqual(code, 0)
                    self.assertEqual(result['status'], 'ok')
                    self.assertEqual(calls[-1], [str(self.root / 'build.sh')]
                                     + ([] if clean else ['--no-clean']) + [self.selection['build']['target']])
                    acquire.assert_not_called()
                    load_target.assert_not_called()
                    attach.assert_not_called()
                    start_console.assert_not_called()

    def test_group_build_stages_before_switch_and_clean_override_is_immutable(self):
        self.selection.update(core='multicore', group='rzv-native-ipc-rtt', id='rzv-native-ipc-rtt')
        self.selection['build'] = {'family': 'nuttx', 'mode': 'incremental'}
        self.selection.pop('load')
        self.write_inputs()
        before = Path(self.args.selection).read_bytes()
        self.args.clean = True
        common = self.root / 'platforms/nuttx/NuttX/nuttx/nuttx'
        calls = []
        class BuildChild:
            def __init__(child, argv, **kwargs):
                child.argv = argv
            def run(child, **kwargs):
                self.assertTrue(BuildLock().inherited())
                calls.append(child.argv)
                common.parent.mkdir(parents=True, exist_ok=True)
                common.write_text(child.argv[-1])
                return 0, '', ''
        with patch.dict(os.environ, {'FIRMWARE_BUILD_LOCK_PATH': str(self.root / 'build.lock')}), \
             patch.object(build, 'REPO_ROOT', self.root), patch.object(artifacts, 'REPO_ROOT', self.root), \
             patch.object(artifacts, 'ARTIFACTS_ROOT', self.root / 'build/workspace-artifacts'), \
             patch.object(artifacts, 'get_git_info', return_value={'revision': 'fixture', 'dirty': False}), \
             patch.object(build, 'ManagedProcess', BuildChild):
            code, result = self.invoke(build.cmd_build)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all('--no-clean' not in argv for argv in calls))
        receipt = json.loads((self.root / result['receiptPath']).read_text())
        self.assertEqual(receipt['status'], 'committed')
        outputs = {item['core']: (self.root / item['path']).read_text() for item in receipt['artifacts']}
        self.assertEqual(outputs, {'cr8_0': 'ipcc-raw-cr8_0', 'cr8_1': 'ipcc-raw-cr8_1'})
        self.assertEqual(Path(self.args.selection).read_bytes(), before)

    def test_failed_group_never_publishes_complete_receipt(self):
        self.selection.update(core='multicore', group='rzv-native-ipc-rtt', id='rzv-native-ipc-rtt')
        self.selection['build'] = {'family': 'nuttx', 'mode': 'incremental'}
        self.selection.pop('load')
        self.write_inputs()
        with patch.dict(os.environ, {'FIRMWARE_BUILD_LOCK_PATH': str(self.root / 'build.lock')}), \
             patch.object(build, 'build_single_target', side_effect=[(0, [{'core': 'cr8_0'}], ''), (1, [], 'failed')]), \
             patch.object(build, 'create_receipt') as publish:
            self.assertEqual(self.invoke(build.cmd_build)[0], 1)
        publish.assert_not_called()

    def test_low_priority_build_runs_under_nice(self):
        commands = []

        class Recorder:
            def __init__(self, cmd, cwd=None):
                commands.append(cmd)

            def run(self, stream_stderr=False):
                return 1, '', 'stop here'

        with patch.object(build, 'ManagedProcess', Recorder):
            build.build_single_target('px4', 'rdk-rzv2h', 'cr8_0', 'renesas_rdk-rzv2h_default', 'incremental', 'run', low_priority=True)
            build.build_single_target('px4', 'rdk-rzv2h', 'cr8_0', 'renesas_rdk-rzv2h_default', 'incremental', 'run')
        self.assertEqual(commands[0][:3], ['nice', '-n', '19'])
        self.assertEqual(commands[0][3:], commands[1])


class OwnershipTests(unittest.TestCase):
    def test_supervisor_reaps_server_even_if_adapter_kills_wrapper(self):
        with tempfile.TemporaryDirectory(prefix='server ownership ') as directory, patch.dict(os.environ, {'FIRMWARE_WORKSPACE_RUNTIME': directory}):
            server = Path(directory) / 'JLinkGDBServer'
            server.write_text('#!' + sys.executable + '\nimport os,time\nprint(os.getpid(),flush=True)\ntime.sleep(30)\n')
            server.chmod(0o700)
            child = None
            server_pid = None
            try:
                with ProbeLease('fixture') as lease:
                    argv = [str(ROOT / 'Tools/firmware_workspace/jlink-server.sh'),
                            '--firmware-python=' + sys.executable, '--firmware-lease=' + lease.token,
                            '--firmware-serial=fixture', '--firmware-core=cr8_0', '--firmware-server=' + str(server), '-port', '50000']
                    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    ready, _, _ = select.select([child.stdout], [], [], 10)
                    self.assertTrue(ready)
                    server_pid = int(child.stdout.readline())
                    self.assertIsNotNone(process_start(server_pid))
                    child.kill()  # Emulate a debug adapter/extension-host crash.
                    child.wait(timeout=5)
                stat = Path(f'/proc/{server_pid}/stat')
                self.assertTrue(not stat.exists() or stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z')
                with self.assertRaises(OperationError):
                    TargetState(probe_directory('fixture') / 'target-state.json').require_ready(['cr8_1'])
            finally:
                if child:
                    if child.poll() is None:
                        child.terminate()
                        child.wait(timeout=10)
                    child.stdout.close()
                    child.stderr.close()
                if server_pid:
                    try:
                        os.kill(server_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_build_lock_token_without_descriptor_cannot_bypass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'build.lock'
            with BuildLock(path) as lock:
                env = os.environ.copy()
                env['PYTHONPATH'] = str(ROOT / 'Tools')
                command = [sys.executable, '-c', 'from firmware_workspace.locks import BuildLock; import sys; sys.exit(0 if BuildLock(sys.argv[1]).inherited() else 1)', str(path)]
                self.assertEqual(subprocess.run(command, env=env).returncode, 1)
                self.assertEqual(subprocess.run(command, env=env, pass_fds=inherited_fds()).returncode, 0)
                del env['FIRMWARE_BUILD_LOCK_FD']
                self.assertEqual(subprocess.run(command, env=env).returncode, 1)

    def test_direct_make_renesas_recipe_enters_shared_lock(self):
        # Exercise the actual wrapper macro with a harmless recipe, never firmware tools.
        text = (ROOT / 'Makefile').read_text()
        macro = 'define cmake-build\n' + text.split('define cmake-build\n', 1)[1].split('\nendef', 1)[0] + '\nendef\n'
        with tempfile.TemporaryDirectory(prefix='make-lock-') as directory:
            fixture = Path(directory) / 'Makefile'
            check = Path(directory) / 'assert_lock.py'
            check.write_text('from firmware_workspace.locks import BuildLock\nassert BuildLock().inherited()\nprint("LOCKED")\n')
            fixture.write_text(f'SRC_DIR := {ROOT}\nARGS :=\n' + macro + f'\ndefine cmake-build-unlocked\n\t@PYTHONPATH="{ROOT / "Tools"}" python3 "{check}"\nendef\nrenesas_fixture:\n\t$(call cmake-build,renesas_fixture)\n')
            env = dict(os.environ, FIRMWARE_BUILD_LOCK_PATH=str(Path(directory) / 'lock'))
            run = subprocess.run(['make', '-f', str(fixture), f'MAKE=make -f {fixture}', 'renesas_fixture'], env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr + run.stdout)
            self.assertIn('LOCKED', run.stdout)

    def test_probe_lease_excludes_second_owner_and_releases(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'FIRMWARE_WORKSPACE_RUNTIME': directory}):
            with ProbeLease('fixture'):
                env = os.environ.copy()
                for name in ('FIRMWARE_PROBE_LEASE', 'FIRMWARE_PROBE_SERIAL', 'FIRMWARE_PROBE_LOCK_FD'):
                    env.pop(name, None)
                env['PYTHONPATH'] = str(ROOT / 'Tools')
                script = 'from firmware_workspace.probe import ProbeLease\nfrom firmware_workspace.verification import OperationError\ntry:\n with ProbeLease("fixture"): pass\nexcept OperationError: raise SystemExit(3)'
                self.assertEqual(subprocess.run([sys.executable, '-c', script], env=env).returncode, 3)
            self.assertEqual(subprocess.run([sys.executable, '-c', script], env=env).returncode, 0)

    def test_probe_supervisor_holds_until_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'Tools'), FIRMWARE_WORKSPACE_RUNTIME=directory)
            script = 'from firmware_workspace import sessions\nfrom types import SimpleNamespace\nsessions.require_probe_available=lambda serial: None\nraise SystemExit(sessions.cmd_probe_session(SimpleNamespace(serial="fixture",console_start=False)))'
            child = subprocess.Popen([sys.executable, '-u', '-c', script], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                ready, _, _ = select.select([child.stdout], [], [], 10)
                self.assertTrue(ready)
                message = json.loads(child.stdout.readline())
                self.assertEqual(message['status'], 'ok')
                self.assertIsNone(child.poll())
                child.stdin.write(json.dumps({'event': 'debug-failed', 'core': 'cr8_0'}) + '\n')
                child.stdin.flush()
                child.stdin.close()
                self.assertEqual(child.wait(timeout=10), 0, child.stderr.read())
                with patch.dict(os.environ, {'FIRMWARE_WORKSPACE_RUNTIME': directory}):
                    with self.assertRaises(OperationError):
                        TargetState(probe_directory('fixture') / 'target-state.json').require_ready(['cr8_1'])
                    with ProbeLease('fixture'):
                        pass
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=10)
                child.stdout.close()
                child.stderr.close()


if __name__ == '__main__':
    unittest.main()
