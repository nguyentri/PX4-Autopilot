#!/usr/bin/env python3
"""Execute and statically verify the production RZ/V2H CAN-FD sample."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "platforms/nuttx/NuttX/apps"
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APP = APPS / "examples/rzv_canfd/rzv_canfd_main.c"
CONFIGS = NUTTX / "boards/arm/rzv/rdk-rzv2h/configs"


def without_includes(source: str) -> str:
    return re.sub(r"^\s*#\s*include[^\n]*$", "", source, flags=re.M)


def enabled(text: str, symbol: str) -> bool:
    return re.search(rf"^CONFIG_{re.escape(symbol)}=y$", text, re.M) is not None


def can_contract() -> str:
    """Extract the production message and public RZ/V ABI declarations."""
    can_header = (NUTTX / "include/nuttx/can/can.h").read_text()
    ioctl_header = (NUTTX / "include/nuttx/fs/ioctl.h").read_text()
    vendor_header = (NUTTX / "include/nuttx/can/rzv_canfd.h").read_text()
    ioctl_names = ("_CANBASE", "_IOC_MASK", "_IOC_TYPE", "_IOC_NR", "_IOC", "_CANIOC")
    contract = "\n".join(
        line for line in ioctl_header.splitlines()
        if any(re.match(rf"#define {re.escape(name)}(?:\(|\s)", line)
               for name in ioctl_names)
    ) + "\n"
    contract += "\n".join(
        line for line in can_header.splitlines()
        if re.match(r"#define CAN_(?:FIRST|NCMDS)\s", line)
    ) + "\n"
    start = can_header.index("#ifdef CONFIG_CAN_FD\n#  define CAN_MAXDATALEN")
    end = can_header.index("/* This structure defines a CAN message FIFO. */", start)
    contract += can_header[start:end]
    contract += without_includes(vendor_header)
    return contract


class CanfdSampleContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-canfd-sample-")
        cls.directory = Path(cls.temporary.name)
        (cls.directory / "canfd-app.inc").write_text(without_includes(APP.read_text()))
        (cls.directory / "canfd-contract.inc").write_text(can_contract())
        cls.binaries = {}
        for errors in (False, True):
            binary = cls.directory / f"canfd-sample-errors-{int(errors)}"
            command = [
                "cc", "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-O0", "-g",
                "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                *(["-DCONFIG_CAN_ERRORS=1"] if errors else []),
                "-I", str(cls.directory),
                str(ROOT / "test/rzv2h-canfd-sample-host-harness.c"),
                "-o", str(binary),
            ]
            compile_result = subprocess.run(command, capture_output=True, text=True)
            if compile_result.returncode:
                raise AssertionError(compile_result.stderr)
            cls.binaries[errors] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_case(self, case: str):
        for errors, binary in self.binaries.items():
            result = subprocess.run(
                [str(binary), case], capture_output=True, text=True, timeout=10
            )
            self.assertEqual(result.returncode, 0,
                             f"CONFIG_CAN_ERRORS={int(errors)}: {result.stderr}")

    def test_strict_arguments_and_no_open_on_rejection(self):
        self.run_case("invalid")
        self.run_case("argument-forms")

    def test_full_matrix_and_default_count(self):
        self.run_case("success")
        self.run_case("default")

    def test_retry_paths_are_bounded(self):
        for case in ("eagain", "write-eintr", "read-eagain", "read-eintr"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_semantic_and_short_io_failures(self):
        for case in (
            "short-write", "short-read", "bad-flags", "bad-id", "bad-dlc",
            "bad-payload", "error-frame",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_poll_and_deadline_failures_cleanup(self):
        for case in (
            "poll-error", "poll-hangup", "missing-ack", "missing-irq",
            "stale-irq", "cancel-timeout", "open-second",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_reopen_contracts(self):
        self.run_case("rerun")
        self.run_case("isolated-reopen")

    def test_short_payload_vectors_are_fixed(self):
        self.run_case("vectors")

    def test_profile_ownership_and_generic_app_unchanged(self):
        profile = {name: (CONFIGS / name / "defconfig").read_text()
                   for name in ("canfd", "canfd-rtt", "canfd-dual", "canfd-ext")}
        for name in ("canfd", "canfd-rtt"):
            self.assertTrue(enabled(profile[name], "RZV_CANFD0"))
            self.assertFalse(enabled(profile[name], "RZV_CANFD3"))
            self.assertTrue(enabled(profile[name], "EXAMPLES_CAN"))
            self.assertFalse(enabled(profile[name], "EXAMPLES_RZV_CANFD"))
        self.assertTrue(enabled(profile["canfd-dual"], "RZV_CANFD0"))
        self.assertTrue(enabled(profile["canfd-dual"], "RZV_CANFD3"))
        self.assertTrue(enabled(profile["canfd-dual"], "EXAMPLES_CAN"))
        self.assertFalse(enabled(profile["canfd-dual"], "EXAMPLES_RZV_CANFD"))
        ext = profile["canfd-ext"]
        for symbol in (
            "RZV_CANFD0", "RZV_CANFD3", "CAN_FD", "CAN_EXTID",
            "EXAMPLES_RZV_CANFD", "SEGGER_RTT", "SYSLOG_RTT_CONSOLE_INPUT",
        ):
            self.assertTrue(enabled(ext, symbol), symbol)
        self.assertIn("CONFIG_CAN_FIFOSIZE=2", ext)
        self.assertIn("# CONFIG_RZV_CANFD1 is not set", ext)
        self.assertIn("# CONFIG_RZV_CANFD_BOOT_LOOPBACK is not set", ext)
        self.assertIn("# CONFIG_EXAMPLES_CAN is not set", ext)
        self.assertEqual(
            subprocess.run(
                ["git", "-C", str(APPS), "diff", "--exit-code", "--",
                 "examples/can/can_main.c"], capture_output=True
            ).returncode,
            0,
            "generic CAN application was modified",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
