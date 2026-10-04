#!/usr/bin/env python3
"""Execute the complete DShot C driver against a GPT/DMAC boundary model.

--driver selects an unchanged saved source for before/after regression evidence.
Only include directives are removed: all driver state and public APIs execute.
The model is bounded host evidence, not proof of board timing or DMA latency.
"""
from pathlib import Path
import argparse
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
DEFAULT_DRIVER = ROOT / "platforms/nuttx/src/px4/renesas/rzv/dshot/dshot.c"
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--driver", type=Path, default=DEFAULT_DRIVER)
OPTIONS, UNITTEST_ARGS = parser.parse_known_args()


class DshotRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="rzv2h-dshot-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        # Keep every definition and statement from the actual translation unit.
        source = OPTIONS.driver.read_text(encoding="utf-8")
        (directory / "dshot-driver.inc").write_text("".join(
            line for line in source.splitlines(keepends=True)
            if not line.lstrip().startswith("#include")), encoding="utf-8")
        for name, contents in {
            "nuttx/config.h": "#define OK 0\n#define FAR\n",
            "px4_platform_common/px4_config.h":
                "#define __BEGIN_DECLS\n#define __END_DECLS\n",
        }.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binary = directory / "dshot-runtime"
        result = subprocess.run([
            compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-I", str(directory), "-I", str(ARCH),
            "-I", str(DEFAULT_DRIVER.parent),
            "-I", str(ROOT / "platforms/nuttx/src/px4/renesas/rzv/include"),
            str(ROOT / "test/rzv2h-dshot-mmio-harness.c"),
            "-o", str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError("host driver compilation failed:\n" + result.stderr)

    def run_scenario(self, scenario, *args):
        result = subprocess.run([str(self.binary), scenario, *map(str, args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_four_outputs_dshot150(self): self.run_scenario("frame", 150000)
    def test_four_outputs_dshot300(self): self.run_scenario("frame", 300000)
    def test_four_outputs_dshot600(self): self.run_scenario("frame", 600000)
    def test_four_outputs_dshot1200(self): self.run_scenario("frame", 1200000)
    def test_completion_delay_does_not_emit_tail_edges(self): self.run_scenario("delay")
    def test_repeated_frames_disarm_and_rearm(self): self.run_scenario("repeat")
    def test_cold_start_software_selector(self): self.run_scenario("start-selector")
    def test_selected_compare_request_and_sparse_mapping(self): self.run_scenario("request")
    def test_dma_compare_write_protection_lifetime(self): self.run_scenario("protection")
    def test_terminal_count_without_end_is_complete(self): self.run_scenario("terminal-count")
    def test_timeout_stops_all_outputs(self): self.run_scenario("timeout")
    def test_dma_error_stops_all_outputs(self): self.run_scenario("error")
    def test_dma_start_failure_stops_all_outputs(self): self.run_scenario("start-failure")
    def test_dma_disable_failure_stops_all_outputs(self): self.run_scenario("disable-failure")
    def test_allocation_failure_rolls_back(self): self.run_scenario("allocation-failure")
    def test_configuration_failure_rolls_back(self): self.run_scenario("configure-failure")
    def test_subset_leaves_other_channels_untouched(self): self.run_scenario("subset")
    def test_disarmed_trigger_has_no_edges(self): self.run_scenario("disarmed")
    def test_invalid_initialization_and_bdshot_rejected(self): self.run_scenario("invalid")
    def test_reinitialization_releases_resources(self): self.run_scenario("reinitialize")
    def test_failed_disable_retains_resources_until_cleanup_retry(self): self.run_scenario("cleanup-retry")
    def test_stop_error_releases_disabled_dma_ownership(self): self.run_scenario("stop-error")
    def test_stale_gpt_capture_and_buffer_configuration_cleared(self): self.run_scenario("stale-registers")


if __name__ == "__main__":
    unittest.main(argv=[__file__, *UNITTEST_ARGS], verbosity=2)
