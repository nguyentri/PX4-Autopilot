#!/usr/bin/env python3
"""Exercise the complete RZ/V2H DMAC driver at its host MMIO boundary."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
DRIVER_SOURCE = DRIVER / "rzv_dmac.c"


class DmacRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="rzv2h-dmac-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        headers = {
            "nuttx/config.h": "#define OK 0\n#define CONFIG_DEBUG_DMA_ERROR 1\n",
            "nuttx/irq.h": "typedef unsigned int irqstate_t;\n"
            "irqstate_t enter_critical_section(void);\n"
            "void leave_critical_section(irqstate_t flags);\n",
            "nuttx/arch.h": "#include <stdint.h>\n"
            "void up_clean_dcache(uintptr_t start, uintptr_t end);\n"
            "void up_invalidate_dcache(uintptr_t start, uintptr_t end);\n"
            "void up_udelay(unsigned int usec);\n",
            "debug.h": "void host_dma_error(const char *format, ...);\n"
            "#define dmaerr(...) host_dma_error(__VA_ARGS__)\n"
            "#define dmainfo(...) ((void)0)\n",
            "arm_internal.h": "#include <stdint.h>\n"
            "uint32_t getreg32(uintptr_t address);\n"
            "void putreg32(uint32_t value, uintptr_t address);\n"
            "void modifyreg32(uintptr_t address, uint32_t clear, uint32_t set);\n",
            "barriers.h": "void host_dsb(void);\n#define ARM_DSB() host_dsb()\n",
        }
        for name, text in headers.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binary = directory / "dmac-runtime"
        result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-D__ARCH_ARM_SRC_RZV_CHIP_H", "-I", str(directory),
             "-I", str(DRIVER), str(ROOT / "test/rzv2h-dmac-mmio-harness.c"),
             str(DRIVER_SOURCE), "-o", str(cls.binary)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise AssertionError(f"host driver compilation failed:\n{result.stderr}")

    def run_scenario(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_enabled_channel_rejects_restart(self):
        self.run_scenario("enabled-start")

    def test_clock_failure_prevents_register_writes_and_allows_retry(self):
        self.run_scenario("clock-failure")

    def test_reset_failure_prevents_register_writes_and_allows_retry(self):
        self.run_scenario("reset-failure")

    def test_enabled_channel_rejects_buffer_replacement(self):
        self.run_scenario("enabled-buffer")

    def test_bus_active_channel_rejects_changes(self):
        self.run_scenario("active")

    def test_cached_destination_prepared_after_disable(self):
        self.run_scenario("cached-restart")

    def test_cached_destination_prepared_after_configure(self):
        self.run_scenario("cached-first")

    def test_polling_mask_restored_on_software_restart(self):
        self.run_scenario("software-mask")

    def test_polling_mask_restored_on_hardware_restart(self):
        self.run_scenario("hardware-mask")

    def test_completed_one_shot_can_rearm(self):
        self.run_scenario("complete-rearm")

    def test_rejected_configurations_do_not_touch_hardware(self):
        self.run_scenario("invalid")

    def test_timeout_and_error_release_preserve_reuse(self):
        self.run_scenario("cleanup")

    def test_error_diagnostics_survive_reset_on_units_zero_one_two(self):
        self.run_scenario("error-diagnostics")

    def test_enable_timeout_preserves_register_write_diagnostics(self):
        self.run_scenario("enable-diagnostics")

    def test_priority_does_not_change_bus_protection(self):
        self.run_scenario("priority-protection")

    def test_new_configuration_clears_stale_errors_and_rejects_live_hardware(self):
        self.run_scenario("warm-configure")

    def test_software_owner_clears_stale_route_and_hardware_rearm_restores_it(self):
        self.run_scenario("stale-route")

    def test_trigger_routing_preserves_sibling(self):
        self.run_scenario("routing")

    def test_peripheral_to_memory_receive(self):
        self.run_scenario("peripheral-source")


if __name__ == "__main__":
    unittest.main(verbosity=2)
