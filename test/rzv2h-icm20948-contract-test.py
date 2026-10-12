#!/usr/bin/env python3
"""Execute real board CS dispatch and ICM20948 SPI framing on the host."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h"


class ICM20948Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-icm20948-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        inputs = {
            "board-under-test.c": BOARD / "src/rzv2h_spi.c",
            "board-under-test.h": BOARD / "include/board.h",
            "icm20948-under-test.c": BOARD / "src/rzv2h-icm20948-spi.c",
            "icm20948-under-test.h": BOARD / "src/rzv2h-icm20948-spi.h",
        }
        # Keep all real bodies and conditionals; replace platform includes only.
        for name, source in inputs.items():
            text = re.sub(r"^\s*#\s*include[^\n]*$", "", source.read_text(), flags=re.M)
            (directory / name).write_text(text)
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binaries = {}
        for mode, defines in {
            "gpio": [],
            "ssl": ["CONFIG_RZV2H_SPI0_HARDWARE_SSL"],
            "loopback": ["CONFIG_RZV2H_SPI_INTERNAL_LOOPBACK_SAMPLE"],
        }.items():
            binary = directory / mode
            result = subprocess.run(
                [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
                 "-DCONFIG_RZV_SPI", "-DCONFIG_RZV_SPI0", "-DCONFIG_SPI_DRIVER",
                 *["-D" + flag for flag in defines], "-I", str(directory),
                 "-I", str(ROOT / "test"),
                 str(ROOT / "test/rzv2h-icm20948-host-fixture.c"), "-o", str(binary)],
                capture_output=True, text=True,
            )
            if result.returncode:
                raise AssertionError(f"{mode} compilation failed:\n{result.stderr}")
            cls.binaries[mode] = binary

    def run_cases(self, scenario, modes=("gpio", "ssl", "loopback")):
        for mode in modes:
            with self.subTest(mode=mode):
                result = subprocess.run([str(self.binaries[mode]), scenario],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_legacy_device_ids_preserve_cs_modes(self):
        self.run_cases("select")

    def test_foreign_controller_cannot_select_sensor(self):
        self.run_cases("foreign-device")

    def test_pin_failure_is_not_published_and_can_retry(self):
        self.run_cases("pin-retry")

    def test_controller_failure_can_retry(self):
        self.run_cases("init-retry")

    def test_registration_failure_is_not_published_and_can_retry(self):
        self.run_cases("register-retry")

    def test_register_read_uses_locked_separate_complete_frames(self):
        self.run_cases("read", ("gpio", "ssl"))

    def test_register_write_preserves_bank_and_value(self):
        self.run_cases("write", ("gpio", "ssl"))

    def test_invalid_register_requests_have_no_io(self):
        self.run_cases("invalid")

    def test_lock_failure_propagates_without_bus_traffic(self):
        self.run_cases("lock-error", ("gpio", "ssl"))

    def test_zero_frequency_releases_lock_without_exchange(self):
        self.run_cases("frequency-zero", ("gpio", "ssl"))

    def test_excess_frequency_releases_lock_without_exchange(self):
        self.run_cases("frequency-high", ("gpio", "ssl"))

    def test_unlock_failure_leaves_read_buffer_unchanged(self):
        self.run_cases("unlock-error", ("gpio", "ssl"))


if __name__ == "__main__":
    unittest.main()
