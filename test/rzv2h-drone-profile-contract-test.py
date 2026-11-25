#!/usr/bin/env python3
"""Exercise actual board source selection and sensor descriptor dispatch."""

from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "boards/renesas/rdk-rzv2h/src"
SUPPORT = runpy.run_path(str(ROOT / "test/rzv2h-board-test-support.py"))
NUTTX_BOARD = ROOT / "platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h"


class BoardSourceSelection(unittest.TestCase):
    def sources(self, *drivers):
        # Execute the real source-selection statements before add_library;
        # CMake script mode cannot create targets.
        source = (BOARD / "CMakeLists.txt").read_text().split("add_library(", 1)[0]
        with tempfile.TemporaryDirectory(prefix="rzv2h-board-sources-") as directory:
            directory = Path(directory)
            output = directory / "sources.txt"
            script = directory / "sources.cmake"
            script.write_text(source + '\nfile(WRITE "' + str(output) +
                              '" "${drivers_board_sources}")\n')
            subprocess.run(["cmake", *["-D" + option + "=ON" for option in drivers],
                            "-P", str(script)], check=True, capture_output=True, text=True)
            return output.read_text().split(";")

    def test_new_driver_modules_declare_native_device_dependency(self):
        drivers = ("barometer/bmp388", "imu/invensense/icm45686",
                   "magnetometer/bosch/bmm150", "power_monitor/ina228")
        with tempfile.TemporaryDirectory(prefix="rzv2h-driver-deps-") as directory:
            directory = Path(directory)
            for driver in drivers:
                with self.subTest(driver=driver):
                    output = directory / "arguments.txt"
                    script = directory / "module.cmake"
                    script.write_text('macro(px4_add_module)\nfile(WRITE "' + str(output) +
                                      '" "${ARGN}")\nendmacro()\n' +
                                      (ROOT / "src/drivers" / driver / "CMakeLists.txt").read_text())
                    subprocess.run(["cmake", "-P", str(script)], check=True, capture_output=True)
                    arguments = output.read_text().split(";")
                    self.assertIn("drivers__device", arguments[arguments.index("DEPENDS") + 1:])

    def test_new_imu_links_spi_descriptor(self):
        self.assertIn("spi.cpp", self.sources("CONFIG_DRIVERS_IMU_INVENSENSE_ICM45686"))

    def test_each_shared_i2c_driver_links_i2c_descriptor(self):
        for driver in ("CONFIG_DRIVERS_BAROMETER_BMP388",
                       "CONFIG_DRIVERS_MAGNETOMETER_BOSCH_BMM150",
                       "CONFIG_DRIVERS_POWER_MONITOR_INA228"):
            with self.subTest(driver=driver):
                self.assertIn("i2c.cpp", self.sources(driver))

    def test_legacy_drivers_keep_their_descriptors(self):
        for driver in ("CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250",
                       "CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948"):
            self.assertIn("spi.cpp", self.sources(driver))
        self.assertIn("i2c.cpp", self.sources("CONFIG_DRIVERS_BAROMETER_BMP280"))

    def test_driver_free_profile_does_not_link_sensor_tables(self):
        sources = self.sources()
        self.assertNotIn("spi.cpp", sources)
        self.assertNotIn("i2c.cpp", sources)

    def test_multiple_i2c_drivers_link_one_table(self):
        sources = self.sources("CONFIG_DRIVERS_BAROMETER_BMP388",
                               "CONFIG_DRIVERS_MAGNETOMETER_BOSCH_BMM150",
                               "CONFIG_DRIVERS_POWER_MONITOR_INA228")
        self.assertEqual(sources.count("i2c.cpp"), 1)


class CompiledSensorSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-drone-cs-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        SUPPORT["host_headers"](cls.directory)
        source = (NUTTX_BOARD / "src/rzv2h_spi.c").read_text()
        source = re.sub(r"^\s*#\s*include[^\n]*$", "", source, flags=re.M)
        (cls.directory / "board-select-under-test.inc").write_text(source)
        init = (BOARD / "init.c").read_text()
        (cls.directory / "board-gpio-under-test.inc").write_text(
            "static void rdk_rzv2h_gpio_initialize(void) " +
            SUPPORT["body"](init, "rdk_rzv2h_gpio_initialize"))
        cls.compiler = shutil.which("c++")
        if cls.compiler is None:
            raise RuntimeError("a host C++ compiler is required")

    def compile(self, name, extra=()):
        binary = self.directory / name
        command = [self.compiler, "-std=c++14", "-Wall", "-Wextra", "-Werror",
                   "-Wno-unused-parameter", "-D__PX4_NUTTX", "-DCONFIG_SPI",
                   "-DCONFIG_RZV_SPI", "-DCONFIG_RZV_SPI0", "-DCONFIG_SPI_EXCHANGE",
                   "-DCONFIG_RZV2H_DRONE_SENSOR_EXTENSION",
                   "-DCONFIG_DRIVERS_IMU_INVENSENSE_ICM45686", *extra,
                   "-include", str(NUTTX_BOARD / "include/board.h")]
        for include in (self.directory, BOARD, SUPPORT["HAL"], SUPPORT["RZV"],
                        ROOT / "platforms/common/include", ROOT / "src"):
            command += ["-I", str(include)]
        command += [str(ROOT / "test/rzv2h-drone-spi-host-fixture.cpp"), "-o", str(binary)]
        result = subprocess.run(command, capture_output=True, text=True)
        return binary, result

    def test_actual_descriptors_drive_only_their_cs_and_retire_unknown_ids(self):
        binary, result = self.compile("selection")
        self.assertEqual(result.returncode, 0, result.stderr)
        subprocess.run([str(binary), "selection"], check=True)

    def test_startup_chip_selects_resolve_through_the_bus_iterator(self):
        script = (BOARD.parent / "init/rc.board_sensors").read_text()
        pins = re.findall(r"^\s*if icm45686 -s -b 0 -c (\d+) -R 0 start", script, flags=re.M)
        self.assertEqual(pins, ["3", "4", "5"])
        binary, result = self.compile("iterate")
        self.assertEqual(result.returncode, 0, result.stderr)
        run = subprocess.run([str(binary), "iterate", *pins], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.splitlines(),
                         [f"cs {pin} -> device {index}" for index, pin in enumerate(pins)])

    def test_failed_initialization_is_not_published_and_can_retry(self):
        binary, result = self.compile("retry")
        self.assertEqual(result.returncode, 0, result.stderr)
        for scenario in ("pin-retry", "controller-retry"):
            with self.subTest(scenario=scenario):
                subprocess.run([str(binary), scenario], check=True)

    def test_conflicting_layout_owners_are_rejected(self):
        for option in ("CONFIG_RZV2H_SPI0_HARDWARE_SSL", "CONFIG_RZV2H_ICM20948_TEST",
                       "CONFIG_ARCH_BUTTONS", "CONFIG_RZV2H_SPI_INTERNAL_LOOPBACK_SAMPLE",
                       "CONFIG_RZV_SPI0_DMA"):
            with self.subTest(option=option):
                _, result = self.compile(option, ["-D" + option])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("The drone extension requires GPIO CS", result.stderr)

    def test_legacy_imu_is_not_silently_combined_with_extension(self):
        for driver in ("MPU9250", "ICM20948"):
            with self.subTest(driver=driver):
                _, result = self.compile(driver, ["-DCONFIG_DRIVERS_IMU_INVENSENSE_" + driver])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ICM45686 without legacy IMU drivers", result.stderr)


class ProfileStartup(unittest.TestCase):
    def test_shared_dshot_profile_selects_distinct_rcpu_dma_channels(self):
        config = (BOARD.parent / "nuttx-config/nsh/defconfig").read_text()
        values = dict(re.findall(r"(?m)^CONFIG_RZV_DMAC_(\w+)_CHANNEL=(-?\d+)$",
                                 config))
        channels = []
        for gpt in (6, 7, 9, 10):
            key = f"GPT{gpt}"
            self.assertIn(key, values, "DShot must not inherit the generic DMA unit")
            channel = int(values[key])
            self.assertIn(channel // 16, (3, 4), "RDK GPT requires its RCPU DMA path")
            channels.append(channel)
        self.assertEqual(len(set(channels)), 4, "DShot DMA channels must be unique")
        for key in ("SPI0_TX", "SPI0_RX"):
            if key in values and int(values[key]) >= 0:
                self.assertNotIn(int(values[key]), channels, "SPI/DShot DMA overlap")

    def init_directory(self, subdir):
        source = (ROOT / "ROMFS/CMakeLists.txt").read_text()
        source = source.split("# board custom init files", 1)[1].split("set(OPTIONAL_BOARD_RC)", 1)[0]
        with tempfile.TemporaryDirectory(prefix="rzv2h-init-select-") as directory:
            directory = Path(directory)
            output = directory / "path.txt"
            script = directory / "init.cmake"
            script.write_text('set(PX4_BOARD_DIR "' + str(BOARD.parent) + '")\n' +
                              source + '\nfile(WRITE "' + str(output) + '" "${board_init_dir}")\n')
            result = subprocess.run(["cmake", "-DCONFIG_BOARD_INIT_SUBDIR=" + subdir,
                                     "-P", str(script)], capture_output=True, text=True)
            return result, output.read_text() if output.exists() else None

    def test_standard_profile_keeps_original_hooks(self):
        result, path = self.init_directory("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path, str(BOARD.parent / "init"))

    def test_extension_profile_selects_its_own_hooks(self):
        result, path = self.init_directory("dualcr8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path, str(BOARD.parent / "init/dualcr8"))

    def test_bad_or_missing_hook_directory_is_rejected(self):
        for name in ("../other", "/tmp", "missing-extension"):
            with self.subTest(name=name):
                result, _ = self.init_directory(name)
                self.assertNotEqual(result.returncode, 0)

    def test_startup_attempts_each_sensor_and_reports_individual_failures(self):
        script = BOARD.parent / "init/rc.board_sensors"
        host = '''
icm45686() { echo "CALL icm45686 $*"; [ "$5" != 4 ]; }
bmm150() { echo "CALL bmm150 $*"; return 1; }
bmp388() { echo "CALL bmp388 $*"; return 0; }
ina228() { echo "CALL ina228 $*"; return 0; }
'''
        result = subprocess.run(["bash", "-c", host + '\n. "$1"', "host", str(script)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for cs in (3, 4, 5):
            self.assertIn(f"CALL icm45686 -s -b 0 -c {cs} -R 0 start", result.stdout)
        for driver, address in (("bmm150", "0x10"), ("bmp388", "0x76"), ("ina228", "0x45")):
            self.assertIn(f"CALL {driver} -I -b 7 -a {address} start", result.stdout)
        self.assertIn("ERROR [init] BMM150 failed", result.stdout)
        self.assertIn("ERROR [init] ICM45686 failed on SPI0 CS pin 4", result.stdout)
        self.assertNotIn(" -P", result.stdout)

    def test_sensor_startup_uses_supported_nsh_control_syntax(self):
        script = (BOARD.parent / "init/rc.board_sensors").read_text()
        # Native NSH supports if/while/until; it has no POSIX for-loop parser
        # or builtin. Bash execution alone cannot establish NSH compatibility.
        parser = (ROOT / "platforms/nuttx/NuttX/apps/nshlib/nsh_parse.c").read_text()
        self.assertNotIn('strcmp(cmd, "for")', parser)
        for line in script.splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                self.assertIn(line.split()[0], ("if", "then", "else", "fi", "echo"))

    def test_integrated_profiles_parse_the_px4_startup_script(self):
        # NSH keeps one if-stack across sourced scripts and silently skips
        # lines past its limits, so a short config breaks rcS mid-boot.
        def needs(script, depth, seen):
            deepest, words, width = depth, 0, 0
            for line in script.read_text().splitlines():
                # NSH drops trailing comments, keeps a quoted string as one
                # argument and counts the command after "if" against the cap.
                tokens = shlex.split(line, comments=True)
                if not tokens:
                    continue
                command = tokens[1:] if tokens[0] in ("if", "while", "until") else tokens
                words, width = max(words, len(command)), max(width, len(line))
                if tokens[0] == "if":
                    depth += 1
                    deepest = max(deepest, depth)
                elif tokens[0] == "fi":
                    depth -= 1
                elif tokens[0] == "." and len(tokens) > 1:
                    name = tokens[1].rsplit("/", 1)[-1]
                    child = next((root / name for root in roots if (root / name).exists()), None)
                    if child and child not in seen:
                        inner = needs(child, depth, seen | {child})
                        deepest, words, width = (max(deepest, inner[0]), max(words, inner[1]),
                                                 max(width, inner[2]))
            return deepest, words, width

        for label, init_subdir in (("nsh", ""), ("dualcr8", "dualcr8"), ("demo", "demo")):
            roots = (BOARD.parent / "init" / init_subdir,
                     ROOT / "ROMFS/px4fmu_common/init.d")
            deepest, words, width = needs(roots[1] / "rcS", 0, frozenset())
            self.assertGreaterEqual(deepest, 7)
            config = (BOARD.parent / "nuttx-config" / label / "defconfig").read_text()

            def value(name):
                match = re.search(rf"(?m)^CONFIG_{name}=(\d+)$", config)
                self.assertIsNotNone(match, f"{label} must reserve {name} for full PX4 startup")
                return int(match.group(1))

            with self.subTest(profile=label):
                self.assertLessEqual(deepest, value("NSH_NESTDEPTH") - 1)
                self.assertLessEqual(words, value("NSH_MAXARGUMENTS"))
                self.assertLess(width, value("NSH_LINELEN"))
                self.assertGreaterEqual(value("SYSTEM_NSH_STACKSIZE"), 3072)

    def test_extension_config_is_separate_from_working_samples(self):
        # The reference drone is the CR8-0 default: top-level init hooks and the
        # nsh defconfig. Bench variants never enable the three-IMU extension.
        profile = (BOARD.parent / "default.px4board").read_text()
        config = (BOARD.parent / "nuttx-config/nsh/defconfig").read_text()
        self.assertNotIn("CONFIG_BOARD_INIT_SUBDIR", profile)
        self.assertIn('CONFIG_BOARD_SERIAL_EXT2="/dev/ttyS4"', profile)
        self.assertIn("CONFIG_RZV2H_DRONE_SENSOR_EXTENSION=y", config)
        self.assertNotIn("CONFIG_RZV_SPI0_DMA=y", config)
        # The reference drone reaches the CA55 XRCE-DDS agent over OpenAMP;
        # raw CR8-CR8 IPC stays off because the two are exclusive on CR8-0.
        self.assertIn("CONFIG_RZV_OPENAMP=y", config)
        self.assertIn("CONFIG_RZV_RPMSG_UXRCE=y", config)
        self.assertNotIn("CONFIG_RZV_IPC_RAW=y", config)
        for name in ("demo", "demosih", "dualcr8"):
            self.assertNotIn("CONFIG_RZV2H_DRONE_SENSOR_EXTENSION=y",
                             (BOARD.parent / "nuttx-config" / name / "defconfig").read_text())

class CompiledDescriptorContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-spi0-descriptor-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        SUPPORT["host_headers"](cls.directory)

    def test_real_single_legacy_imu_tables(self):
        # spi.cpp keeps the single-IMU MPU9250/ICM20948 P93 tables; no shipped
        # profile selects them, but the source must stay compilable and exclusive.
        for label, driver in (("icm20948", "ICM20948"), ("mpu9250", "MPU9250"),
                              ("mpu9250-dshot", "MPU9250")):
            with self.subTest(label=label):
                defines = ["CONFIG_DRIVERS_IMU_INVENSENSE_" + driver]
                if label.endswith("dshot"):
                    defines.append("CONFIG_DRIVERS_DSHOT")
                binary, result = SUPPORT["compile_descriptor"](self.directory, label, defines)
                self.assertEqual(result.returncode, 0, result.stderr)
                subprocess.run([str(binary)], check=True)

    def test_both_physical_imu_choices_are_rejected(self):
        _, result = SUPPORT["compile_descriptor"](self.directory, "both", [
            "CONFIG_DRIVERS_IMU_INVENSENSE_ICM20948", "CONFIG_DRIVERS_IMU_INVENSENSE_MPU9250"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SPI0/P93 supports one IMU", result.stderr)

    def test_table_without_a_sensor_choice_is_rejected(self):
        _, result = SUPPORT["compile_descriptor"](self.directory, "neither", [])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("The sensor SPI table requires an enabled IMU driver", result.stderr)

    def test_actual_guard_preserves_live_irq_owner_on_repeated_initialization(self):
        binary = SUPPORT["compile_irq"](self.directory)
        subprocess.run([str(binary)], check=True)


class SharedBoardSourceContracts(unittest.TestCase):
    def test_discovered_targets_match_readme(self):
        targets = subprocess.check_output(
            ["bash", str(ROOT / "build.sh"), "--list"], cwd=ROOT, text=True
        ).splitlines()
        rzv2h = [name for name in targets if name.startswith("renesas_rdk-rzv2h")]
        for retired in ("core_only", "simple", "sih", "drone", "dshot"):
            self.assertNotIn("renesas_rdk-rzv2h_" + retired, rzv2h)
        documented = re.search(
            r"### Build Targets\s+[\s\S]*?```text\s+([\s\S]*?)```", SUPPORT["read"]("README.md")
        )
        self.assertIsNotNone(documented)
        self.assertEqual(targets, documented.group(1).strip().splitlines())

    def test_gpio_irq_guard_precedes_all_pin_and_spi_setup(self):
        source = SUPPORT["read"]("boards/renesas/rdk-rzv2h/src/init.c")
        initialize = SUPPORT["body"](source, "board_app_initialize")
        call = initialize.index("rdk_rzv2h_gpio_irq_initialize_once()")
        self.assertLess(initialize.index("px4_platform_init()"), call)
        self.assertLess(call, initialize.index("rdk_rzv2h_gpio_initialize()"))
        self.assertLess(call, initialize.index("board_spi_initialize()"))
        self.assertIn("CONFIG_RZV_GPIO_IRQ", source)
        pins = SUPPORT["body"](source, "rdk_rzv2h_gpio_initialize")
        self.assertIn("px4_arch_configgpio(BOARD_ICM20948_DRDY_GPIO | RZV_GPIO_PULLUP)", pins)

    def test_board_init_keeps_physical_timer_setup_driver_gated(self):
        source = SUPPORT["read"]("boards/renesas/rdk-rzv2h/src/init.c")
        self.assertRegex(source, re.compile(
            r"#if defined\(CONFIG_DRIVERS_PWM_OUT\) \|\| defined\(CONFIG_DRIVERS_DSHOT\).*?"
            r"rdk_rzv2h_timer_initialize\(\);.*?#endif", re.DOTALL))

    def test_sih_modules_declare_their_direct_library_dependencies(self):
        # demosih links simulator_sih and sensor_mag_sim.
        self.assertIn("world_magnetic_model",
                      SUPPORT["read"]("src/modules/simulation/sensor_mag_sim/CMakeLists.txt"))
        self.assertIn("lat_lon_alt",
                      SUPPORT["read"]("src/modules/simulation/simulator_sih/CMakeLists.txt"))


if __name__ == "__main__":
    unittest.main()
