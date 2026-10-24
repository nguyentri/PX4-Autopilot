#!/usr/bin/env python3
"""Execute the complete GPT lower half with real NuttX PWM declarations.

Only architecture/clock/IRQ/MMIO boundaries are replaced. These host checks
prove dispatch and driver behavior; they do not establish electrical output,
CPG monitor behavior, board pin admission, or physical qualification.
"""

from itertools import product
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
ARCH = NUTTX / "arch/arm/src/rzv"


class GPTChannelRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compiler = shutil.which("cc")
        if cls.compiler is None:
            raise RuntimeError("a host C compiler (cc) is required")
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-gpt-channels-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = cls.directory = Path(cls.temporary.name)
        # Use the real nuttx/timers/pwm.h, with only its platform dependencies
        # shimmed. -idirafter keeps host libc headers ahead of NuttX libc.
        headers = {
            "nuttx/config.h": "",
            "nuttx/compiler.h": "#define FAR\n#define CODE\n"
                                 "#define UNUSED(x) ((void)(x))\n#define OK 0\n",
            "nuttx/arch.h": "",
            "nuttx/irq.h": "typedef unsigned int irqstate_t;\n",
            "nuttx/fs/ioctl.h": "",
            "fixedmath.h": "typedef uint32_t ub16_t;\n#define b16ONE 65536u\n",
            "arm_internal.h": "",
        }
        for name, content in headers.items():
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        cls.binaries = {}

    @classmethod
    def binary(cls, multichannel: bool, pulsecount: bool, mask: int,
               sample_api: bool) -> Path:
        key = multichannel, pulsecount, mask, sample_api
        if key in cls.binaries:
            return cls.binaries[key]
        binary = cls.directory / (f"multi{int(multichannel)}-pulse{int(pulsecount)}-"
                                  f"{mask:04x}-api{int(sample_api)}")
        command = [cls.compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-parameter", "-I", str(cls.directory),
                   "-I", str(ARCH), "-idirafter", str(NUTTX / "include"),
                   "-DCONFIG_RZV_PWM", "-DCONFIG_PWM_NCHANNELS=3",
                   f"-DTEST_ENABLED_MASK={mask}"]
        if multichannel:
            command.append("-DCONFIG_PWM_MULTICHAN")
        if pulsecount:
            command.append("-DCONFIG_PWM_PULSECOUNT")
        if sample_api:
            command.append("-DCONFIG_RZV2H_SAMPLE_TEST_API")
        for channel in range(16):
            if mask & (1 << channel):
                command.append(f"-DCONFIG_RZV_GPT{channel}")
        command += [str(ROOT / "test/rzv2h-gpt-channel-runtime-harness.c"),
                    "-o", str(binary)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise AssertionError(f"host GPT compilation failed ({key}):\n{result.stderr}")
        cls.binaries[key] = binary
        return binary

    def exercise(self, mask: int, sample_api: bool = True) -> None:
        for multichannel, pulsecount, output in product((False, True), (False, True), (0, 1)):
            with self.subTest(mask=f"{mask:04x}", multichannel=multichannel,
                              pulsecount=pulsecount, output=output, sample_api=sample_api):
                # Each A-first/B-first run has fresh production static state.
                binary = self.binary(multichannel, pulsecount, mask, sample_api)
                result = subprocess.run(
                    [str(binary), str(output)],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_sixteen_instances_outputs_and_lifecycles(self) -> None:
        self.exercise(0xFFFF)

    def test_each_channel_alone_and_other_channels_disabled(self) -> None:
        for channel in range(16):
            self.exercise(1 << channel)

    def test_sparse_interleaving_across_both_units(self) -> None:
        self.exercise(0x9009)

    def test_no_configured_channels_has_no_side_effects(self) -> None:
        self.exercise(0)

    def test_sample_api_disabled_preserves_production_behavior(self) -> None:
        self.exercise(0xFFFF, sample_api=False)


if __name__ == "__main__":
    unittest.main()
