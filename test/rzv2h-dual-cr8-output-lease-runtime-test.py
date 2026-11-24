#!/usr/bin/env python3
"""Dual-CR8 output safety: CR8-0 link recovery, the CR8-1 epoch query, and
the build guards that keep remote outputs out of single-core images."""

import importlib.util
import re
import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / 'boards/renesas'
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
SPEC = importlib.util.spec_from_file_location('expanded', ROOT / 'test/rzv2h-expanded-remediation-runtime-test.py')
EXPANDED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXPANDED)
REPAIR = EXPANDED.REPAIR
extract = REPAIR.extract

PROTOCOLS = (BOARDS / 'rdk-rzv2h/rzv2h_outputs/protocol.h',
             BOARDS / 'rdk-rzv2h-io-cr8_1/rzv2h_io/protocol.h',
             BOARDS / 'rdk-rzv2h-io-cm33/px4io_m33/protocol.h')


class DualCr8OutputLease(unittest.TestCase):
    def test_epoch_snapshot_does_not_wait_behind_a_blocked_writer(self):
        source = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw_chardev.c').read_text()
        body = extract(source, 'static int rzv_raw_ioctl(')
        stats = body[body.index('case RZV_IPC_RAWIOC_GET_STATS'):body.index('case RZV_IPC_RAWIOC_RECOVER')]
        self.assertIn('nxmutex_lock(&priv->rxlock)', stats)
        self.assertIn('nxmutex_unlock(&priv->rxlock)', stats)
        self.assertNotIn('&priv->lock', stats)

    def test_poll_does_not_wait_behind_a_blocked_writer(self):
        # The writer keeps priv->lock across its ACK wait.  A poller queued on
        # it cannot consume the peer's frame, so two cores writing at once
        # wait for each other until both writes time out.
        source = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw.c').read_text()
        write = extract(source, 'ssize_t rzv_ipc_raw_write(')
        self.assertLess(write.index('nxmutex_lock(&priv->lock)'), write.index('nxsem_tickwait_uninterruptible(&priv->acksem'))
        chardev = (NUTTX / 'arch/arm/src/rzv/rzv_ipc_raw_chardev.c').read_text()
        poll = extract(chardev, 'static int rzv_raw_poll(')
        self.assertIn('nxmutex_lock(&priv->rxlock)', poll)
        self.assertEqual(poll.count('nxmutex_lock('), 1)
        self.assertEqual(poll.count('nxmutex_unlock(&priv->rxlock)'), poll.count('nxmutex_unlock('))
        self.assertNotIn('&priv->lock', poll)

    def test_dual_cr8_selects_the_supervised_output_producer(self):
        board = BOARDS / 'rdk-rzv2h'
        self.assertNotIn('PX4IO_BRIDGE', (board / 'Kconfig').read_text())
        # Heartbeat-only profiles own the CR8 link for rzv2h_heartbeat liveness
        # and ping/say text; they must carry no output producer of any kind.
        # The single-core demo has no CR8 link at all.
        board_cmake = (board / 'src/CMakeLists.txt').read_text()
        heartbeat_only = set(re.findall(
            r'if\(PX4_BOARD_LABEL STREQUAL "(\w+)"\)(?:(?!\nendif\(\)).)*?add_subdirectory\([^)]*ipc_heartbeat',
            board_cmake, re.S))
        self.assertEqual(heartbeat_only, {'demosih'})
        for profile in sorted(board.glob('*.px4board')):
            label = profile.stem
            config = board / 'nuttx-config' / label / 'defconfig'
            nuttx = (config if config.exists() else board / 'nuttx-config/nsh/defconfig').read_text()
            has_link = re.search(r'(?m)^CONFIG_RZV_IPC_CR8_CR8=y', nuttx) is not None
            remote = 'CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS=y' in profile.read_text()
            if label in heartbeat_only:
                self.assertTrue(has_link, label)
                self.assertFalse(remote, label)
            else:
                self.assertEqual(remote, has_link, label)
        self.assertIn('CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS=y', (board / 'dualcr8.px4board').read_text())

    def test_profiles_only_set_board_options_kconfig_can_apply(self):
        # Options inside 'if BOARD_RDK_RZV2H' are forced off unless a profile
        # selects the board symbol; setting them otherwise is silently ignored.
        board = BOARDS / 'rdk-rzv2h'
        kconfig = (board / 'Kconfig').read_text()
        guarded = kconfig[kconfig.index('if BOARD_RDK_RZV2H\n'):kconfig.index('endif # BOARD_RDK_RZV2H')]
        hidden = set(re.findall(r'(?m)^config (\w+)', guarded))
        self.assertIn('BOARD_RDK_RZV2H_HAS_IMU', hidden)
        for profile in sorted(board.glob('*.px4board')):
            text = profile.read_text()
            if re.search(r'(?m)^CONFIG_BOARD_RDK_RZV2H=y$', text):
                continue
            for option in hidden:
                self.assertNotRegex(text, rf'(?m)^CONFIG_{option}=', profile.stem)

    def test_px4_kconfig_resolves_remote_ownership(self):
        # A board option that PX4 Kconfig never parses is silently dropped.
        probe = r"""
import os, sys, kconfiglib
board = 'boards/renesas/rdk-rzv2h/'
for model, label in [(m, l) for m, l in (a.split(':') for a in sys.argv[1:])]:
    os.environ.update(VENDOR='renesas', MODEL=model, LABEL=label, PLATFORM='nuttx')
    k = kconfiglib.Kconfig('Kconfig', warn=False)
    if model == 'rdk-rzv2h':
        k.load_config(board + 'default.px4board')
        k.load_config(board + label + '.px4board', replace=False)
    print(model, label, k.syms['BOARD_RDK_RZV2H_REMOTE_OUTPUTS'].str_value)
"""
        labels = sorted(p.stem for p in (BOARDS / 'rdk-rzv2h').glob('*.px4board'))
        args = ['rdk-rzv2h:' + label for label in labels] + ['rdk-rzv2h-io-cr8_1:default']
        result = subprocess.run(['python3', '-c', probe] + args, cwd=ROOT, capture_output=True, text=True)
        if 'No module named' in result.stderr:
            self.skipTest('kconfiglib is not installed')
        self.assertEqual(result.returncode, 0, result.stderr)
        resolved = dict((' '.join(line.split()[:2]), line.split()[2]) for line in result.stdout.splitlines())
        expected = {f'rdk-rzv2h {label}': 'y' if label == 'dualcr8' else 'n' for label in labels}
        expected['rdk-rzv2h-io-cr8_1 default'] = 'n'
        self.assertEqual(resolved, expected)

    def test_dual_cr8_registers_link_and_no_legacy_bridge_starts(self):
        board = BOARDS / 'rdk-rzv2h'
        cmake = (board / 'src/CMakeLists.txt').read_text()
        self.assertRegex(cmake, r'if\(CONFIG_RZV_IPC_RAW\)\n\tlist\(APPEND drivers_board_sources\n'
                                r'\t\t\S+/rdk-rzv2h/src/rzv2h_ipc\.c\n')
        init = (board / 'src/init.c').read_text()
        self.assertRegex(init, r'#ifdef CONFIG_RZV_IPC_RAW\n(?:[/ ]\*.*\n)*#  ifdef CONFIG_RZV_OPENAMP\n#    error')
        app = extract(init, '__EXPORT int board_app_initialize(')
        raw = app[app.index('#if defined(CONFIG_RZV_IPC_RAW)'):]
        self.assertIn('ret = board_ipc_initialize();', raw[:raw.index('#endif')])
        self.assertIn('CONFIG_BOARD_INIT_SUBDIR="dualcr8"', (board / 'dualcr8.px4board').read_text())

        # The legacy CR8-0 bridge is retired: no startup hook may launch it.
        for script in board.glob('init/**/rc.board_extras'):
            self.assertNotIn('px4io_bridge', script.read_text(), script)

    def test_every_core_shares_the_lease_and_safe_fault_contract(self):
        names = ('FMU_LOSS_TIMEOUT_US', 'FAULT_FLAG_CR8_TIMEOUT', 'FAULT_FLAG_OUTPUT_SAFE_FAULT',
                 'FAULT_FLAG_PEER_SESSION', 'FAULT_FLAG_ARM_REJECTED', 'FAULT_FLAG_FMU_HEARTBEAT')
        texts = [path.read_text() for path in PROTOCOLS]
        for name in names:
            values = {re.search(rf'#define {name}\s+(\S+)', text).group(1) for text in texts}
            self.assertEqual(len(values), 1, (name, values))
        self.assertEqual(re.search(r'#define FMU_LOSS_TIMEOUT_US\s+(\d+)', texts[0]).group(1), '50000')
        flags = [int(re.search(rf'#define {name}\s+\(1 << (\d+)\)', texts[0]).group(1)) for name in names[1:]]
        self.assertEqual(len(set(flags)), len(flags))


if __name__ == '__main__':
    unittest.main()
