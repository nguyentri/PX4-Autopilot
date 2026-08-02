#!/usr/bin/env python3
"""Source/model regressions for the RZ/V2H GPT PWM integration.

These checks cover contracts that are otherwise only observable on target
hardware: output-half routing, buffered live updates, reset/latch sequencing,
ownership validation, and initialization rollback.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"


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


class NuttXLowerHalfContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gpt = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c"
        )
        cls.header = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.h"
        )
        cls.board = read(
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rzv2h_pwm.c"
        )

    def test_board_routes_the_mixed_a_b_outputs_explicitly(self) -> None:
        self.assertIn("enum rzv_gpt_output_e", self.header)
        self.assertRegex(
            self.board,
            r'(?s)"/dev/pwm0".*RZV_GPT_OUTPUT_A.*'
            r'"/dev/pwm1".*RZV_GPT_OUTPUT_B.*'
            r'"/dev/pwm2".*RZV_GPT_OUTPUT_A.*'
            r'"/dev/pwm3".*RZV_GPT_OUTPUT_B',
        )
        self.assertIn("rzv_gpt_initialize_output", self.board)

    def test_running_update_uses_only_buffered_registers(self) -> None:
        body = function_body(self.gpt, "rzv_gpt_update")
        self.assertIn("RZV_GPT_GTPBR_OFFSET", body)
        self.assertRegex(body, r"RZV_GPT_GTCCR[CE]_OFFSET")
        self.assertNotIn("RZV_GPT_GTSTP_OFFSET", body)
        self.assertNotIn("RZV_GPT_GTCLR_OFFSET", body)
        self.assertNotIn("RZV_GPT_GTSTR_OFFSET", body)
        self.assertNotIn("RZV_GPT_GTPR_OFFSET", body)

    def test_initial_direction_uses_the_udf_latch_sequence(self) -> None:
        body = function_body(self.gpt, "gpt_write_gtuddtyc")
        self.assertGreaterEqual(body.count("RZV_GPT_GTUDDTYC_OFFSET"), 2)
        self.assertIn("GPT_GTUDDTYC_UDF", body)

    def test_stop_and_pulse_expiry_share_full_quiesce_sequence(self) -> None:
        quiesce = function_body(self.gpt, "gpt_quiesce_locked")
        stop = function_body(self.gpt, "rzv_gpt_stop")
        irq = function_body(self.gpt, "rzv_gpt_irq")
        self.assertIn("RZV_GPT_GTSTP_OFFSET", quiesce)
        self.assertIn("RZV_GPT_GTCLR_OFFSET", quiesce)
        self.assertIn("RZV_GPT_GTIOR_OFFSET", quiesce)
        self.assertIn("gpt_write_gtuddtyc", quiesce)
        self.assertIn("gpt_quiesce_locked", stop)
        self.assertIn("gpt_quiesce_locked", irq)

    def test_finite_start_publishes_state_before_enabling_irq(self) -> None:
        body = function_body(self.gpt, "rzv_gpt_start")
        self.assertLess(body.index("priv->running = true"), body.index("up_enable_irq"))
        failure = body.split("if (ret < 0)", 2)[-1]
        self.assertIn("gpt_quiesce_locked", failure)

    def test_finite_pulses_complete_on_compare_falling_edges(self) -> None:
        attach = function_body(self.gpt, "rzv_gpt_compare_event")
        start = function_body(self.gpt, "rzv_gpt_start")
        irq = function_body(self.gpt, "rzv_gpt_irq")
        self.assertIn("ELCCMPA", attach)
        self.assertIn("ELCCMPB", attach)
        self.assertIn("GPT_GTINTAD_GTINTA", start)
        self.assertIn("GPT_GTINTAD_GTINTB", start)
        self.assertIn("pulse_started", irq)

        for requested in (1, 2, 10):
            remaining = requested
            pulse_started = False
            completed = 0

            # The initial compare occurs while the output is still low.
            for _ in range(requested + 1):
                if not pulse_started:
                    pulse_started = True
                    continue

                completed += 1
                remaining -= 1
                if remaining == 0:
                    break

            self.assertEqual(completed, requested)
            self.assertEqual(remaining, 0)

    def test_finite_zero_duty_is_rejected(self) -> None:
        start = function_body(self.gpt, "rzv_gpt_start")
        self.assertIsNotNone(
            re.search(
                r"pulsecount > 0.*duty_a_counts == 0.*duty_b_counts == 0",
                start,
                re.S,
            )
        )
        self.assertIn("return -EINVAL", start)

    def test_board_registration_is_resumable(self) -> None:
        body = function_body(self.board, "rzv2h_pwm_setup_locked")
        self.assertIn("registered_mask", body)
        self.assertIn("rzv_unconfiggpio", body)
        self.assertIn("registration_error", body)

        wrapper = function_body(self.board, "rzv2h_pwm_setup")
        self.assertIn("nxmutex_lock", wrapper)
        self.assertIn("nxmutex_unlock", wrapper)


class ConfigurationOwnershipContracts(unittest.TestCase):
    def test_board_glue_is_owned_by_rzv_pwm(self) -> None:
        kconfig = (
            NUTTX / "arch/arm/src/rzv/Kconfig"
        ).read_text(encoding="utf-8")
        gpt_block = kconfig.split("config RZV_GPT", 1)[1].split(
            "config RZV_PWM", 1
        )[0]
        self.assertNotIn("select PWM", gpt_block)

        paths = (
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/CMakeLists.txt",
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/Makefile",
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rzv2h_bringup.c",
            "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/"
            "rdk-rzv2h/src/rdk-rzv2h.h",
        )

        for path in paths:
            with self.subTest(path=path):
                source = read(path)
                self.assertIn("CONFIG_RZV_PWM", source)


class PX4DirectPathContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.io_timer = read(
            "platforms/nuttx/src/px4/renesas/rzv/io_pins/io_timer.c"
        )
        cls.pwm_servo = read(
            "platforms/nuttx/src/px4/renesas/rzv/io_pins/pwm_servo.c"
        )

    def test_rate_update_buffers_while_running_and_clears_while_stopped(
        self,
    ) -> None:
        body = function_body(self.io_timer, "io_timer_set_pwm_rate")
        self.assertLess(
            body.index("px4_enter_critical_section"),
            body.index("io_timer_get_channel_mode"),
        )
        self.assertIn("if (gpt_state[channel].enabled)", body)
        running = body.split("if (gpt_state[channel].enabled)", 1)[1]
        self.assertIn("RZV_GPT_GTPBR_OFFSET", running)
        self.assertIn("RZV_GPT_GTCLR_OFFSET", body)

    def test_disable_clears_the_counter(self) -> None:
        body = function_body(self.io_timer, "io_timer_set_enable")
        self.assertIn("RZV_GPT_GTSTP_OFFSET", body)
        self.assertIn("RZV_GPT_GTCLR_OFFSET", body)
        self.assertLess(
            body.index("px4_enter_critical_section"),
            body.index("channel_allocations[mode]"),
        )

    def test_direction_latch_and_initialization_rollback_exist(self) -> None:
        latch = function_body(self.io_timer, "gpt_write_duty_control")
        init = function_body(self.io_timer, "io_timer_init")
        self.assertGreaterEqual(latch.count("RZV_GPT_GTUDDTYC_OFFSET"), 2)
        self.assertIn("GPT_GTUDDTYC_UDF", latch)
        self.assertIn("rzv2h_gpt_deinit_channel", init)

    def test_public_channel_operations_validate_mode_and_index(self) -> None:
        for name in (
            "io_timer_allocate_channel",
            "io_timer_unallocate_channel",
            "io_timer_get_channel_mode",
            "io_timer_set_enable",
            "io_timer_set_ccr",
        ):
            with self.subTest(function=name):
                body = function_body(self.io_timer, name)
                self.assertIn("valid_channel", body)

    def test_rate_error_is_propagated_before_cache_update(self) -> None:
        body = function_body(self.pwm_servo, "up_pwm_servo_set_rate")
        self.assertIn("return ret", body)
        self.assertLess(body.index("return ret"), body.index("pwm_rate = rate"))

    def test_ccr_ownership_check_is_inside_the_mmio_lock(self) -> None:
        body = function_body(self.io_timer, "io_timer_set_ccr")
        self.assertLess(
            body.index("px4_enter_critical_section"),
            body.index("io_timer_get_channel_mode"),
        )

    def test_pwm_and_oneshot_owners_are_released_separately(self) -> None:
        body = function_body(self.pwm_servo, "pwm_servo_release_channels")
        self.assertIn("pwmout_mask", body)
        self.assertIn("oneshot_mask", body)
        self.assertGreaterEqual(body.count("io_timer_set_enable"), 2)
        self.assertLess(body.index("return ret"), body.index("io_timer_unallocate_channel"))


class BoardResetSafetyContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.board_reset = read(
            "platforms/nuttx/src/px4/renesas/rzv/board_reset/board_reset.c"
        )
        cls.board_init = read("boards/renesas/rdk-rzv2h/src/init.c")
        cls.board_config = read(
            "boards/renesas/rdk-rzv2h/src/board_config.h"
        )
        cls.rzv_kconfig = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig"
        )
        cls.rzv_make_defs = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Make.defs"
        )
        cls.board_reset_cmake = read(
            "platforms/nuttx/src/px4/renesas/rzv/board_reset/CMakeLists.txt"
        )

    def test_board_reset_matches_nuttx_and_runs_safety_hook(self) -> None:
        self.assertRegex(self.board_reset, r"\bint\s+board_reset\(int status\)")
        self.assertIn("<nuttx/board.h>", self.board_reset)
        body = function_body(self.board_reset, "board_reset")
        self.assertIn("board_on_reset(status)", body)
        self.assertLess(body.index("board_on_reset(status)"), body.index("up_systemreset()"))

    def test_reset_hook_disconnects_every_motor_output(self) -> None:
        self.assertIn("#define BOARD_HAS_ON_RESET", self.board_config)
        body = function_body(self.board_init, "board_on_reset")

        for channel in range(4):
            with self.subTest(channel=channel):
                self.assertIn(
                    f"px4_arch_unconfiggpio(BOARD_PWM_CH{channel}_GPIO)",
                    body,
                )

    def test_all_px4_profiles_enable_boardctl_reset(self) -> None:
        for profile in ("nsh", "sih", "core_only"):
            with self.subTest(profile=profile):
                defconfig = read(
                    f"boards/renesas/rdk-rzv2h/nuttx-config/{profile}/defconfig"
                )
                self.assertIn("CONFIG_BOARDCTL_RESET=y", defconfig)

    def test_cr8_architecture_supplies_a_nonreturning_system_reset(self) -> None:
        cr8_selection = self.rzv_kconfig.split(
            "config ARCH_CORTEXR8_SELECTED", 1
        )[1].split("endif # !RZV2H_BUILD_CM33", 1)[0]
        self.assertIn("select ARCH_HAVE_RESET", cr8_selection)
        self.assertIn("CHIP_CSRCS += rzv_systemreset.c", self.rzv_make_defs)
        self.assertIn(
            "target_link_libraries(arch_board_reset PRIVATE nuttx_arch)",
            self.board_reset_cmake,
        )

        system_reset = read(
            "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/"
            "rzv_systemreset.c"
        )
        body = function_body(system_reset, "up_systemreset")
        self.assertIn("RZV_WDT_CHANNEL_2", system_reset)
        self.assertIn("RZV_WDT_CHANNEL_3", system_reset)
        self.assertIn("RZV_CPG_ERRORRST_SEL2_BIT", body)
        self.assertIn("WDT_WDTRCR_RSTIRQS_RESET_REQ", body)
        self.assertIn("for (;;)", body)


class CoreOnlyDemoContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core_defconfig = read(
            "boards/renesas/rdk-rzv2h/nuttx-config/core_only/defconfig"
        )
        cls.full_defconfig = read(
            "boards/renesas/rdk-rzv2h/nuttx-config/nsh/defconfig"
        )
        cls.core_board = read("boards/renesas/rdk-rzv2h/core_only.px4board")
        cls.core_init_cmake = read(
            "ROMFS/rdk-rzv2h-core-only/init.d/CMakeLists.txt"
        )
        cls.core_rcs = read("ROMFS/rdk-rzv2h-core-only/init.d/rcS")
        cls.mixer_module = read("src/lib/mixer_module/mixer_module.cpp")

    def test_core_only_selects_the_generated_px4_romfs(self) -> None:
        self.assertIn("CONFIG_NSH_ARCHROMFS=y", self.core_defconfig)
        self.assertIn("CONFIG_NSH_ROMFSETC=y", self.core_defconfig)
        self.assertIn("rc.sysinit", self.core_init_cmake)
        self.assertTrue(
            (ROOT / "ROMFS/rdk-rzv2h-core-only/init.d/rc.sysinit").is_file()
        )

    def test_core_only_selects_volatile_params_and_fits_nsh_buffer(self) -> None:
        self.assertIn(". /etc/init.d/rc.filepaths", self.core_rcs)
        self.assertIn("param select $PARAM_FILE", self.core_rcs)
        self.assertLess(
            self.core_rcs.index("param select $PARAM_FILE"),
            self.core_rcs.index("param set-default"),
        )

        line_length = re.search(
            r"^CONFIG_NSH_LINELEN=(\d+)$",
            self.core_defconfig,
            re.MULTILINE,
        )
        self.assertIsNotNone(line_length)

        for line_number, line in enumerate(self.core_rcs.splitlines(), 1):
            with self.subTest(line_number=line_number):
                self.assertLess(
                    len(line) + 1,
                    int(line_length.group(1)),
                    "NSH fgets would split this script line",
                )

    def test_core_only_matches_the_full_rzv2h_pwm_timer_configuration(
        self,
    ) -> None:
        required = (
            "CONFIG_PWM=y",
            "CONFIG_RZV_GPT=y",
            "CONFIG_RZV_GPT6=y",
            "CONFIG_RZV_GPT7=y",
            "CONFIG_RZV_GPT9=y",
            "CONFIG_RZV_GPT10=y",
        )

        for symbol in required:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, self.full_defconfig)
                self.assertIn(symbol, self.core_defconfig)

    def test_core_only_links_the_px4_pwm_driver_and_test_command(self) -> None:
        self.assertIn("CONFIG_DRIVERS_PWM_OUT=y", self.core_board)
        self.assertIn("CONFIG_SYSTEMCMDS_ACTUATOR_TEST=y", self.core_board)
        self.assertIn("CONFIG_MODULES_CONTROL_ALLOCATOR=y", self.core_board)
        self.assertIn(
            "CONFIG_BOARD_HAS_PWM=DEFINE_FROM_BOARDCONFIG", self.core_board
        )

    def test_core_only_starts_four_safe_400_hz_pwm_outputs(self) -> None:
        for timer in range(4):
            with self.subTest(timer=timer):
                self.assertIn(
                    f"param set-default PWM_MAIN_TIM{timer} 400",
                    self.core_rcs,
                )

        for channel in range(1, 5):
            with self.subTest(channel=channel):
                self.assertIn(
                    f"param set-default PWM_MAIN_FUNC{channel} {100 + channel}",
                    self.core_rcs,
                )
                self.assertIn(
                    f"param set-default PWM_MAIN_DIS{channel} 1000",
                    self.core_rcs,
                )

        self.assertIn("pwm_out start", self.core_rcs)
        self.assertIn("work_queue status", self.core_rcs)
        self.assertIn("work queues are created on demand", self.core_rcs)
        self.assertIn(
            "ChangeWorkQueue(px4::wq_configurations::rate_ctrl)",
            self.mixer_module,
        )
        self.assertNotIn("actuator_test set", self.core_rcs)


class DocumentationContracts(unittest.TestCase):
    def test_board_readme_uses_the_current_bounded_actuator_command(self) -> None:
        board_readme = read("boards/renesas/rdk-rzv2h/README.md")
        self.assertIn(
            "actuator_test set -m 1 -v 0 -t 5",
            board_readme,
        )
        self.assertNotIn("pwm_out test", board_readme)
        self.assertNotIn("pwm_out arm", board_readme)

    def test_runtime_clock_and_gpio_unconfigure_names_are_current(self) -> None:
        board_config = read("boards/renesas/rdk-rzv2h/src/board_config.h")
        timer_config = read("boards/renesas/rdk-rzv2h/src/timer_config.cpp")
        micro_hal = read(
            "platforms/nuttx/src/px4/renesas/rzv/include/px4_arch/micro_hal.h"
        )

        self.assertIn("P4CLK", board_config)
        self.assertIn("rzv_get_gpt_clock_hz", timer_config)
        self.assertIn("rzv_unconfiggpio", micro_hal)
        self.assertNotIn("CONFIG_RZV_PCLK_FREQUENCY", micro_hal)


if __name__ == "__main__":
    unittest.main()
