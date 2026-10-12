#!/usr/bin/env python3
"""Compile the production BMP388 reset method with a controlled bus boundary."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "src/drivers/barometer/bmp388"


class ResetContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-bmp-reset-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = (DRIVER / "bmp388.cpp").read_text()
        start = source.index("bool\nBMP388::soft_reset()")
        end = source.index("\n/*", start)
        constants = "\n".join(re.findall(r"^#define (?:BMP3_SENS_STATUS_REG_ADDR|BMP3_CMD_RDY|BMP3_CMD_ADDR|BMP3_ERR_REG_ADDR|BMP3_CMD_ERR|BMP3_POST_RESET_WAIT_TIME|BPM3_CMD_SOFT_RESET)\s+[^\n]*", (DRIVER / "bmp388.h").read_text(), re.M))
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#define OK 0
static std::vector<unsigned> waits;
static int usleep(unsigned value) { waits.push_back(value); return 0; }
struct Interface {
    unsigned reads = 0, ready_after = 0, writes = 0;
    bool status_error = false, write_error = false, error_error = false, command_error = false;
    int get_reg(uint8_t address, uint8_t *value) {
        if (address == BMP3_SENS_STATUS_REG_ADDR) {
            ++reads;
            if (status_error) { return -1; }
            *value = reads > ready_after ? BMP3_CMD_RDY : 0;
        } else {
            assert(address == BMP3_ERR_REG_ADDR);
            assert(writes == 1);
            if (error_error) { return -1; }
            *value = command_error ? BMP3_CMD_ERR : 0;
        }
        return OK;
    }
    int set_reg(uint8_t value, uint8_t address) {
        assert(address == BMP3_CMD_ADDR && value == BPM3_CMD_SOFT_RESET);
        assert(reads > ready_after);
        ++writes;
        return write_error ? -1 : OK;
    }
};
struct BMP388 { Interface *_interface; bool soft_reset(); };
'''
        main = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    Interface bus;
    unsigned expected_reads = 1, expected_waits = 1, expected_writes = 1;
    bool expected = true;
    if (!strcmp(argv[1], "later-ready")) { bus.ready_after = 2; expected_reads = 3; expected_waits = 3; }
    if (!strcmp(argv[1], "last-ready")) { bus.ready_after = 9; expected_reads = 10; expected_waits = 10; }
    if (!strcmp(argv[1], "never-ready")) { bus.ready_after = 100; expected_reads = 10; expected_waits = 9; expected_writes = 0; expected = false; }
    if (!strcmp(argv[1], "status-error")) { bus.status_error = true; expected_waits = 0; expected_writes = 0; expected = false; }
    if (!strcmp(argv[1], "write-error")) { bus.write_error = true; expected_waits = 0; expected = false; }
    if (!strcmp(argv[1], "error-read-error")) { bus.error_error = true; expected = false; }
    if (!strcmp(argv[1], "command-error")) { bus.command_error = true; expected = false; }
    BMP388 driver{&bus};
    assert(driver.soft_reset() == expected);
    assert(bus.reads == expected_reads && bus.writes == expected_writes);
    assert(waits.size() == expected_waits);
    for (auto delay : waits) { assert(delay == BMP3_POST_RESET_WAIT_TIME); }
}
'''
        path = directory / "reset.cpp"
        path.write_text(constants + fixture + source[start:end] + main)
        compiler = shutil.which("c++")
        if compiler is None:
            raise RuntimeError("host C++ compiler required")
        cls.binary = directory / "reset"
        subprocess.run([compiler, "-std=c++14", "-Wall", "-Wextra", "-Werror", str(path), "-o", str(cls.binary)], check=True)

    def test_immediately_ready(self): self.run_case("ready")
    def test_ready_after_two_bounded_waits(self): self.run_case("later-ready")
    def test_ready_on_last_attempt(self): self.run_case("last-ready")
    def test_never_ready_never_issues_reset(self): self.run_case("never-ready")
    def test_status_read_error_propagates_immediately(self): self.run_case("status-error")
    def test_reset_write_error_has_no_followup_read(self): self.run_case("write-error")
    def test_error_register_read_failure(self): self.run_case("error-read-error")
    def test_sensor_command_error(self): self.run_case("command-error")

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
