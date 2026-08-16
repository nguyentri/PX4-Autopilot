#!/usr/bin/env python3
"""Recovery and readiness contracts for the RZ/V2H IPC demo."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "platforms/nuttx/NuttX/apps/examples/rzv_ipc_demo/rzv_ipc_demo_main.c"
)


def function_body(source: str, signature: str, next_signature: str) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


class Rzv2hIpcRecoveryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SOURCE.read_text(encoding="utf-8")

    def test_armed_and_transport_ready_are_distinct_markers(self) -> None:
        echo = function_body(self.source, "static int run_echo", "/***")
        armed = echo.index("IPCTEST_ARMED core=%s")
        ready_check = echo.index("ipctest_report_ready", armed)

        self.assertLess(armed, ready_check)
        self.assertNotIn("IPCTEST_READY core=%s", echo[:ready_check])

        reporter = function_body(
            self.source,
            "static bool ipctest_report_ready",
            "static int ipctest_recover_echo",
        )
        self.assertIn("RZV_IPC_RAWIOC_GET_STATS", reporter)
        self.assertIn("stats.ready && !stats.degraded", reporter)
        self.assertIn("IPCTEST_READY core=%s", reporter)

    def test_protocol_read_errors_recover_without_exiting_echo(self) -> None:
        echo = function_body(self.source, "static int run_echo", "/***")
        read_error = echo.index("if (nr < 0)")
        fatal_error = echo.index('fprintf(stderr, "echo read error:', read_error)
        recovery = echo[read_error:fatal_error]

        self.assertIn("errno == EPROTO || errno == ENOLINK", recovery)
        self.assertIn("ipctest_recover_echo", recovery)
        self.assertIn("continue;", recovery)

    def test_successful_recovery_reports_transport_ready(self) -> None:
        recover = function_body(
            self.source,
            "static int ipctest_recover_echo",
            "#endif",
        )
        ioctl = recover.index("RZV_IPC_RAWIOC_RECOVER")
        stats = recover.index('print_raw_stats(fd, a->dev, "echo-recovered")')
        ready = recover.index("ipctest_report_ready", stats)

        self.assertLess(ioctl, stats)
        self.assertLess(stats, ready)


if __name__ == "__main__":
    unittest.main()
