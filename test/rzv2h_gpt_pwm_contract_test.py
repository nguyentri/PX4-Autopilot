#!/usr/bin/env python3
"""Source/model regressions for the RZ/V2H GPT PWM integration.

These checks cover contracts that are otherwise only observable on target
hardware: output-half routing, buffered live updates, reset/latch sequencing,
ownership validation, and initialization rollback.
"""

from pathlib import Path
import errno
from itertools import product
import re
import shutil
import subprocess
import tempfile
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


class ExecutedDutyEndpointContracts(unittest.TestCase):
    """Compile the driver's real helpers instead of duplicating their math."""

    @classmethod
    def setUpClass(cls) -> None:
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-gpt-pwm-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / "nuttx").mkdir()
        (directory / "nuttx/config.h").write_text("", encoding="utf-8")
        source = read("platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c")
        signatures = (
            "static uint32_t gpt_duty_to_counts(uint32_t period, ub16_t duty)",
            "static uint32_t gpt_compute_gtuddtyc(enum rzv_gpt_output_e output, "
            "uint32_t duty_a_counts, uint32_t duty_b_counts, "
            "uint32_t period_counts)",
        )
        functions = "\n".join(
            signature + function_body(source, re.search(r"(\w+)\(", signature)[1])
            for signature in signatures
        )
        (directory / "gpt-driver-functions.inc").write_text(
            functions, encoding="utf-8"
        )
        cls.binaries = {}
        for multichannel in (False, True):
            binary = directory / f"endpoints-multi{int(multichannel)}"
            command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-I", str(directory), "-I", str(NUTTX / "arch/arm/src/rzv")]
            if multichannel:
                command.append("-DCONFIG_PWM_MULTICHAN")
            command += [str(ROOT / "test/rzv2h-gpt-pwm-endpoint-harness.c"),
                        "-o", str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode:
                raise AssertionError(f"host helper compilation failed:\n{result.stderr}")
            cls.binaries[multichannel] = binary

    def evaluate(self, period: int, duty: int, output: int,
                 multichannel: bool = False, other_duty: int = 0) -> tuple[int, int, int]:
        result = subprocess.run(
            [str(self.binaries[multichannel]), str(period), str(duty), str(output),
             str(other_duty)],
            capture_output=True, text=True, check=True,
        )
        return tuple(map(int, result.stdout.split()))

    def test_exact_full_duty_reaches_force_high_for_either_output(self) -> None:
        for period in (1, 2, 1000, 0xFFFFFFFF):
            for output, multichannel in product((0, 1), (False, True)):
                with self.subTest(period=period, output=output, multichannel=multichannel):
                    counts, selected, inactive = self.evaluate(period, 0x10000, output, multichannel)
                    self.assertEqual(counts, period)
                    self.assertEqual(selected, 3)
                    self.assertEqual(inactive, 2)

    def test_zero_and_near_full_remain_distinct_from_full(self) -> None:
        for period in (1, 2, 1000, 0xFFFFFFFF):
            for output, multichannel in product((0, 1), (False, True)):
                with self.subTest(period=period, output=output, multichannel=multichannel):
                    self.assertEqual(self.evaluate(period, 0, output, multichannel), (0, 2, 2))
                    counts, selected, inactive = self.evaluate(period, 0xFFFF, output, multichannel)
                    self.assertLess(counts, period)
                    self.assertEqual(selected, 0 if counts else 2)
                    self.assertEqual(inactive, 2)

    def test_multichannel_endpoint_modes_are_independent(self) -> None:
        for duty_a, duty_b in product((0, 0xFFFF, 0x10000), repeat=2):
            with self.subTest(duty_a=duty_a, duty_b=duty_b):
                counts, mode_a, mode_b = self.evaluate(1000, duty_a, 0, True, duty_b)
                self.assertEqual(counts, {0: 0, 0xFFFF: 999, 0x10000: 1000}[duty_a])
                self.assertEqual(mode_a, {0: 2, 0xFFFF: 0, 0x10000: 3}[duty_a])
                self.assertEqual(mode_b, {0: 2, 0xFFFF: 0, 0x10000: 3}[duty_b])


class ExecutedPWMRequestContracts(unittest.TestCase):
    """Run real start/update code with observable register writes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-gpt-pwm-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        (directory / "nuttx").mkdir()
        (directory / "nuttx/config.h").write_text("", encoding="utf-8")
        source = read("platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c")
        types = "\n".join(
            re.search(rf"struct {name}\s*\{{.*?\n\}};", source, re.S)[0]
            for name in ("rzv_gpt_lowerhalf_s", "rzv_gpt_divider_s")
        )
        (directory / "gpt-driver-types.inc").write_text(types, encoding="utf-8")
        dividers = re.search(
            r"static const struct rzv_gpt_divider_s g_rzv_gpt_dividers\[\] ="
            r"\s*\{.*?\n\};", source, re.S
        )[0]
        signatures = (
            "static void gpt_unlock(struct rzv_gpt_lowerhalf_s *priv)",
            "static void gpt_lock(struct rzv_gpt_lowerhalf_s *priv)",
            "static int gpt_compute_period(struct rzv_gpt_lowerhalf_s *priv, "
            "uint32_t frequency, uint32_t *period, uint32_t *tpcs)",
            "static uint32_t gpt_duty_to_counts(uint32_t period, ub16_t duty)",
            "static uint32_t gpt_compose_gtior(enum rzv_gpt_output_e output, "
            "uint32_t duty_a_counts, uint32_t duty_b_counts, uint32_t period_counts)",
            "static uint32_t gpt_compute_gtuddtyc(enum rzv_gpt_output_e output, "
            "uint32_t duty_a_counts, uint32_t duty_b_counts, uint32_t period_counts)",
            "static void gpt_write_gtuddtyc(struct rzv_gpt_lowerhalf_s *priv, "
            "uint32_t value, bool latch_direction)",
            "static void gpt_quiesce_locked(struct rzv_gpt_lowerhalf_s *priv)",
            "static int rzv_gpt_update(struct rzv_gpt_lowerhalf_s *priv, "
            "uint32_t period, uint32_t tpcs, uint32_t duty_a_counts, "
            "uint32_t duty_b_counts)",
            "#ifdef CONFIG_PWM_PULSECOUNT\n"
            "static int rzv_gpt_start(struct pwm_lowerhalf_s *dev, "
            "const struct pwm_info_s *info, void *handle)\n"
            "#else\nstatic int rzv_gpt_start(struct pwm_lowerhalf_s *dev, "
            "const struct pwm_info_s *info)\n#endif\n",
        )
        functions = [dividers]
        for signature in signatures:
            name = re.search(r"(\w+)\(", signature)[1]
            definition = signature + function_body(source, name)
            if name == "gpt_quiesce_locked":
                definition = "#ifdef CONFIG_PWM_PULSECOUNT\n" + definition + "\n#endif"
            functions.append(definition)
        (directory / "gpt-driver-functions.inc").write_text("\n".join(functions), encoding="utf-8")
        compiler = shutil.which("cc")
        if compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.binaries = {}
        for multichannel, pulsecount in product((False, True), repeat=2):
            binary = directory / f"{'multi' if multichannel else 'single'}-pulse{int(pulsecount)}"
            command = [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                       "-I", str(directory),
                       "-I", str(NUTTX / "arch/arm/src/rzv")]
            if pulsecount:
                command.append("-DCONFIG_PWM_PULSECOUNT")
            if multichannel:
                command.append("-DCONFIG_PWM_MULTICHAN")
            command += [str(ROOT / "test/rzv2h-gpt-pwm-mmio-harness.c"),
                        "-o", str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode:
                raise AssertionError(f"host driver compilation failed:\n{result.stderr}")
            cls.binaries[multichannel, pulsecount] = binary

    def request(self, multichannel: bool, duty: int, output: int = 0,
                count: int = 0, initialized: bool = True,
                handle: bool = True, pulsecount: bool = True) -> tuple[int, ...]:
        result = subprocess.run(
            [str(self.binaries[multichannel, pulsecount]), "start", str(duty), str(output),
             str(count), str(int(initialized)), str(int(handle))],
            capture_output=True, text=True, check=True,
        )
        return tuple(map(int, result.stdout.split()))

    def test_above_full_duty_is_rejected_before_setup_or_mmio(self) -> None:
        for multichannel, pulsecount in product((False, True), repeat=2):
            for output in (0, 1):
                for duty in (0x10001, 0xFFFFFFFF):
                    with self.subTest(multichannel=multichannel, pulsecount=pulsecount,
                                      output=output, duty=duty):
                        self.assertEqual(
                            self.request(multichannel, duty, output, initialized=False,
                                         pulsecount=pulsecount),
                            (-errno.EINVAL, 0, 0, 0, 0),
                        )

    def test_finite_endpoint_requests_have_no_falling_edges(self) -> None:
        for output in (0, 1):
            for duty in (0, 0x10000):
                with self.subTest(output=output, duty=duty):
                    result = self.request(False, duty, output, count=1)
                    self.assertEqual(result, (-errno.EINVAL, 0, 0, 0, 0))

    def test_near_full_finite_and_continuous_endpoints_remain_supported(self) -> None:
        for output in (0, 1):
            with self.subTest(output=output):
                ret, writes, setup, running, irq = self.request(False, 0xFFFF, output, 1)
                self.assertEqual((ret, setup, running, irq), (0, 0, 1, 1))
                self.assertGreater(writes, 0)
                for duty in (0, 0x10000):
                    self.assertEqual(self.request(False, duty, output)[0], 0)
                    self.assertEqual(self.request(False, duty, output, 1, handle=False)[0], 0)

    def live(self, multichannel: bool, output: int, injection: int,
             old_period: int, new_period: int, options: int = 0,
             pulsecount: bool = True) -> tuple[int, ...]:
        result = subprocess.run(
            [str(self.binaries[multichannel, pulsecount]), "live", str(output), str(injection),
             str(old_period), str(new_period), str(options)],
            capture_output=True, text=True, check=True,
        )
        return tuple(map(int, result.stdout.split()))

    def test_overflow_between_each_mmio_access_cannot_mix_period_and_compare(self) -> None:
        for multichannel, pulsecount in product((False, True), repeat=2):
            for output in (0, 1):
                for old_period, new_period in ((1000, 500), (500, 2000), (1000, 2)):
                    for pending in (False, True):
                        options = 2 if pending else 0
                        baseline = self.live(multichannel, output, 0, old_period,
                                             new_period, options, pulsecount)
                        writes, accesses = baseline[1:3]
                        for injection in (-1, 0, *range(1, accesses + 1)):
                            with self.subTest(multichannel=multichannel, pulsecount=pulsecount,
                                              output=output,
                                              old_period=old_period, new_period=new_period,
                                              pending=pending, injection=injection):
                                ret, actual_writes, actual_accesses, mixed, forbidden, final, restored, period = (
                                    self.live(multichannel, output, injection,
                                              old_period, new_period, options, pulsecount)
                                )
                                self.assertEqual(ret, 0)
                                self.assertEqual(actual_writes, writes)
                                self.assertEqual(actual_accesses, accesses)
                                self.assertEqual(mixed, 0)
                                self.assertEqual(forbidden, 0)
                                self.assertEqual((final, restored, period), (1, 1, new_period))

    def test_live_prescaler_change_rejected_before_register_writes(self) -> None:
        for multichannel, pulsecount in product((False, True), repeat=2):
            for output in (0, 1):
                with self.subTest(multichannel=multichannel, pulsecount=pulsecount, output=output):
                    result = self.live(multichannel, output, -1, 1000, 500, options=1,
                                       pulsecount=pulsecount)
                    self.assertEqual(result, (-errno.ERANGE, 0, 0, 0, 0, 0, 1, 1000))

    def test_start_without_pulsecount_accepts_continuous_endpoints(self) -> None:
        for multichannel in (False, True):
            for output in (0, 1):
                for duty in (0, 0x8000, 0xFFFF, 0x10000):
                    with self.subTest(multichannel=multichannel, output=output, duty=duty):
                        ret, writes, setup, running, irq = self.request(
                            multichannel, duty, output, pulsecount=False
                        )
                        self.assertEqual((ret, setup, running, irq), (0, 0, 1, 0))
                        self.assertGreater(writes, 0)


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

    def test_setup_admits_software_start_stop_and_clear(self) -> None:
        compiler = shutil.which("cc")
        self.assertIsNotNone(compiler)
        bodies = "\n".join(
            signature + function_body(self.gpt, name)
            for name, signature in (
                ("gpt_unlock", "static void gpt_unlock(struct rzv_gpt_lowerhalf_s *priv)"),
                ("gpt_lock", "static void gpt_lock(struct rzv_gpt_lowerhalf_s *priv)"),
                ("rzv_gpt_setup", "static int rzv_gpt_setup(struct pwm_lowerhalf_s *dev)"),
            )
        )
        boundary = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "hardware/rzv_gpt.h"
#define FAR
#define OK 0
typedef unsigned int irqstate_t;
struct pwm_lowerhalf_s { int unused; };
struct rzv_gpt_lowerhalf_s {
  struct pwm_lowerhalf_s dev;
  uint32_t pclk;
  unsigned int channel;
  unsigned int hw_ch;
  bool initialized;
};
static uint32_t registers[64];
static int rzv_gpt_module_start(int channel) { (void)channel; return 0; }
static uint32_t rzv_get_gpt_clock_hz(void) { return 200000000; }
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; }
static void gpt_putreg(struct rzv_gpt_lowerhalf_s *priv, unsigned int offset,
                       uint32_t value) {
  uint32_t bit = 1u << priv->hw_ch;
  registers[offset / 4] = value;
  /* Software group commands only act when their source admits them. */
  if ((value & bit) && offset == RZV_GPT_GTSTR_OFFSET &&
      (registers[RZV_GPT_GTSSR_OFFSET / 4] & (1u << 31)))
    registers[RZV_GPT_GTCR_OFFSET / 4] |= GPT_GTCR_CST;
  if ((value & bit) && offset == RZV_GPT_GTSTP_OFFSET &&
      (registers[RZV_GPT_GTPSR_OFFSET / 4] & (1u << 31)))
    registers[RZV_GPT_GTCR_OFFSET / 4] &= ~GPT_GTCR_CST;
  if ((value & bit) && offset == RZV_GPT_GTCLR_OFFSET &&
      (registers[RZV_GPT_GTCSR_OFFSET / 4] & (1u << 31)))
    registers[RZV_GPT_GTCNT_OFFSET / 4] = 0;
}
"""
        exercise = r"""
int main(void) {
  struct rzv_gpt_lowerhalf_s priv = {.channel = 6, .hw_ch = 6};
  registers[RZV_GPT_GTCNT_OFFSET / 4] = 123;
  assert(rzv_gpt_setup(&priv.dev) == 0 && priv.initialized);
  assert(registers[RZV_GPT_GTCNT_OFFSET / 4] == 0);
  gpt_putreg(&priv, RZV_GPT_GTSTR_OFFSET, 1u << 6);
  assert(registers[RZV_GPT_GTCR_OFFSET / 4] & GPT_GTCR_CST);
  gpt_putreg(&priv, RZV_GPT_GTSTP_OFFSET, 1u << 6);
  assert(!(registers[RZV_GPT_GTCR_OFFSET / 4] & GPT_GTCR_CST));
  registers[RZV_GPT_GTCNT_OFFSET / 4] = 456;
  gpt_putreg(&priv, RZV_GPT_GTCLR_OFFSET, 1u << 6);
  assert(registers[RZV_GPT_GTCNT_OFFSET / 4] == 0);
}
"""
        with tempfile.TemporaryDirectory(prefix="rzv2h-gpt-setup-") as tmp:
            directory = Path(tmp)
            (directory / "nuttx").mkdir()
            (directory / "nuttx/config.h").write_text("")
            source = directory / "setup.c"
            source.write_text(boundary + bodies + exercise)
            binary = directory / "setup"
            subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", tmp, "-I", str(NUTTX / "arch/arm/src/rzv"),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

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

    def test_running_update_defensively_masks_startup_force_transfer(self) -> None:
        body = function_body(self.gpt, "rzv_gpt_update")
        self.assertRegex(
            body, r"gpt_getreg\(priv, RZV_GPT_GTBER_OFFSET\)\s*&\s*~GPT_GTBER_CCRSWT"
        )

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

    def test_compare_irq_selectors_match_the_cr8_source_table(self) -> None:
        body = function_body(self.gpt, "rzv_gpt_compare_event")
        program = r"""
#include <assert.h>
#include <stdint.h>
#include "hardware/rzv_gpt.h"
#define FAR
#define RZV_GPT_OUTPUT_A 0
struct rzv_gpt_lowerhalf_s { unsigned int channel, hw_ch, output; };
""" + "static uint16_t rzv_gpt_compare_event(const struct rzv_gpt_lowerhalf_s *priv)" + body + r"""
int main(void) {
  const unsigned int channels[] = {6, 7, 9, 10};
  const unsigned int outputs[] = {0, 1, 0, 1};
  /* FSP CR8 IRQSEL identifiers, not ELC event numbers. */
  const unsigned int expected[] = {121, 130, 220, 229};
  for (unsigned int i = 0; i < 4; ++i) {
    struct rzv_gpt_lowerhalf_s priv = {channels[i], channels[i] % 8, outputs[i]};
    assert(rzv_gpt_compare_event(&priv) == expected[i]);
  }
}
"""
        with tempfile.TemporaryDirectory(prefix="rzv2h-gpt-irqsel-") as tmp:
            directory = Path(tmp)
            (directory / "nuttx").mkdir()
            (directory / "nuttx/config.h").write_text("")
            source = directory / "irqsel.c"
            source.write_text(program)
            binary = directory / "irqsel"
            subprocess.run([shutil.which("cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", tmp, "-I", str(NUTTX / "arch/arm/src/rzv"),
                            str(source), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_finite_pulses_complete_on_compare_falling_edges(self) -> None:
        attach = function_body(self.gpt, "rzv_gpt_compare_event")
        start = function_body(self.gpt, "rzv_gpt_start")
        irq = function_body(self.gpt, "rzv_gpt_irq")
        self.assertIn("IRQSEL_CCMPA", attach)
        self.assertIn("IRQSEL_CCMPB", attach)
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
        for profile in ("nsh", "sih", "core_only", "simple"):
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


class SimpleDemoContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.simple_defconfig = read(
            "boards/renesas/rdk-rzv2h/nuttx-config/simple/defconfig"
        )
        cls.full_defconfig = read(
            "boards/renesas/rdk-rzv2h/nuttx-config/nsh/defconfig"
        )
        cls.simple_board = read("boards/renesas/rdk-rzv2h/simple.px4board")
        cls.simple_init_cmake = read(
            "ROMFS/rdk-rzv2h-simple/init.d/CMakeLists.txt"
        )
        cls.simple_rcs = read("ROMFS/rdk-rzv2h-simple/init.d/rcS")
        cls.simple_defaults = read("ROMFS/rdk-rzv2h-simple/init.d/rc.board_defaults")
        cls.simple_sensors = read("ROMFS/rdk-rzv2h-simple/init.d/rc.board_sensors")
        cls.mixer_module = read("src/lib/mixer_module/mixer_module.cpp")

    def test_simple_selects_the_generated_px4_romfs(self) -> None:
        self.assertIn("CONFIG_NSH_ARCHROMFS=y", self.simple_defconfig)
        self.assertIn("CONFIG_NSH_ROMFSETC=y", self.simple_defconfig)
        self.assertIn("rc.sysinit", self.simple_init_cmake)
        self.assertTrue(
            (ROOT / "ROMFS/rdk-rzv2h-simple/init.d/rc.sysinit").is_file()
        )

    def test_simple_selects_volatile_params_and_fits_nsh_buffer(self) -> None:
        self.assertIn(". /etc/init.d/rc.filepaths", self.simple_rcs)
        self.assertIn("param select $PARAM_FILE", self.simple_rcs)
        self.assertLess(
            self.simple_rcs.index("param select $PARAM_FILE"),
            self.simple_rcs.index(". /etc/init.d/rc.board_defaults"),
        )

        line_length = re.search(
            r"^CONFIG_NSH_LINELEN=(\d+)$",
            self.simple_defconfig,
            re.MULTILINE,
        )
        self.assertIsNotNone(line_length)

        for line_number, line in enumerate((self.simple_rcs + self.simple_defaults + self.simple_sensors).splitlines(), 1):
            with self.subTest(line_number=line_number):
                self.assertLess(
                    len(line) + 1,
                    int(line_length.group(1)),
                    "NSH fgets would split this script line",
                )

    def test_simple_matches_the_full_rzv2h_pwm_timer_configuration(
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
                self.assertIn(symbol, self.simple_defconfig)

    def test_simple_links_the_px4_pwm_driver_and_test_command(self) -> None:
        self.assertIn("CONFIG_DRIVERS_PWM_OUT=y", self.simple_board)
        self.assertIn("CONFIG_SYSTEMCMDS_ACTUATOR_TEST=y", self.simple_board)
        self.assertIn("CONFIG_MODULES_CONTROL_ALLOCATOR=y", self.simple_board)
        self.assertIn(
            "CONFIG_BOARD_HAS_PWM=DEFINE_FROM_BOARDCONFIG", self.simple_board
        )

    def test_simple_starts_four_safe_400_hz_pwm_outputs(self) -> None:
        for timer in range(4):
            with self.subTest(timer=timer):
                self.assertIn(
                    f"param set-default PWM_MAIN_TIM{timer} 400",
                    self.simple_defaults,
                )

        for channel in range(1, 5):
            with self.subTest(channel=channel):
                self.assertIn(
                    f"param set-default PWM_MAIN_FUNC{channel} {100 + channel}",
                    self.simple_defaults,
                )
                self.assertIn(
                    f"param set-default PWM_MAIN_DIS{channel} 1000",
                    self.simple_defaults,
                )

        self.assertIn("pwm_out start", self.simple_rcs)
        self.assertIn("work_queue status", self.simple_rcs)
        self.assertIn(". /etc/init.d/rc.board_sensors", self.simple_rcs)
        self.assertIn("if icm20948 -s -b 0 -R 0 start", self.simple_sensors)
        self.assertIn(
            "ChangeWorkQueue(px4::wq_configurations::rate_ctrl)",
            self.mixer_module,
        )
        self.assertNotIn("actuator_test set", self.simple_rcs)

    def test_archived_core_only_resources_remain_available(self) -> None:
        for path in (
            "boards/renesas/rdk-rzv2h/nuttx-config/core_only/defconfig",
            "ROMFS/rdk-rzv2h-core-only/init.d/rcS",
            "ROMFS/rdk-rzv2h-core-only/init.d/rc.sysinit",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())


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
