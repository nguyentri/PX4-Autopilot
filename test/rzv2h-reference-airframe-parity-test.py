#!/usr/bin/env python3
"""Check that the default and demo airframe chain keeps the reference drone's values.

rcS runs rc.board_defaults before the airframe selected by SYS_AUTOSTART, and
both write with "param set-default", so the airframe chain is the last writer.
The FreeRTOS reference never runs an airframe: its board command list is final
and every other parameter keeps the PX4 compiled default. The default target's
board command list is the in-tree mirror of that list.

This test evaluates the board command list and then the selected airframe chain
with a small model of the NSH subset these scripts use, and fails on any other
construct so that a new one cannot slip past the model.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT_D = ROOT / "ROMFS/px4fmu_common/init.d"
BOARD = ROOT / "boards/renesas/rdk-rzv2h"
REFERENCE = ROOT / "refs/rzv2h_drone_px4-dev/px4/boards/renesas/rzv/init/rc.board_defaults.cmds"
AIRFRAME_ID = 4210
AIRFRAME = INIT_D / "airframes/4210_rzv2h_rdk_s500"
ICM45686 = ROOT / "src/drivers/imu/invensense/icm45686"

# Values the port sets on purpose instead of the reference's. The reference
# caps the ICM-45686 FIFO read at 200 Hz for its 1 MHz SPI; SPI0 here runs at
# 20 MHz, so the driver reads its FIFO at the PX4 multicopter 800 Hz.
PORT_VALUES = {"IMU_GYRO_RATEMAX": "800"}


def number(text):
    return float(text.rstrip("f"))


class CompiledDefaults:
    """PX4 compiled defaults from PARAM_DEFINE_* sources and module YAML files."""

    def __init__(self):
        self.cache = {}

    def __getitem__(self, name):
        if name not in self.cache:
            self.cache[name] = self.lookup(name)
        return self.cache[name]

    @staticmethod
    def lookup(name):
        define = re.compile(r"PARAM_DEFINE_(?:INT32|FLOAT)\(\s*" + name + r"\s*,\s*([^)]+)\)")
        for path in (ROOT / "src").rglob("*.c"):
            match = define.search(path.read_text(errors="ignore"))
            if match:
                return match[1].strip()
        key = re.compile(r"^(\s+)" + name + r":\s*$")
        for path in (ROOT / "src").rglob("*.yaml"):
            lines = path.read_text(errors="ignore").splitlines()
            for index, line in enumerate(lines):
                match = key.match(line)
                if not match:
                    continue
                for inner in lines[index + 1:]:
                    indent = len(inner) - len(inner.lstrip())
                    if inner.strip() and indent <= len(match[1]):
                        break
                    found = re.match(r"\s+default:\s*(\S+)\s*$", inner)
                    if found:
                        return found[1]
        raise AssertionError("no compiled default for " + name)


COMPILED = CompiledDefaults()


class Startup:
    """Evaluate the board command list and airframe chain in rcS order."""

    def __init__(self):
        self.values = {}
        self.writes = {}

    def current(self, name):
        return self.values[name] if name in self.values else COMPILED[name]

    def condition(self, words, path):
        negate = words[:1] == ["!"]
        words = words[1:] if negate else words
        if words[:2] == ["param", "compare"] and len(words) == 4:
            result = number(self.current(words[2])) == number(words[3])
        elif words[:2] == ["param", "greater"] and len(words) == 4:
            result = number(self.current(words[2])) > number(words[3])
        elif words[:2] == ["param", "set-default"]:
            result = self.command(words, path)
        else:
            raise AssertionError("unmodelled condition in %s: %s" % (path, " ".join(words)))
        return result != negate

    def command(self, words, path):
        if words[:2] == ["param", "set-default"]:
            operands = [word for word in words[2:] if word != "-s"]
            if len(operands) != 2:
                raise AssertionError("unmodelled param write in %s: %s" % (path, " ".join(words)))
            self.values[operands[0]] = operands[1]
            self.writes.setdefault(operands[0], []).append(path.relative_to(ROOT).as_posix())
            return True
        if words[0] in ("set", "unset"):
            return True
        if words[0] == "." and len(words) == 2 and words[1].startswith("${R}etc/init.d/"):
            self.run(INIT_D / words[1][len("${R}etc/init.d/"):])
            return True
        raise AssertionError("unmodelled command in %s: %s" % (path, " ".join(words)))

    def run(self, path):
        # Each frame is [parent active, this branch active, a branch already taken].
        frames = []
        for raw in path.read_text().splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            words = line.split()
            active = all(frame[0] and frame[1] for frame in frames)
            if words[0] == "if":
                taken = active and self.condition(words[1:], path)
                frames.append([active, taken, taken])
            elif words == ["then"]:
                continue
            elif words == ["else"]:
                frames[-1][1] = not frames[-1][2]
            elif words == ["fi"]:
                frames.pop()
            elif active:
                self.command(words, path)
        if frames:
            raise AssertionError("unterminated if in " + str(path))

    def airframe(self):
        autostart = int(self.current("SYS_AUTOSTART"))
        matches = sorted((INIT_D / "airframes").glob("%d_*" % autostart))
        if len(matches) != 1:
            raise AssertionError("SYS_AUTOSTART %d selects %d airframes" % (autostart, len(matches)))
        before = dict(self.writes)
        self.run(matches[0])
        return {name for name, paths in self.writes.items() if paths != before.get(name)}


def boot(subdir):
    startup = Startup()
    defaults = BOARD / "init" / subdir / "rc.board_defaults.cmds"
    startup.run(defaults)
    board = dict(startup.values)
    chain = startup.airframe()
    return startup, board, chain


def equal(left, right):
    return number(left) == number(right)


def reference_value(name, *sources):
    """The port value, else the first source holding the key, else the compiled default."""
    if name in PORT_VALUES:
        return PORT_VALUES[name]
    for source in sources:
        if name in source:
            return source[name]
    return COMPILED[name]


class AirframeParity(unittest.TestCase):
    def test_default_and_demo_install_and_select_the_reference_airframe(self):
        self.assertEqual(sorted(path.name for path in (INIT_D / "airframes").glob("%d_*" % AIRFRAME_ID)),
                         [AIRFRAME.name])
        header = AIRFRAME.read_text()
        for tag in ("@name ", "@type Quadrotor x", "@class Copter"):
            self.assertIn(tag, header)
        self.assertIn(". ${R}etc/init.d/airframes/4014_s500", header)
        cmake = (INIT_D / "airframes/CMakeLists.txt").read_text()
        self.assertRegex(cmake, r"if\(CONFIG_BOARD_RDK_RZV2H_REFERENCE_AIRFRAME\)\s+(#[^\n]*\s+)?"
                                r"px4_add_romfs_files\(" + AIRFRAME.name + r"\)")
        self.assertIn("config BOARD_RDK_RZV2H_REFERENCE_AIRFRAME", (BOARD / "Kconfig").read_text())
        self.assertIn("CONFIG_BOARD_RDK_RZV2H_REFERENCE_AIRFRAME=y\n",
                      (BOARD / "default.px4board").read_text())
        self.assertNotIn("CONFIG_BOARD_RDK_RZV2H_REFERENCE_AIRFRAME",
                         (BOARD / "demo.px4board").read_text())
        for subdir in ("", "demo"):
            startup, _, _ = boot(subdir)
            self.assertEqual(int(startup.current("SYS_AUTOSTART")), AIRFRAME_ID, subdir or "default")

    def check(self, subdir):
        startup, board, chain = boot(subdir)
        # The reference values: this board's own list (sensor-specific values
        # of the demo win), then the default list that mirrors the reference,
        # then the PX4 compiled default the reference keeps.
        reference = boot("")[1] if subdir else board
        self.assertTrue(chain, "the airframe chain wrote nothing")
        for name in sorted(chain | set(board)):
            expected = reference_value(name, board, reference)
            with self.subTest(target=subdir or "default", parameter=name):
                self.assertTrue(equal(startup.current(name), expected),
                                "%s ends at %s, reference %s (writers: %s)" %
                                (name, startup.current(name), expected, ", ".join(startup.writes[name])))

    def test_gyro_fifo_rate_fits_the_driver_fifo(self):
        # The driver reads whole ODR samples per FIFO read and publishes at most
        # one sensor_gyro_fifo message (32 samples) per read.
        header = (ICM45686 / "ICM45686.hpp").read_text()
        odr = int(re.search(r"FIFO_SAMPLE_DT\{1e6f / (\d+)\.f\}", header)[1])
        rate = int(PORT_VALUES["IMU_GYRO_RATEMAX"])
        self.assertEqual(odr % rate, 0, "FIFO rate must divide the %d Hz ODR" % odr)
        self.assertLessEqual(odr // rate, 32)
        for subdir in ("", "demo"):
            startup, _, _ = boot(subdir)
            self.assertEqual(int(startup.current("IMU_GYRO_RATEMAX")), rate, subdir or "default")

    def test_default_ends_with_the_reference_values(self):
        self.check("")

    def test_demo_ends_with_the_reference_values(self):
        self.check("demo")


class ReferenceMirror(unittest.TestCase):
    """Reads the local-only reference tree; registered in the reference-host group."""

    def test_default_list_mirrors_the_reference_for_every_airframe_key(self):
        reference = {}
        for line in REFERENCE.read_text().splitlines():
            words = line.split("#", 1)[0].split()
            if words[:2] == ["param", "set"] and len(words) == 4:
                reference[words[2]] = words[3]
        startup, _, chain = boot("")
        for name in sorted(chain):
            expected = reference_value(name, reference)
            with self.subTest(parameter=name):
                self.assertTrue(equal(startup.current(name), expected),
                                "%s ends at %s, reference %s" % (name, startup.current(name), expected))


if __name__ == "__main__":
    unittest.main()
