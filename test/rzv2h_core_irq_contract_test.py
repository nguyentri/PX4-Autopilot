#!/usr/bin/env python3
"""Static contracts for the RZ/V2H CM33 interrupt architecture."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
RZV = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
INCLUDE = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/include/rzv"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0

    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]

    raise AssertionError(f"unterminated function: {signature}")


class Rzv2hCoreIrqContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.irq_header = read(INCLUDE / "irq.h")
        cls.irq = read(RZV / "rzv_irq_cm33.c")
        cls.icu = read(RZV / "rzv_icu_cm33.c")

    def test_cm33_irq_span_is_480_external_vectors(self) -> None:
        cm33_base = re.search(
            r"#ifdef CONFIG_RZV2H_BUILD_CM33(?P<body>.*?)#else",
            self.irq_header,
            re.DOTALL,
        )
        self.assertIsNotNone(cm33_base)
        self.assertRegex(cm33_base.group("body"), r"RZV_IRQ_FIRST\s+\(16\)")
        self.assertRegex(
            self.irq_header,
            r"(?s)#ifdef CONFIG_RZV2H_BUILD_CM33\s+"
            r"#\s*undef RZV_IRQ_NEXTINT\s+"
            r"#\s*define RZV_IRQ_NEXTINT\s+\(480\)",
        )

    def test_cm33_nvic_initialization_is_hardware_bounded(self) -> None:
        body = function_body(self.irq, "static void rzv_cm33_nvic_init(void)")
        self.assertIn("getreg32(NVIC_ICTR)", body)
        self.assertIn("NVIC_ICTR_INTLINESNUM_MASK", body)
        self.assertIn("RZV_IRQ_NEXTINT", body)
        self.assertRegex(body, r"if \(ninterrupts > RZV_IRQ_NEXTINT\)")
        self.assertNotIn("= 512", body)

    def test_cm33_registers_architecture_exception_handlers(self) -> None:
        body = function_body(self.irq, "void up_irqinitialize(void)")
        self.assertIn("irq_attach(NVIC_IRQ_SVCALL, arm_svcall, NULL)", body)
        self.assertIn(
            "irq_attach(NVIC_IRQ_HARDFAULT, arm_hardfault, NULL)", body
        )
        self.assertIn("NVIC_SYSH_SVCALL_PRIORITY", body)
        self.assertLess(body.index("arm_svcall"), body.index("up_irq_enable()"))

    def test_cm33_icu_attach_is_validated_and_transactional(self) -> None:
        body = function_body(
            self.icu,
            "int rzv_icu_m33_attach(int event, xcpt_t handler, void *arg,"
            " bool irq_enable)",
        )
        self.assertIn("if (handler == NULL)", body)
        self.assertIn(
            "if (event < 0 || event > RZV_INTC_INTM33SEL_MASK)", body
        )

        reservation = body.index("slot = g_icu_m33_slot++")
        publication = body.index("ret = irq_attach", reservation)
        self.assertNotIn(
            "leave_critical_section(flags)", body[reservation:publication]
        )
        self.assertRegex(
            body,
            r"(?s)ret = irq_attach.*?if \(ret < 0\).*?"
            r"g_icu_m33_slot--.*?return ret",
        )
        self.assertRegex(
            body,
            r"(?s)ret = rzv_icu_m33_set_event.*?if \(ret < 0\).*?"
            r"irq_detach\(irq\).*?g_icu_m33_slot--.*?return ret",
        )

    def test_cm33_event_programming_rejects_truncation(self) -> None:
        body = function_body(
            self.icu, "static int rzv_icu_m33_set_event(int slot, int event)"
        )
        self.assertIn(
            "if (event < 0 || event > RZV_INTC_INTM33SEL_MASK)", body
        )

    def test_cm33_icu_detach_is_one_atomic_transaction(self) -> None:
        body = function_body(
            self.icu, "int rzv_icu_m33_detach(int icu_irq)"
        )
        lock = body.index("flags = enter_critical_section()")
        handler_check = body.index(
            "if (g_icu_m33_handlers[slot].handler == NULL)"
        )
        disable = body.index("up_disable_irq(icu_irq)")
        detach = body.index("irq_detach(icu_irq)")
        route_clear = body.index("rzv_icu_m33_set_event(slot, 0)")
        table_clear = body.index("g_icu_m33_handlers[slot].handler = NULL")
        allocator_update = body.index("g_icu_m33_slot = highest_used + 1")
        unlock = body.rindex("leave_critical_section(flags)")

        self.assertLess(lock, handler_check)
        self.assertLess(handler_check, disable)
        self.assertLess(disable, detach)
        self.assertLess(detach, route_clear)
        self.assertLess(route_clear, table_clear)
        self.assertLess(table_clear, allocator_update)
        self.assertLess(allocator_update, unlock)


if __name__ == "__main__":
    unittest.main()
