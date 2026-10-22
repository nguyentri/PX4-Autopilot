#!/usr/bin/env python3
"""Exercise real CAN upper/lower-half paths with modeled MMIO and IRQ delivery."""
import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARCH = NUTTX / 'arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('extract', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
EXTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACT)


def without_includes(text):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', text, flags=re.M)


def structure(text, name):
    start = text.index('struct ' + name + '\n{')
    return text[start:text.index('\n};', start) + 3] + '\n'


class CanLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='rzv2h-canfd-runtime-')
        cls.directory = Path(cls.temporary.name)
        canh = (NUTTX / 'include/nuttx/can/can.h').read_text()
        start = canh.index('#ifdef CONFIG_CAN_EXTID\nbegin_packed_struct struct can_hdr_s')
        end = canh.index('/* This structure defines a CAN message FIFO. */', start)
        contract = canh[start:end]
        for name in ('can_rxfifo_s', 'can_txfifo_s', 'can_rtrwait_s', 'can_ops_s', 'can_reader_s', 'can_dev_s'):
            contract += ('struct can_dev_s;\n' if name == 'can_ops_s' else '') + structure(canh, name)
        contract += '\n'.join(line for line in canh.splitlines() if line.startswith('#define dev_') or line.startswith('#define CAN_MSGLEN')) + '\n'
        for path in (NUTTX/'include/nuttx/can/rzv_canfd.h', ARCH/'hardware/rzv_canfd.h', ARCH/'rzv_canfd.h'):
            contract += without_includes(path.read_text())
        (cls.directory/'canfd-contract.inc').write_text(contract)
        (cls.directory/'canfd-driver.inc').write_text(without_includes((ARCH/'rzv_canfd.c').read_text()))
        (cls.directory/'canfd-board.inc').write_text(without_includes((NUTTX/'boards/arm/rzv/rdk-rzv2h/src/rzv2h_canfd.c').read_text()))
        upper = (NUTTX/'drivers/can/can.c').read_text()
        signatures = ['static uint8_t can_dlc2bytes(', 'static int can_xmit(',
                      'int can_txdone(', 'static ssize_t can_write(', 'static int can_close(']
        (cls.directory/'canfd-upper.inc').write_text('\n'.join(EXTRACT.EXTRACT.definition(upper, sig) for sig in signatures))
        cls.executables = {}
        for depth in (2, 8, 0, "all", "all_loop", "loop8", "high_loop", "high", "sparse", "legacy"):
            mask = {"all": 63, "all_loop": 63, "high_loop": 48, "high": 48, "sparse": 36, "legacy": 3}.get(depth, 9)
            fifo = 8 if depth == "loop8" else depth if isinstance(depth, int) else 2
            binary = cls.directory/f'canfd-{depth}'
            result = subprocess.run(['cc', '-std=c11', '-O0', '-g', '-Wall', '-Wextra',
                '-Werror', '-Wno-unused-parameter', '-Wno-unused-function', '-Wno-sign-compare',
                f'-DTEST_FIFO={fifo or 2}', f'-DTEST_CHANNEL_MASK={mask}', *(['-DTEST_LOOPBACK=1'] if depth in (0, "all_loop", "loop8", "high_loop") else []), '-I', str(cls.directory),
                str(ROOT/'test/rzv2h-canfd-host-harness.c'), '-o', str(binary)], capture_output=True, text=True)
            if result.returncode:
                raise AssertionError(result.stderr)
            cls.executables[depth] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case, depth=2):
        result = subprocess.run([str(self.executables[depth]), case], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receive_filter_preserves_every_classic_and_fd_length(self): self.run_case('payloads', 'all')
    def test_loopback_filter_preserves_every_classic_and_fd_length(self): self.run_case('payloads', 'all_loop')
    def test_failed_internal_recovery_allows_close_and_reopen(self): self.run_case('loopback_failure', 0)
    def test_failed_internal_recovery_drains_legacy_queue(self): self.run_case('loopback_failure', 'loop8')
    def test_failed_expansion_loopback_recovery_allows_close(self): self.run_case('loopback_failure', 'high_loop')
    def test_nondefault_irq_priority_is_applied_before_enable(self): self.run_case('priorities', 'all')
    def test_shared_irq_priority_failure_unwinds_and_retries(self): self.run_case('priority_shared_failure')
    def test_tx_irq_priority_failure_preserves_sibling(self): self.run_case('priority_tx_failure')
    def test_error_irq_priority_failure_preserves_sibling(self): self.run_case('priority_error_failure')
    def test_optional_global_error_priority_failure_releases_its_route(self): self.run_case('priority_global_error_failure')

    def test_all_six_channels_internal_loopback(self): self.run_case('all_channels', 'all_loop')
    def test_all_six_channels_can_operate_together(self): self.run_case('all_channels', 'all')
    def test_high_channels_only_keep_real_afl_and_fifo_ownership(self): self.run_case('all_channels', 'high')
    def test_sparse_channels_two_and_five(self): self.run_case('all_channels', 'sparse')
    def test_legacy_hw1_keeps_can1_without_hw3(self): self.run_case('all_channels', 'legacy')
    def test_internal_loopback_keeps_both_transceivers_isolated(self): self.run_case('loopback', 0)
    def test_stale_rx_is_discarded_and_stuck_fifo_fails_open_bounded(self): self.run_case('stale_rx')
    def test_abort_irq_retires_failure_without_success_and_can_send_again(self): self.run_case('tx_abort')
    def test_sparse_routing_and_real_upper_half(self): self.run_case('routing')
    def test_cancel_and_stale_irq_after_reopen(self): self.run_case('cancel')
    def test_reset_timeout_quarantine_post_fault_write_and_recovery(self): self.run_case('stuck')
    def test_setup_failure_preserves_sibling(self): self.run_case('setup')
    def test_boot_registration_rollback_is_retryable(self): self.run_case('rollback')
    def test_sequence_exhaustion_never_reuses_id(self): self.run_case('exhaustion')
    def test_invalid_arguments_do_not_mutate_active_transfer(self): self.run_case('arguments')
    def test_larger_legacy_queue_rejects_cancel_without_mutation(self): self.run_case('arguments', 8)


if __name__ == '__main__':
    unittest.main()
