#!/usr/bin/env python3
"""Source regressions for the RZ/V2H GTM timer lifecycle."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def function_body(source: str, name: str) -> str:
    start = None

    for match in reversed(list(re.finditer(rf"\b{name}\s*\(", source))):
        brace = source.find("{", match.end())
        semicolon = source.find(";", match.end())

        if brace >= 0 and (semicolon < 0 or brace < semicolon):
            start = brace
            break

    if start is None:
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


class GtmLifecycleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.driver = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gtm.c"
        )
        cls.header = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gtm.h"
        )
        cls.board = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rzv2h_timer.c"
        )

    def test_initialize_pulses_reset_before_register_access(self) -> None:
        body = function_body(self.driver, "rzv_gtm_timer_initialize")
        clock = body.index("rzv_clock_enable")
        reset = body.index("rzv_module_reset", clock)
        unreset = body.index("rzv_module_unreset", reset)
        stop = body.index("RZV_GTM_OSTMTT_OFFSET", unreset)

        self.assertLess(clock, reset)
        self.assertLess(reset, unreset)
        self.assertLess(unreset, stop)

    def test_initialize_failure_restores_module_lifecycle(self) -> None:
        body = function_body(self.driver, "rzv_gtm_timer_initialize")
        cleanup = body[body.index("errout_with_module:") :]
        self.assertLess(
            cleanup.index("rzv_module_reset"),
            cleanup.index("rzv_clock_disable"),
        )
        self.assertLess(
            cleanup.index("rzv_clock_disable"),
            cleanup.index("kmm_free"),
        )

    def test_uninitialize_releases_irq_reset_clock_and_storage(self) -> None:
        self.assertIn("rzv_gtm_timer_uninitialize", self.header)
        body = function_body(self.driver, "rzv_gtm_timer_uninitialize")

        for operation in (
            "gtm_timer_stop",
            "up_disable_irq",
            "irq_detach",
            "rzv_module_reset",
            "rzv_clock_disable",
            "kmm_free",
        ):
            self.assertIn(operation, body)

        self.assertLess(body.index("up_disable_irq"), body.index("irq_detach"))
        self.assertLess(
            body.index("rzv_module_reset"),
            body.index("rzv_clock_disable"),
        )
        self.assertLess(body.index("rzv_clock_disable"), body.rindex("kmm_free"))

    def test_board_checks_pointer_registration_result_and_cleans_up(self) -> None:
        body = function_body(self.board, "rzv2h_timer_register")
        self.assertIn("handle = timer_register", body)
        self.assertRegex(body, r"if\s*\(\s*handle\s*==\s*NULL\s*\)")
        self.assertIn("rzv_gtm_timer_uninitialize", body)
        self.assertNotRegex(body, r"\bret\s*=\s*timer_register")

    def test_board_maps_every_gtm_channel_to_matching_device(self) -> None:
        body = function_body(self.board, "board_timer_initialize")
        for channel in range(8):
            self.assertIn(
                f'rzv2h_timer_register(&ret, {channel}, "/dev/timer{channel}")',
                body,
            )


if __name__ == "__main__":
    unittest.main()
