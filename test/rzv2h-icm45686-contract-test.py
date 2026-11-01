#!/usr/bin/env python3
"""Execute the real RZ/V2H ICM-45686 SPI helpers and NSH command on the host.

The board sources are copied with their platform includes stripped and
compiled against a register-level sensor model with a fake monotonic clock.
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h"
APPS = ROOT / "platforms/nuttx/NuttX/apps/examples/icm45686"
CONFIG = BOARD / "configs/icm45686-dma-ssl-rtt/defconfig"


class ICM45686Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-icm45686-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        inputs = {
            "icm45686-spi-under-test.c": BOARD / "src/rzv2h-icm45686-spi.c",
            "icm45686-spi-under-test.h": BOARD / "src/rzv2h-icm45686-spi.h",
            "icm45686-test-under-test.c": BOARD / "src/rzv2h-icm45686-test.c",
        }
        # Keep all real bodies; replace platform includes only.
        for name, source in inputs.items():
            text = re.sub(r"^\s*#\s*include[^\n]*$", "", source.read_text(), flags=re.M)
            (directory / name).write_text(text)
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binary = directory / "icm45686"
        result = subprocess.run(
            [compiler, "-std=c11", "-D_DEFAULT_SOURCE", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(ROOT / "test"),
             str(ROOT / "test/rzv2h-icm45686-host-fixture.c"), "-o", str(cls.binary)],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise AssertionError(f"compilation failed:\n{result.stderr}")

    def run_case(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.rstrip().endswith("PASS"), result.stdout)
        return result.stdout

    def test_packet_decode_vectors_and_header_rejection(self):
        self.run_case("decode")

    def test_fifo_count_keeps_second_read_and_rejects_full(self):
        self.run_case("fifo-count")

    def test_frames_are_exact_and_never_exceed_241_bytes(self):
        self.run_case("lengths")

    def test_invalid_arguments_have_no_io(self):
        self.run_case("invalid")

    def test_achieved_frequency_window_is_2_to_24_mhz(self):
        self.run_case("frequency")

    def test_lock_and_unlock_failures_propagate(self):
        self.run_case("lock")

    def test_successful_runs_configure_drain_and_power_down(self):
        output = self.run_case("success")
        for count in (10, 1, 20, 1000):
            self.assertIn(f"ICM45686 result=0 samples={count}/{count} ", output)
        self.assertRegex(output, r"ICM45686 first accel=\(-?\d+,-?\d+,-?\d+\) "
                                 r"gyro=\(-?\d+,-?\d+,-?\d+\) temp=-?\d+ ts=\d+")
        # Samples print after shutdown, immediately before the result line.
        self.assertRegex(output, r"ICM45686 last [^\n]*\nICM45686 result=0")

    def test_identity_and_bring_up_failures_write_nothing(self):
        output = self.run_case("identity")
        self.assertIn("ICM45686 WHO_AM_I mismatch", output)
        self.assertIn("ICM45686 result=-19 samples=0/5", output)

    def test_reset_and_readback_failures_still_clean_up(self):
        self.run_case("reset-failures")

    def test_no_progress_and_fixed_cap_deadlines(self):
        self.run_case("deadlines")

    def test_fifo_overflow_and_bad_packet_fail_the_run(self):
        output = self.run_case("overflow-bad-packet")
        self.assertIn("ICM45686 bad packet=8 header=0x7a", output)

    def test_cleanup_errors_never_mask_primary_errors(self):
        output = self.run_case("cleanup")
        self.assertIn("ICM45686 cleanup failed: -5", output)

    def test_concurrent_invocation_is_rejected(self):
        self.assertIn("ICM45686 test busy", self.run_case("busy"))

    def test_command_line_count_parsing(self):
        output = self.run_case("cli")
        self.assertIn("Usage: icm45686_test [sample-count: 1..1000]", output)

    def test_elapsed_milliseconds_borrow_and_saturation(self):
        self.run_case("elapsed")

    def test_profile_selects_dma_hardware_ssl_command_only(self):
        config = CONFIG.read_text()
        for line in ("CONFIG_RZV2H_ICM45686_TEST=y", "CONFIG_EXAMPLES_ICM45686=y",
                     "CONFIG_RZV_SPI0_DMA=y", "CONFIG_RZV2H_SPI0_HARDWARE_SSL=y"):
            self.assertIn(line, config)
        for symbol in ("RZV2H_ICM20948_TEST", "EXAMPLES_GY912",
                       "RZV2H_DRONE_SENSOR_EXTENSION", "RZV2H_DUALCR8_DRONE"):
            self.assertIn(f"# CONFIG_{symbol} is not set", config)
        self.assertNotIn("CONFIG_RZV_GPIO_IRQ=y", config)
        kconfig = (BOARD / "Kconfig").read_text()
        block = kconfig[kconfig.index("config RZV2H_ICM45686_TEST"):]
        block = block[:block.index("\nconfig ")]
        self.assertIn("default n", block)
        for dependency in ("RZV_SPI0_DMA", "RZV2H_SPI0_HARDWARE_SSL",
                           "!RZV2H_DRONE_SENSOR_EXTENSION", "!RZV2H_ICM20948_TEST"):
            self.assertIn(dependency, block)
        self.assertIn('default "icm45686_test"', (APPS / "Kconfig").read_text())


if __name__ == "__main__":
    unittest.main()
