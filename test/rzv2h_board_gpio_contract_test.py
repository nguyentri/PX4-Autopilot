#!/usr/bin/env python3
"""Board-level GPIO ownership contracts for the RDK-RZ/V2H port."""

from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PX4_BOARD_HEADER = ROOT / "boards/renesas/rdk-rzv2h/src/board_config.h"
NUTTX_BOARD_DIR = (
    ROOT
    / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h"
)
NUTTX_BOARD_HEADER = NUTTX_BOARD_DIR / "include/board.h"

NUTTX_PERIPHERAL_MACROS = (
    "BOARD_SCI3_TXD_GPIO",
    "BOARD_SCI3_RXD_GPIO",
    "BOARD_I2C0_SDA_GPIO",
    "BOARD_I2C0_SCL_GPIO",
    "BOARD_I2C1_SDA_GPIO",
    "BOARD_I2C1_SCL_GPIO",
    "BOARD_I2C2_SDA_GPIO",
    "BOARD_I2C2_SCL_GPIO",
    "BOARD_RIIC0_SDA_GPIO",
    "BOARD_RIIC0_SCL_GPIO",
    "BOARD_RIIC1_SDA_GPIO",
    "BOARD_RIIC1_SCL_GPIO",
    "BOARD_RIIC2_SDA_GPIO",
    "BOARD_RIIC2_SCL_GPIO",
    "BOARD_SCI0_I2C_SCL_GPIO",
    "BOARD_SCI0_I2C_SDA_GPIO",
    "BOARD_SCI1_I2C_SCL_GPIO",
    "BOARD_SCI1_I2C_SDA_GPIO",
    "BOARD_SCI2_I2C_SCL_GPIO",
    "BOARD_SCI2_I2C_SDA_GPIO",
    "BOARD_SCI3_I2C_SCL_GPIO",
    "BOARD_SCI3_I2C_SDA_GPIO",
    "BOARD_SCI7_I2C_SCL_GPIO",
    "BOARD_SCI7_I2C_SDA_GPIO",
    "BOARD_SPI0_MOSI_GPIO",
    "BOARD_SPI0_MISO_GPIO",
    "BOARD_SPI0_SCK_GPIO",
    "BOARD_SPI0_SS0_GPIO",
    "BOARD_PWM_CH0_GPIO",
    "BOARD_PWM_CH1_GPIO",
    "BOARD_PWM_CH2_GPIO",
    "BOARD_PWM_CH3_GPIO",
    "BOARD_P7_0_GPIO",
    "BOARD_P7_1_GPIO",
    "BOARD_P7_2_GPIO",
    "BOARD_P7_3_GPIO",
    "BOARD_P7_5_GPIO",
    "BOARD_P7_6_GPIO",
    "BOARD_P7_7_GPIO",
    "BOARD_P8_2_GPIO",
    "BOARD_P8_3_GPIO",
    "BOARD_P9_0_GPIO",
    "BOARD_P9_1_GPIO",
    "BOARD_P9_2_GPIO",
    "BOARD_P9_3_GPIO",
    "BOARD_CANFD0_TX_GPIO",
    "BOARD_CANFD0_RX_GPIO",
    "BOARD_CANFD1_TX_GPIO",
    "BOARD_CANFD1_RX_GPIO",
)

PX4_PERIPHERAL_MACROS = tuple(
    "BOARD_PWM_CH{}_GPIO".format(channel) for channel in range(4)
)


def macro_definitions(path):
    definitions = {}
    logical_line = ""

    for source_line in path.read_text(encoding="utf-8").splitlines():
        logical_line += source_line

        if source_line.rstrip().endswith("\\"):
            logical_line = logical_line.rstrip()[:-1] + " "
            continue

        match = re.match(
            r"\s*#\s*define\s+(BOARD_[A-Z0-9_]+_GPIO)\s+(.+)",
            logical_line,
        )

        if match:
            definitions[match.group(1)] = match.group(2).split("/*", 1)[0]

        logical_line = ""

    return definitions


def resolved_bodies(definitions, macro):
    seen = []
    bodies = []

    while macro not in seen:
        seen.append(macro)
        body = definitions[macro]
        bodies.append(body)

        alias = re.search(r"\b(BOARD_[A-Z0-9_]+_GPIO)\b", body)

        if alias is None or alias.group(1) not in definitions:
            return bodies

        macro = alias.group(1)

    raise AssertionError("cyclic GPIO macro alias: " + " -> ".join(seen))


def assert_peripheral_mode(test_case, definitions, macro):
    bodies = resolved_bodies(definitions, macro)
    expression = " ".join(bodies)

    test_case.assertIn(
        "RZV_GPIO_PERIPH",
        expression,
        macro + " does not include RZV_GPIO_PERIPH",
    )

    for conflicting_mode in (
        "RZV_GPIO_INPUT",
        "RZV_GPIO_OUTPUT",
        "RZV_GPIO_ANALOG",
    ):
        test_case.assertNotIn(
            conflicting_mode,
            expression,
            macro + " also includes " + conflicting_mode,
        )


def assert_not_peripheral_mode(test_case, definitions, macro):
    expression = " ".join(resolved_bodies(definitions, macro))
    test_case.assertNotIn(
        "RZV_GPIO_PERIPH",
        expression,
        macro + " must remain GPIO/IRQ mode",
    )


def preprocess_mode_contract(include_directive, include_dirs, macros,
                             extra_definitions=""):
    compiler = shutil.which("cc")

    if compiler is None:
        raise AssertionError("host C preprocessor 'cc' is required")

    checks = []

    for macro in macros:
        checks.extend((
            "#ifndef " + macro,
            '#error "' + macro + ' is not defined"',
            "#endif",
            "#if ((" + macro
            + " & GPIO_MODE_MASK) != RZV_GPIO_PERIPH)",
            '#error "' + macro + ' does not resolve to peripheral mode"',
            "#endif",
        ))

    source = "\n".join((
        include_directive,
        extra_definitions,
        *checks,
        "",
    ))

    with tempfile.TemporaryDirectory(
        prefix="rzv2h-board-gpio-contract-"
    ) as temporary_directory:
        temporary_path = Path(temporary_directory)
        nuttx_path = temporary_path / "nuttx"
        nuttx_path.mkdir()
        shutil.copytree(
            ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/include",
            temporary_path / "arch",
            symlinks=True,
            ignore=shutil.ignore_patterns("board", "chip"),
        )
        chip_include_path = temporary_path / "arch/chip"
        chip_include_path.mkdir(parents=True)
        (nuttx_path / "config.h").write_text(
            "#define CONFIG_RZV2H_GROUP 1\n"
            "#define CONFIG_ARCH_CHIP_R9A09G057 1\n"
            "#define CONFIG_ARCH_ARMV7R 1\n"
            "#define CONFIG_ARCH_CORTEXR8 1\n",
            encoding="utf-8",
        )
        (chip_include_path / "irq.h").write_text(
            "/* Keep this host contract independent of the last configured "
            "NuttX target. */\n"
            "#include <arch/rzv/irq.h>\n",
            encoding="utf-8",
        )
        (temporary_path / "px4_boardconfig.h").write_text(
            "/* Empty host-preprocessor board configuration. */\n",
            encoding="utf-8",
        )

        command = [compiler, "-E", "-x", "c", "-I" + str(temporary_path)]
        command.extend("-I" + str(path) for path in include_dirs)
        command.append("-")

        return subprocess.run(
            command,
            cwd=ROOT,
            input=source,
            text=True,
            capture_output=True,
            check=False,
        )


class BoardPeripheralGPIOContracts(unittest.TestCase):
    def test_nuttx_peripheral_macros_own_the_mode_flag(self):
        definitions = macro_definitions(NUTTX_BOARD_HEADER)

        for macro in NUTTX_PERIPHERAL_MACROS:
            with self.subTest(macro=macro):
                self.assertIn(macro, definitions)
                assert_peripheral_mode(self, definitions, macro)

    def test_px4_pwm_macros_own_the_mode_flag(self):
        definitions = macro_definitions(PX4_BOARD_HEADER)

        for macro in PX4_PERIPHERAL_MACROS:
            with self.subTest(macro=macro):
                assert_peripheral_mode(self, definitions, macro)

    def test_resolved_mode_bits_are_exactly_peripheral(self):
        arch_path = (
            ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
        )
        nuttx_include_dirs = (
            NUTTX_BOARD_DIR / "include",
            arch_path,
            arch_path / "hardware",
            ROOT / "platforms/nuttx/NuttX/nuttx/include",
        )
        nuttx_result = preprocess_mode_contract(
            '#include "board.h"',
            nuttx_include_dirs,
            NUTTX_PERIPHERAL_MACROS,
        )
        self.assertEqual(
            0,
            nuttx_result.returncode,
            nuttx_result.stderr,
        )

        px4_result = preprocess_mode_contract(
            '#include "rzv_gpio.h"\n#include "board_config.h"',
            (
                ROOT / "platforms/common/include",
                ROOT / "platforms/nuttx/NuttX/nuttx/include",
                arch_path,
                arch_path / "hardware",
                PX4_BOARD_HEADER.parent,
            ),
            PX4_PERIPHERAL_MACROS,
        )
        self.assertEqual(0, px4_result.returncode, px4_result.stderr)

        conflict_result = preprocess_mode_contract(
            '#include "board.h"',
            nuttx_include_dirs,
            ("BOARD_CONFLICT_GPIO",),
            "#define BOARD_CONFLICT_GPIO "
            "(GPIO_P9_3_OUTPUT_HIGH | RZV_GPIO_PERIPH)",
        )
        self.assertNotEqual(
            0,
            conflict_result.returncode,
            "semantic check accepted conflicting output/peripheral mode bits",
        )

    def test_gpio_only_macros_remain_gpio_mode(self):
        nuttx_definitions = macro_definitions(NUTTX_BOARD_HEADER)

        for macro in (
            "BOARD_LED1_GPIO",
            "BOARD_LED2_GPIO",
            "BOARD_LED3_GPIO",
            "BOARD_LED4_GPIO",
            "BOARD_MPU9250_CS_GPIO",
            "BOARD_MPU9250_DRDY_GPIO",
            "BOARD_P5_0_GPIO",
            "BOARD_P7_4_GPIO",
            "BOARD_SCI0_I2C_SCL_RESET_GPIO",
            "BOARD_SCI0_I2C_SDA_RESET_GPIO",
            "BOARD_SCI1_I2C_SCL_RESET_GPIO",
            "BOARD_SCI1_I2C_SDA_RESET_GPIO",
            "BOARD_SCI2_I2C_SCL_RESET_GPIO",
            "BOARD_SCI2_I2C_SDA_RESET_GPIO",
            "BOARD_SCI3_I2C_SCL_RESET_GPIO",
            "BOARD_SCI3_I2C_SDA_RESET_GPIO",
            "BOARD_SCI7_I2C_SCL_RESET_GPIO",
            "BOARD_SCI7_I2C_SDA_RESET_GPIO",
        ):
            with self.subTest(macro=macro):
                assert_not_peripheral_mode(
                    self, nuttx_definitions, macro
                )

        px4_definitions = macro_definitions(PX4_BOARD_HEADER)

        for macro in (
            "BOARD_MPU9250_CS_GPIO",
            "BOARD_MPU9250_DRDY_GPIO",
        ):
            with self.subTest(macro=macro):
                assert_not_peripheral_mode(
                    self, px4_definitions, macro
                )

        spi_source = (
            NUTTX_BOARD_DIR / "src/rzv2h_spi.c"
        ).read_text(encoding="utf-8")
        spi_cs = re.search(
            r"#define\s+SPI0_CS0_GPIO\s+(.+?)(?:\n\n|/\*)",
            spi_source,
            re.S,
        )
        self.assertIsNotNone(spi_cs)
        self.assertNotIn("RZV_GPIO_PERIPH", spi_cs.group(1))
        self.assertIn("RZV_GPIO_OUTPUT", spi_cs.group(1))

    def test_source_callers_do_not_append_peripheral_mode(self):
        caller_composition = re.compile(
            r"(?:BOARD_[A-Z0-9_]+_GPIO|GPIO_[A-Z0-9_]+)"
            r"\s*\|\s*RZV_GPIO_PERIPH"
            r"|RZV_GPIO_PERIPH\s*\|\s*"
            r"(?:BOARD_[A-Z0-9_]+_GPIO|GPIO_[A-Z0-9_]+)"
        )
        source_paths = []

        for directory in (
            ROOT / "boards/renesas/rdk-rzv2h/src",
            NUTTX_BOARD_DIR / "src",
            ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv",
        ):
            source_paths.extend(directory.rglob("*.c"))
            source_paths.extend(directory.rglob("*.cpp"))

        for path in source_paths:
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(caller_composition.search(
                    path.read_text(encoding="utf-8")
                ))


if __name__ == "__main__":
    unittest.main()
