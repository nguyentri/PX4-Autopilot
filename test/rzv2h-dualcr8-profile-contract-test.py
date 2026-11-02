#!/usr/bin/env python3
"""Execute exact-BOM descriptors, startup and output-owner boundaries on host."""
from pathlib import Path
import runpy
import itertools
import tempfile
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'boards/renesas/rdk-rzv2h'
DRONE = runpy.run_path(str(ROOT / 'test/rzv2h-drone-profile-contract-test.py'))
SUPPORT = DRONE['SUPPORT']


class SingleSensorSelection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        DRONE['CompiledSensorSelection'].setUpClass.__func__(cls)

    def compile(self, name, extra=()):
        return DRONE['CompiledSensorSelection'].compile(
            self, name, ['-UCONFIG_RZV2H_DRONE_SENSOR_EXTENSION',
                         '-DCONFIG_RZV2H_SPI0_SINGLE_IMU', *extra])

    def test_one_real_descriptor_only_touches_p93_and_retries_failed_init(self):
        binary, result = self.compile('single-cs')
        self.assertEqual(result.returncode, 0, result.stderr)
        for case in ('selection', 'pin-retry', 'controller-retry'):
            with self.subTest(case=case):
                subprocess.run([str(binary), case], check=True)
        run = subprocess.run([str(binary), 'iterate', '3'], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.strip(), 'cs 3 -> device 0')

    def test_conflicting_pin_owners_and_dma_are_rejected(self):
        for option in ('DRONE_SENSOR_EXTENSION', 'SPI0_HARDWARE_SSL', 'ICM20948_TEST',
                       'SPI_INTERNAL_LOOPBACK_SAMPLE'):
            with self.subTest(option=option):
                _, result = self.compile(option, ['-DCONFIG_RZV2H_' + option])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('exclusive polled P93 ownership', result.stderr)
        for option in ('CONFIG_ARCH_BUTTONS', 'CONFIG_RZV_SPI0_DMA'):
            _, result = self.compile(option, ['-D' + option])
            self.assertNotEqual(result.returncode, 0)

    def test_remote_board_reset_does_not_write_motor_pads(self):
        body = SUPPORT['body']((BOARD / 'src/init.c').read_text(), 'board_on_reset')
        source = '#define CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS 1\n'
        source += '#define __EXPORT\nstatic void up_mdelay(int) {}\n'
        source += 'void board_on_reset(int status) ' + body
        source += '\nint main() { board_on_reset(-1); board_on_reset(0); }\n'
        # A pin write would fail compilation: no pin/HAL declaration exists.
        path = self.directory / 'reset.cpp'
        path.write_text(source)
        binary = self.directory / 'reset'
        subprocess.run([self.compiler, '-Wall', '-Wextra', '-Werror', str(path),
                        '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

    def test_timer_initialization_uses_remote_owner_and_driver_truth_table(self):
        body = SUPPORT['body']((BOARD / 'src/init.c').read_text(), 'board_app_initialize')
        for remote, pwm, dshot in itertools.product((False, True), repeat=3):
            defines = []
            for enabled, name in ((remote, 'BOARD_RDK_RZV2H_REMOTE_OUTPUTS'),
                                  (pwm, 'DRIVERS_PWM_OUT'), (dshot, 'DRIVERS_DSHOT')):
                if enabled:
                    defines.append('-DCONFIG_' + name)
            run = subprocess.run([self.compiler, '-E', '-P', '-x', 'c++', *defines, '-'],
                                 input=body, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual('rdk_rzv2h_timer_initialize();' in run.stdout,
                             not remote and (pwm or dshot), (remote, pwm, dshot))


class ExactProfile(unittest.TestCase):
    def test_duplicate_profile_and_config_are_removed(self):
        self.assertFalse((BOARD / 'dualcr8demo.px4board').exists())
        self.assertFalse((BOARD / 'nuttx-config/dualcr8demo').exists())
        self.assertFalse((BOARD / 'init/dualcr8demo').exists())
        targets = subprocess.check_output(['bash', 'build.sh', '--list'], cwd=ROOT, text=True).splitlines()
        self.assertIn('renesas_rdk-rzv2h_dualcr8', targets)
        self.assertNotIn('renesas_rdk-rzv2h_dualcr8demo', targets)

    def test_startup_attempts_one_imu_and_both_i2c_sensors(self):
        script = BOARD / 'init/dualcr8/rc.board_sensors'
        host = '''
icm45686() { echo "CALL icm45686 $*"; return 1; }
bmm150() { echo "CALL bmm150 $*"; return 0; }
bmp388() { echo "CALL bmp388 $*"; return 0; }
'''
        run = subprocess.run(['bash', '-c', host + '\n. "$1"', 'host', str(script)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout.count('CALL icm45686'), 1)
        for command in ('icm45686 -s -b 0 -c 3 -R 0 start',
                        'bmm150 -I -b 7 -a 0x10 start', 'bmp388 -I -b 7 -a 0x76 start'):
            self.assertIn('CALL ' + command, run.stdout)
        self.assertIn('ERROR [init] ICM45686 failed', run.stdout)
        self.assertNotIn('ina228', script.read_text())

    def test_profile_declares_expected_health_without_selecting_unknown_hardware(self):
        profile = (BOARD / 'dualcr8.px4board').read_text()
        config = (BOARD / 'nuttx-config/dualcr8/defconfig').read_text()
        defaults = (BOARD / 'init/dualcr8/rc.board_defaults.cmds').read_text()
        for symbol in ('PWM_OUT', 'DSHOT', 'POWER_MONITOR_INA228'):
            self.assertIn('CONFIG_DRIVERS_' + symbol + '=n', profile)
        self.assertIn('CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS=y', profile)
        self.assertIn('CONFIG_RZV2H_SPI0_SINGLE_IMU=y', config)
        self.assertNotIn('CONFIG_RZV2H_DRONE_SENSOR_EXTENSION=y', config)
        self.assertNotIn('CONFIG_RZV_GPT6=y', config)
        for symbol in ('BARO', 'GPS', 'MAG', 'NUM_DIST'):
            self.assertIn('param set-default SYS_HAS_' + symbol + ' 1', defaults)
        self.assertIn('param set-default SENS_TFMINI_CFG 401', defaults)
        self.assertIn('set PWM_OUT_START no', defaults)
        self.assertNotIn('BAT1_SOURCE -1', defaults)
        self.assertNotIn('PWM_MAIN_TIM', defaults)


class ExactBuildSelection(unittest.TestCase):
    def test_real_cmake_selection_rejects_profile_prefix_collisions(self):
        source = (ROOT / 'cmake/px4_config.cmake').read_text()
        selection = 'if(NOT PX4_CONFIG_FILE)' + source.split('if(NOT PX4_CONFIG_FILE)', 1)[1]
        selection = selection.split('message(STATUS "PX4 config file:', 1)[0]
        cases = {
            'renesas_rdk-rzv2h_dualcr8': 'dualcr8',
            'renesas_rdk-rzv2h_dualcr8demo': '',
            'renesas_rdk-rzv2h_default': 'default',
            'renesas_rdk-rzv2h': 'default',
            'renesasrdk-rzv2h_dualcr8': 'dualcr8',
            'nuttx_renesas_rdk-rzv2h_dualcr8': 'dualcr8',
            'nuttx_renesas_rdk-rzv2h': 'default',
            'renesas_rdk-rzv2h_dualcr8demo_junk': '',
        }
        with tempfile.TemporaryDirectory(prefix='px4-config-select-') as directory:
            directory = Path(directory)
            result = directory / 'selection.txt'
            script = directory / 'select.cmake'
            script.write_text('set(PX4_SOURCE_DIR "' + str(ROOT) + '")\n' + selection +
                              '\nfile(WRITE "' + str(result) + '" "${LABEL}")\n')
            for name, expected in cases.items():
                with self.subTest(config=name):
                    run = subprocess.run(['cmake', '-DCONFIG=' + name, '-P', str(script)],
                                         cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(result.read_text(), expected)


if __name__ == '__main__':
    unittest.main()
