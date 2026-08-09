#!/usr/bin/env python3
"""Source-contract regressions for audited RZ/V2H ADC, GBETH, and SCIF fixes."""

import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = Path(
    os.environ.get("RZV_NUTTX_ROOT", ROOT / "platforms/nuttx/NuttX/nuttx")
)


def read(relative_path: str) -> str:
    return (NUTTX / relative_path).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    for match in reversed(list(re.finditer(rf"\b{name}\s*\(", source))):
        start = source.find("{", match.end())
        semicolon = source.find(";", match.end())
        if start >= 0 and (semicolon < 0 or start < semicolon):
            break
    else:
        raise AssertionError(f"function {name} not found")

    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]

    raise AssertionError(f"function {name} has no closing brace")


class AdcContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = read("arch/arm/src/rzv/rzv_adc.c")

    def test_byte_wide_event_link_register_uses_byte_accessor(self) -> None:
        accessor = function_body(self.source, "rzv_adc_putreg8")
        reset = function_body(self.source, "rzv_adc_reset")
        self.assertIn("putreg8(value", accessor)
        self.assertIn(
            "rzv_adc_putreg8(priv, RZV_ADC_E_ADELCCR_OFFSET, 0)", reset
        )
        self.assertNotIn(
            "rzv_adc_putreg(priv, RZV_ADC_E_ADELCCR_OFFSET", reset
        )


class EthernetContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = read("arch/arm/src/rzv/rzv_ether.c")
        cls.header = read("arch/arm/src/rzv/rzv_ether.h")
        cls.hardware = read("arch/arm/src/rzv/hardware/rzv_ether.h")
        cls.phy = read("arch/arm/src/rzv/rzv_ether_phy.c")

    def test_dma_and_cpu_share_a_16_byte_descriptor_stride(self) -> None:
        self.assertRegex(
            self.header,
            r"_Static_assert\s*\(\s*sizeof\(struct rzv_eth_desc_s\)\s*==\s*16",
        )
        self.assertNotIn("reserved[12]", self.header)
        self.assertIn('section(".noncache_buffer")', self.driver)
        allocator = function_body(self.driver, "rzv_alloc_buffers")
        self.assertNotRegex(allocator, r"kmm_memalign\([^;]*(txdesc|rxdesc)")

    def test_descriptor_ownership_is_not_cache_maintained(self) -> None:
        self.assertNotRegex(
            self.driver,
            r"rzv_(?:clean|invalidate)_dcache_region\s*\(\s*(?:priv->)?(?:txdesc|rxdesc)\s*,",
        )

    def test_descriptor_ownership_has_explicit_dma_ordering(self) -> None:
        self.assertIn('"dmb sy"', self.driver)
        self.assertGreaterEqual(self.driver.count("RZV_ETHER_DMA_BARRIER();"), 8)
        transmit = function_body(self.driver, "rzv_transmit")
        self.assertLess(
            transmit.index("RZV_ETHER_DMA_BARRIER();"),
            transmit.index("txdesc->des3 = TDES3_OWN"),
        )
        self.assertLess(
            transmit.rindex("RZV_ETHER_DMA_BARRIER();"),
            transmit.index("RZV_ETH_DMA_CH0_TXDESC_TAIL"),
        )

    def test_irq_bottom_half_holds_network_lock(self) -> None:
        body = function_body(self.driver, "rzv_work")
        self.assertLess(body.index("net_lock()"), body.index("rzv_receive(priv)"))
        self.assertLess(body.index("rzv_txdone(priv)"), body.rindex("net_unlock()"))

    def test_ifdown_quiesces_and_workers_respect_admin_down(self) -> None:
        ifdown = function_body(self.driver, "rzv_ifdown")
        irqwork = function_body(self.driver, "rzv_work")
        timeout = function_body(self.driver, "rzv_txtimeout_work")
        self.assertIn("priv->bifup = false", ifdown)
        self.assertIn("work_cancel(HPWORK, &priv->irqwork)", ifdown)
        self.assertIn("work_cancel(HPWORK, &priv->txtimeout_work)", ifdown)
        self.assertIn("work_cancel(LPWORK, &priv->txavail_work)", ifdown)
        self.assertRegex(irqwork, r"(?s)if \(!priv->bifup\).*?return;")
        self.assertRegex(timeout, r"(?s)if \(!priv->bifup\).*?return;")

    def test_unknown_phy_mode_is_not_invented(self) -> None:
        body = function_body(self.phy, "rzv_phy_linkstatus")
        self.assertNotIn("Default to 100FD", body)
        self.assertIn("linkstatus = PHY_LINK_DOWN", body)
        self.assertIn("unable to determine speed/duplex", body)

    def test_gigabit_mode_accepts_local_master_or_slave(self) -> None:
        body = function_body(self.phy, "rzv_phy_linkstatus")
        self.assertNotIn("PHY_1000BTSR_LOCAL_MASTER", body)
        self.assertIn("PHY_1000BTSR_MS_FAULT", body)
        self.assertIn("PHY_1000BTCR_ADV_1000FD", body)

    def test_bit_31_mmio_masks_are_unsigned(self) -> None:
        combined = self.driver + self.hardware
        self.assertNotRegex(combined, r"(?<![A-Za-z0-9_])1\s*<<\s*31")


class ScifContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = read("arch/arm/src/rzv/rzv_scif.c")
        cls.lowputc = read("arch/arm/src/rzv/rzv_lowputc.c")
        cls.clock = read("arch/arm/src/rzv/rzv_clock.c")
        cls.clock_header = read("arch/arm/src/rzv/rzv_clock.h")

    def test_irq_ids_preserve_signed_icu_results(self) -> None:
        self.assertRegex(self.driver, r"int\s+irq_rxi;")
        self.assertRegex(self.driver, r"int\s+irq_txi;")
        self.assertIn(".irq_rxi        = -1", self.driver)
        attach = function_body(self.driver, "rzv_scif_attach")
        detach = function_body(self.driver, "rzv_scif_detach")
        self.assertIn("return irq_rxi", attach)
        self.assertIn("rzv_icu_detach(irq_rxi)", attach)
        self.assertIn("priv->irq_rxi >= 0", detach)
        self.assertIn("priv->irq_rxi = -1", detach)

    def test_invalid_baud_is_rejected_before_mmio(self) -> None:
        calculate = function_body(self.driver, "rzv_scif_calculate_baud")
        configure = function_body(self.driver, "rzv_scif_configure")
        self.assertIn("if (baud == 0)", calculate)
        self.assertIn("return -EINVAL", calculate)
        self.assertIn("return -ERANGE", calculate)
        self.assertLess(
            configure.index("rzv_scif_calculate_baud"),
            configure.index("rzv_clock_enable"),
        )

    def test_tcsets_commits_only_after_hardware_configuration(self) -> None:
        ioctl = function_body(self.driver, "rzv_scif_ioctl")
        tcsets = ioctl[ioctl.index("case TCSETS:") :]
        configure = tcsets.index("ret = rzv_scif_configure")
        reject = tcsets.index("if (ret < 0)", configure)
        commit = tcsets.index("priv->baud = baud", reject)
        self.assertLess(configure, reject)
        self.assertLess(reject, commit)

    def test_reset_release_has_failure_and_shutdown_cleanup(self) -> None:
        configure = function_body(self.driver, "rzv_scif_configure")
        shutdown = function_body(self.driver, "rzv_scif_shutdown")
        self.assertIn("rzv_module_unreset(priv->clk_id)", configure)
        self.assertIn("rzv_module_reset(priv->clk_id)", configure)
        self.assertIn("rzv_module_reset(priv->clk_id)", shutdown)

    def test_receive_isr_uses_counters_not_formatted_logging(self) -> None:
        body = function_body(self.driver, "rzv_scif_rxi_interrupt")
        self.assertNotIn("_info(", body)
        self.assertIn("priv->frame_count++", body)
        self.assertIn("priv->overrun_count++", body)

    def test_scif_console_never_falls_back_to_sci3(self) -> None:
        self.assertIn("defined(CONFIG_SCIF0_SERIAL_CONSOLE)", self.lowputc)
        setup = function_body(self.lowputc, "rzv_lowsetup")
        output = function_body(self.lowputc, "rzv_lowputc")
        self.assertIn("RZV_LOWPUTC_SCIF_CONSOLE", setup)
        self.assertIn("RZV_LOWPUTC_SCIF_CONSOLE", output)

    def test_scifa_has_distinct_clock_reset_and_module_stop_contract(self) -> None:
        self.assertRegex(
            self.clock_header,
            r"RZV_CPG_CLK_SCIF0\s+\(8\s*<<\s*16\s*\|\s*15\)",
        )
        self.assertIn("RZV_CPG_CLK_SCIF0", self.driver)
        configure = function_body(self.driver, "rzv_scif_configure")
        self.assertIn("rzv_module_unreset(priv->clk_id)", configure)
        self.assertRegex(
            self.clock,
            r"RZV_CPG_CLK_SCIF0[^\n]*RZV_CPG_BUS_3_MSTOP[^\n]*14",
        )
        unreset = function_body(self.clock, "rzv_module_unreset")
        self.assertRegex(
            unreset,
            r"(?s)clk_id\s*==\s*RZV_CPG_CLK_SCIF0.*?domain\s*=\s*9.*?bitmask\s*=\s*1u\s*<<\s*5",
        )


if __name__ == "__main__":
    unittest.main()
