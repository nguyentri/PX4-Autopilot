#!/usr/bin/env python3
"""Exercise demo startup hooks and their ordering in the shared PX4 boot path."""

import argparse
import json
import lzma
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "boards/renesas/rdk-rzv2h/init/demo"
BUILD_DIR = None
STREAMS = (("HIGHRES_IMU", 10), ("SCALED_PRESSURE", 2),
           ("DISTANCE_SENSOR", 2), ("SERVO_OUTPUT_RAW_0", 2))


class DemoStartup(unittest.TestCase):
    def test_telemetry_ring_can_send_mavlink_ftp(self):
        if BUILD_DIR is None:
            self.skipTest("pass --build-dir to exercise MAVLink serialization")
        body = runpy.run_path(str(ROOT / "test/rzv2h-simple-test-support.py"))["body"]
        source = (ROOT / "src/modules/mavlink/mavlink_main.cpp").read_text()
        ftp_source = (ROOT / "src/modules/mavlink/mavlink_ftp.cpp").read_text()
        config = (INIT.parent.parent / "nuttx-config/demo/defconfig").read_text()
        tx_size = int(re.search(r"(?m)^CONFIG_SCI5_TXBUFSIZE=(\d+)$", config)[1])
        rx_size = int(re.search(r"(?m)^CONFIG_SCI5_RXBUFSIZE=(\d+)$", config)[1])
        resolved = (BUILD_DIR / "NuttX/nuttx/.config").read_text()
        for direction, expected in (("TX", tx_size), ("RX", rx_size)):
            self.assertEqual(int(re.search(
                rf"(?m)^CONFIG_SCI5_{direction}BUFSIZE=(\d+)$", resolved)[1]), expected)
        fixture = r'''
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <common/mavlink.h>
static void pthread_mutex_lock(int *) {}
static unsigned hrt_absolute_time() { return 1; }
class Mavlink {
public:
    unsigned free_bytes;
    int _send_mutex{};
    unsigned _last_write_try_time{};
    struct { unsigned tx_buffer_overruns{}; } _tstatus;
    bool _tx_buffer_low{};
    unsigned get_free_tx_buf() { return free_bytes; }
    void count_txerrbytes(int) {}
    void send_start(int length);
};
class MavlinkFTP {
public:
    struct { bool stream_download{true}; } _session_info;
    unsigned get_size();
};
'''
        fixture += "\nvoid Mavlink::send_start(int length) " + body(source, "Mavlink::send_start")
        fixture += "\nunsigned MavlinkFTP::get_size() " + body(ftp_source, "MavlinkFTP::get_size")
        fixture += r'''
int main(int argc, char **argv) {
    Mavlink link;
    // NuttX FIONSPACE reserves one ring slot to distinguish empty from full.
    link.free_bytes = std::atoi(argv[1]) - 1;
    MavlinkFTP ftp;
    mavlink_file_transfer_protocol_t reply{};
    std::memset(reply.payload, 0xa5, sizeof(reply.payload));
    mavlink_message_t message{};
    mavlink_msg_file_transfer_protocol_encode(1, 1, &message, &reply);
    unsigned char packet[MAVLINK_MAX_PACKET_LEN];
    const unsigned length = mavlink_msg_to_send_buffer(packet, &message);
    link.send_start(length);
    if (link._tx_buffer_low || link.free_bytes < ftp.get_size()) {
        std::fprintf(stderr, "SCI5 free=%u cannot send FTP wire=%u / burst requirement=%u\n",
                     link.free_bytes, length, ftp.get_size());
        return 1;
    }
    if (link.free_bytes < MAVLINK_MAX_PACKET_LEN || std::atoi(argv[2]) - 1 < MAVLINK_MAX_PACKET_LEN) {
        std::fprintf(stderr, "SCI5 cannot buffer a maximum signed MAVLink frame\n");
        return 2;
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="rzv2h-mavlink-ring-") as directory:
            directory = Path(directory)
            code = directory / "ftp-ring.cpp"
            code.write_text(fixture)
            binary = directory / "ftp-ring"
            compile_result = subprocess.run(
                ["c++", "-std=c++14", "-Wno-address-of-packed-member", "-I",
                 str(BUILD_DIR / "mavlink"), str(code), "-o", str(binary)],
                capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(binary), str(tx_size), str(rx_size)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_reconfiguration_clears_the_constrained_flash_cache(self):
        # Execute the real option-handling block across successive CMake runs.
        source = (ROOT / "cmake/kconfig.cmake").read_text()
        block = "if(CONSTRAINED_FLASH)\n" + source.split(
            "\tif(CONSTRAINED_FLASH)\n", 1)[1].split("\n\tif(NO_HELP)", 1)[0]
        with tempfile.TemporaryDirectory(prefix="rzv2h-flash-config-") as directory:
            directory = Path(directory)
            (directory / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(flash_cache NONE)\n" +
                block + '\nfile(WRITE "${CMAKE_BINARY_DIR}/flash.txt" '
                '"${px4_constrained_flash_build}")\n')
            for setting, expected in (("ON", "1"), ("OFF", "0"), ("ON", "1")):
                result = subprocess.run(
                    ["cmake", "-S", str(directory), "-B", str(directory / "build"),
                     "-DCONSTRAINED_FLASH=" + setting], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((directory / "build/flash.txt").read_text(), expected)

    def run_hook(self, filename, harness, arguments=()):
        result = subprocess.run(
            ["bash", "-c", harness + '\n. "$1"', "host", str(INIT / filename),
             *arguments], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_stream_requests_are_independent_and_report_failures(self):
        harness = '''
failed_stream=$2
mavlink() {
    echo "CALL $*"
    [ "$5" != "$failed_stream" ]
}
'''
        for failed in ("none", *(name for name, _ in STREAMS)):
            with self.subTest(failed=failed):
                output = self.run_hook("rc.board_extras", harness, [failed])
                calls = [line for line in output.splitlines() if line.startswith("CALL ")]
                self.assertEqual(calls, [
                    f"CALL stream -d /dev/ttyS5 -s {name} -r {rate}"
                    for name, rate in STREAMS])
                errors = [line for line in output.splitlines() if "ERROR [init]" in line]
                self.assertEqual(len(errors), 0 if failed == "none" else 1)
                if errors:
                    self.assertIn(failed, errors[0])

    def test_defaults_enable_qgc_tests_without_overwriting_user_choice(self):
        harness = '''
declare -A params
params[COM_MOT_TEST_EN]=$2
set() { export "$1=$2"; }
param() {
    [ "$1" = set-default ] || return 1
    shift
    # DShot is not linked into this demo image.
    [ "$1" != -s ] || return 1
    if [ -z "${params[$1]}" ]; then params[$1]=$2; fi
}
'''
        script = '''
. "$1"
printf 'test=%s link=%s mode=%s flow=%s lidar=%s baud=%s pwm=%s stick=%s\n' \
    "${params[COM_MOT_TEST_EN]}" "${params[MAV_0_CONFIG]}" \
    "${params[MAV_0_MODE]}" "${params[MAV_0_FLOW_CTRL]}" \
    "${params[SENS_TFMINI_CFG]}" "${params[SER_TEL1_BAUD]}" "$DSHOT_START" "${params[COM_RC_IN_MODE]}"
'''
        for choice, expected in (("", "1"), ("0", "0")):
            with self.subTest(user_motor_test=choice):
                result = subprocess.run(
                    ["bash", "-c", harness + script, "host",
                     str(INIT / "rc.board_defaults.cmds"), choice],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"test={expected} link=101 mode=0 flow=0 lidar=401 "
                              "baud=57600 pwm=no stick=4", result.stdout)

    def test_both_bus_sensors_are_attempted_even_if_one_fails(self):
        # The harness substitutes only driver exits, never sensor data.
        for imu_exit, baro_exit in ((0, 0), (1, 0), (0, 1), (1, 1)):
            harness = f'''
icm45686() {{ echo "CALL icm45686 $*"; return {imu_exit}; }}
bmp280() {{ echo "CALL bmp280 $*"; return {baro_exit}; }}
'''
            with self.subTest(imu=imu_exit, baro=baro_exit):
                output = self.run_hook("rc.board_sensors", harness)
                self.assertIn("CALL icm45686 -s -b 0 -c 3 -R 0 start", output)
                self.assertIn("CALL bmp280 -I -b 7 -a 0x76 start", output)
                self.assertEqual(output.count("ERROR [init]"), imu_exit + baro_exit)

    def test_hook_runs_after_serial_and_before_boot_complete(self):
        rcs = (ROOT / "ROMFS/px4fmu_common/init.d/rcS").read_text()
        self.assertLess(rcs.index(". ${R}etc/init.d/rc.serial"),
                        rcs.index(". $BOARD_RC_EXTRAS"))
        self.assertLess(rcs.index(". $BOARD_RC_EXTRAS"), rcs.index("mavlink boot_complete"))
        self.assertIn("pwm_out start", rcs)
        self.assertIn("CONFIG_BOARD_INIT_SUBDIR=\"demo\"",
                      (INIT.parent.parent / "demo.px4board").read_text())

    def test_hooks_use_nsh_syntax_and_never_drive_motors_at_boot(self):
        for script in INIT.iterdir():
            if not script.is_file():
                continue
            for line in script.read_text().splitlines():
                tokens = shlex.split(line, comments=True)
                if not tokens:
                    continue
                self.assertNotIn(tokens[0], ("for", "function", "actuator_test"))
                self.assertNotEqual(tokens[:2], ["commander", "arm"])
                self.assertLess(len(line), 128)
                if tokens[0] == "if":
                    tokens = tokens[1:]
                self.assertLessEqual(len(tokens), 15)

    def test_generated_romfs_contains_demo_hooks_and_serial_drivers(self):
        if BUILD_DIR is None:
            self.skipTest("pass --build-dir to check generated ROMFS")
        init = BUILD_DIR / "etc/init.d"
        for name in ("rc.board_defaults.cmds", "rc.board_sensors", "rc.board_extras"):
            source = [line.strip() for line in (INIT / name).read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
            generated = [line.strip() for line in (init / name).read_text().splitlines()
                         if line.strip() and not line.lstrip().startswith("#")]
            self.assertEqual(source, generated)
        serial = (init / "rc.serial").read_text()
        self.assertIn("set PRT SENS_TFMINI_CFG", serial)
        self.assertIn("tfmini start -d ${SERIAL_DEV}", serial)
        self.assertIn("set PRT MAV_0_CONFIG", serial)
        self.assertIn("mavlink start ${MAV_ARGS} -x", serial)
        wrapper = (init / "rc.board_defaults").read_text()
        self.assertIn("set RZV_DEFAULTS ${R}etc/init.d/rc.board_defaults.cmds", wrapper)
        self.assertIn(". $RZV_DEFAULTS", wrapper)
        defaults = (init / "rc.board_defaults.cmds").read_text()
        self.assertIn("param set-default COM_MOT_TEST_EN 1", defaults)
        self.assertIn("param set-default MAV_0_CONFIG 101", defaults)

    def test_qgc_actuator_metadata_is_served_from_the_firmware(self):
        if BUILD_DIR is None:
            self.skipTest("pass --build-dir to check embedded metadata")
        extras = BUILD_DIR / "etc/extras"
        general = json.loads(lzma.decompress(
            (extras / "component_general.json.xz").read_bytes()))
        types = {item["type"]: item for item in general["metadataTypes"]}
        for type_id, filename in ((1, "parameters.json.xz"),
                                  (4, "all_events.json.xz"), (5, "actuators.json.xz")):
            self.assertEqual(types[type_id]["uri"], "mftp://etc/extras/" + filename)
            content = json.loads(lzma.decompress((extras / filename).read_bytes()))
            self.assertTrue(content, filename)
            if type_id == 1:
                names = {param["name"] for param in content["parameters"]}
                self.assertTrue({"SYS_AUTOSTART", "COM_RC_IN_MODE"} <= names)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path)
    args, remaining = parser.parse_known_args()
    BUILD_DIR = args.build_dir
    unittest.main(argv=[__file__, *remaining])
