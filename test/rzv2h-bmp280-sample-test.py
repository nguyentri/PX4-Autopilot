#!/usr/bin/env python3
"""Host checks for the RZ/V2H standalone BMP280 SCI7 I2C sample.

The production compensation helper is compiled into a shared library and
called through ctypes.  The production NSH command is compiled against a
timed BMP280 register simulator (controlled syscall responses, never board
evidence) to execute ID, reset, conversion, failure and CLI paths.  Static
contracts tie registers to the PX4 driver and the defconfig to SCI7.
"""

import ctypes
import errno
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
APPS = ROOT / "platforms/nuttx/NuttX/apps"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h"
DEFCONFIG = BOARD / "configs/bmp280/defconfig"
BOARD_H = BOARD / "include/board.h"
SCI_I2C_H = BOARD / "src/rzv2h_sci_i2c.h"
APP_DIR = APPS / "examples/bmp280"
APP_MAIN = APP_DIR / "bmp280_main.c"
APP_COMP = APP_DIR / "bmp280_compensation.c"
PX4_H = ROOT / "src/drivers/barometer/bmp280/bmp280.h"
PX4_HPP = ROOT / "src/drivers/barometer/bmp280/BMP280.hpp"
CC = shutil.which("cc") or shutil.which("gcc")

# Bosch BST-BMP280-DS001 compensation example (section 3.12 / 8.1).
BOSCH = dict(t1=27504, t2=26435, t3=-1000, p1=36477, p2=-10685, p3=3024,
             p4=2855, p5=140, p6=-7, p7=15500, p8=-14600, p9=6000)
BOSCH_ADC_T = 519888
BOSCH_ADC_P = 415148
FIELDS = ("t1", "t2", "t3", "p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8",
          "p9")


class Calib(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint16 if name in ("t1", "p1")
                 else ctypes.c_int16) for name in FIELDS]


def calib_bytes(**values):
    out = bytearray()
    for name in FIELDS:
        out += int(values[name]).to_bytes(2, "little",
                                          signed=name not in ("t1", "p1"))
    return bytes(out)


def data_bytes(adc_p, adc_t):
    """0xf7..0xfc: press msb/lsb/xlsb[7:4], then temp msb/lsb/xlsb[7:4]."""
    def word(v):
        return bytes([(v >> 12) & 0xff, (v >> 4) & 0xff, (v & 0xf) << 4])
    return word(adc_p) + word(adc_t)


def strip_c_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def config_values(path):
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", path.read_text(), re.M))


def c_defines(path):
    return {name: int(value, 16) for name, value in re.findall(
        r"^#define\s+(\w+)\s+\(?0x([0-9a-fA-F]+)\b", path.read_text(), re.M)}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


STUB_CONFIG = """
#define CONFIG_EXAMPLES_BMP280_DEFAULT_BUS 7
#define FAR
#define OK 0
"""

STUB_I2C = """
#include <stdint.h>
#include <sys/types.h>
#define I2C_M_READ   0x0001
#define I2C_M_NOSTOP 0x0040
#define I2CIOC_TRANSFER 0x2101
struct i2c_msg_s { uint32_t frequency; uint16_t addr; uint16_t flags;
                   uint8_t *buffer; ssize_t length; };
struct i2c_transfer_s { struct i2c_msg_s *msgv; size_t msgc; };
"""

# Timed BMP280 model.  Time only advances through usleep().  SIM_* environment
# variables select faults; a summary line goes to stderr after the app ends.
SIM = r"""
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "nuttx/i2c/i2c_master.h"

int bmp280_app_main(int argc, char *argv[]);

static unsigned long long now_us, reset_at, conv_done;
static int pending, ctrl, reset_seen, opens, closes, xfers, stale, convs;
static int sleep_writes, bad_shape, freq_bad, id = 0x58, nack_after = -1;
static int nvm_stuck, meas_stuck, early_clear, raw_skip, erased, open_fail;
static unsigned freq_want = 100000;
static unsigned char data[6] = {0x80, 0, 0, 0x80, 0, 0};
static const unsigned char calib[24] = {CALIB};
static char path[32];

static int env(const char *n, int d)
{
  const char *v = getenv(n);
  return v ? (int)strtol(v, NULL, 0) : d;
}

static void advance(void)
{
  if (pending && !meas_stuck && now_us >= conv_done)
    {
      unsigned p = raw_skip ? 0x80000 : ADC_P;
      unsigned t = ADC_T;
      data[0] = p >> 12; data[1] = p >> 4; data[2] = (p & 0xf) << 4;
      data[3] = t >> 12; data[4] = t >> 4; data[5] = (t & 0xf) << 4;
      pending = 0;
      ctrl &= ~3;
      convs++;
    }
}

static unsigned char reg(int r)
{
  advance();
  if (r == 0xd0) return id;
  if (r == 0xf3)
    {
      int nvm = reset_seen && (nvm_stuck || now_us < reset_at + 3000);
      return (pending && !early_clear ? 0x08 : 0) | (nvm ? 1 : 0);
    }
  if (r == 0xf4) return ctrl;
  if (r == 0xf5) return 0;
  if (r >= 0x88 && r < 0xa0) return erased ? 0xff : calib[r - 0x88];
  if (r >= 0xf7 && r <= 0xfc)
    {
      if (pending) stale++;
      return data[r - 0xf7];
    }
  return 0;
}

int sim_open(const char *p, int flags, ...)
{
  (void)flags;
  opens++;
  snprintf(path, sizeof(path), "%s", p);
  if (open_fail) { errno = ENOENT; return -1; }
  return 3;
}

int sim_close(int fd) { (void)fd; closes++; return 0; }
int sim_usleep(useconds_t us) { now_us += us; return 0; }

int sim_ioctl(int fd, unsigned long req, ...)
{
  va_list ap;
  struct i2c_transfer_s *x;
  struct i2c_msg_s *m;
  size_t i;

  va_start(ap, req);
  x = (struct i2c_transfer_s *)(uintptr_t)va_arg(ap, unsigned long);
  va_end(ap);
  xfers++;
  if (fd != 3 || req != I2CIOC_TRANSFER) { errno = EINVAL; return -1; }
  m = x->msgv;
  for (i = 0; i < x->msgc; i++)
    {
      if (m[i].frequency != freq_want) freq_bad++;
      if (m[i].addr != 0x76) { errno = ENXIO; return -1; }
    }
  if (nack_after >= 0 && xfers > nack_after) { errno = EIO; return -1; }
  if (reset_seen && now_us < reset_at + 2000) { errno = EIO; return -1; }

  if (x->msgc == 2)
    {
      if (m[0].flags != I2C_M_NOSTOP || m[1].flags != I2C_M_READ ||
          m[0].length != 1) { bad_shape++; errno = EIO; return -1; }
      for (i = 0; i < (size_t)m[1].length; i++)
        m[1].buffer[i] = reg(m[0].buffer[0] + i);
      return 0;
    }
  if (x->msgc == 1 && m[0].flags == 0 && m[0].length == 2)
    {
      int r = m[0].buffer[0], v = m[0].buffer[1];
      advance();
      if (r == 0xe0 && v == 0xb6)
        {
          reset_seen = 1; reset_at = now_us; ctrl = 0; pending = 0;
          memset(data, 0, sizeof(data)); data[0] = data[3] = 0x80;
        }
      else if (r == 0xf4)
        {
          ctrl = v;
          if ((v & 3) == 1) { pending = 1; conv_done = now_us + 40000; }
          if (v == 0) sleep_writes++;
        }
      return 0;
    }
  bad_shape++;
  errno = EINVAL;
  return -1;
}

int main(int argc, char *argv[])
{
  int rc;
  id = env("SIM_ID", 0x58);
  nack_after = env("SIM_NACK_AFTER", -1);
  nvm_stuck = env("SIM_NVM_STUCK", 0);
  meas_stuck = env("SIM_MEAS_STUCK", 0);
  early_clear = env("SIM_EARLY_CLEAR", 0);
  raw_skip = env("SIM_RAW_SKIP", 0);
  erased = env("SIM_ERASED", 0);
  open_fail = env("SIM_OPEN_FAIL", 0);
  freq_want = env("SIM_FREQ", 100000);
  fflush(stdout);
  rc = bmp280_app_main(argc, argv);
  fflush(stdout);
  fprintf(stderr, "SIM: opens=%d closes=%d convs=%d stale=%d sleep=%d "
          "shape=%d freq_bad=%d now_us=%llu path=%s\n", opens, closes,
          convs, stale, sleep_writes, bad_shape, freq_bad, now_us, path);
  return rc;
}
"""


def build_sim(workdir, main_src=APP_MAIN, comp_src=APP_COMP):
    inc = workdir / "inc"
    (inc / "nuttx/i2c").mkdir(parents=True, exist_ok=True)
    (inc / "nuttx/config.h").write_text(STUB_CONFIG)
    (inc / "nuttx/i2c/i2c_master.h").write_text(STUB_I2C)
    sim = SIM.replace("CALIB", ",".join(str(b) for b in calib_bytes(**BOSCH)))
    sim = sim.replace("ADC_P", str(BOSCH_ADC_P)).replace("ADC_T", str(BOSCH_ADC_T))
    (workdir / "sim.c").write_text(sim)
    exe = workdir / "bmp280-sim"
    flags = ["-std=gnu11", "-O0", "-U_FORTIFY_SOURCE", "-Wall", "-Wextra",
             "-Werror", "-I", str(inc), "-I", str(APP_DIR)]
    objs = []
    for name, src, extra in (
            ("main.o", main_src, ["-Dmain=bmp280_app_main", "-Dopen=sim_open",
                                  "-Dclose=sim_close", "-Dioctl=sim_ioctl",
                                  "-Dusleep=sim_usleep"]),
            ("comp.o", comp_src, []), ("sim.o", workdir / "sim.c", [])):
        out = workdir / name
        res = run([CC, *flags, *extra, "-c", str(src), "-o", str(out)])
        if res.returncode:
            raise AssertionError(res.stderr)
        objs.append(str(out))
    res = run([CC, *objs, "-o", str(exe)])
    if res.returncode:
        raise AssertionError(res.stderr)
    return exe


def sim_run(exe, args=(), **faults):
    environ = {k: v for k, v in os.environ.items() if not k.startswith("SIM_")}
    environ.update({"SIM_" + k.upper(): str(v) for k, v in faults.items()})
    res = run([str(exe), *args], env=environ, timeout=10)
    summary = dict(re.findall(r"(\w+)=(\S+)", res.stderr.splitlines()[-1]))
    return res, summary


@unittest.skipIf(CC is None, "host C compiler not available")
class CompensationHelper(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        lib = Path(cls.tmp.name) / "libbmp280comp.so"
        res = run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror", "-shared",
                   "-fPIC", "-I", str(APP_DIR), str(APP_COMP), "-o", str(lib)])
        if res.returncode:
            raise AssertionError(res.stderr)
        cls.lib = ctypes.CDLL(str(lib))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def decode(self, raw):
        cal = Calib()
        ret = self.lib.bmp280_calib_decode((ctypes.c_uint8 * 24)(*raw),
                                           ctypes.byref(cal))
        return ret, cal

    def compensate(self, cal, adc_t, adc_p):
        t = ctypes.c_int32()
        p = ctypes.c_uint32()
        ret = self.lib.bmp280_compensate(ctypes.byref(cal), adc_t, adc_p,
                                         ctypes.byref(t), ctypes.byref(p))
        return ret, t.value, p.value

    def bosch(self, **override):
        ret, cal = self.decode(calib_bytes(**{**BOSCH, **override}))
        self.assertEqual(ret, 0)
        return cal

    def test_bosch_reference_vector(self):
        ret, temp, press = self.compensate(self.bosch(), BOSCH_ADC_T, BOSCH_ADC_P)
        self.assertEqual(ret, 0)
        self.assertEqual(temp, 2508)                      # 25.08 degC
        # Bosch int64 algorithm, Q24.8 Pa: 25767233 / 256 = 100653.25 Pa.
        self.assertEqual(press, 25767233)

    def test_decode_signedness_and_little_endian(self):
        ret, cal = self.decode(calib_bytes(**BOSCH))
        self.assertEqual(ret, 0)
        self.assertEqual({f: getattr(cal, f) for f in FIELDS}, BOSCH)
        ret, cal = self.decode(calib_bytes(**{**BOSCH, "t1": 0xfedc, "p1": 0x8001,
                                              "t2": -32768, "p9": -1}))
        self.assertEqual((cal.t1, cal.p1, cal.t2, cal.p9), (0xfedc, 0x8001, -32768, -1))

    def test_invalid_trim_rejected(self):
        einval = -errno.EINVAL
        self.assertEqual(self.decode(bytes(24))[0], einval)
        self.assertEqual(self.decode(b"\xff" * 24)[0], einval)
        self.assertEqual(self.decode(calib_bytes(**{**BOSCH, "t1": 0}))[0], einval)
        self.assertEqual(self.decode(calib_bytes(**{**BOSCH, "p1": 0}))[0], einval)
        cal = self.bosch()
        cal.p1 = 0      # divisor source, even if a caller bypasses decode
        self.assertEqual(self.compensate(cal, BOSCH_ADC_T, BOSCH_ADC_P)[0], einval)

    def test_raw_decode_and_skipped_marker(self):
        p = ctypes.c_int32()
        t = ctypes.c_int32()
        raw = data_bytes(BOSCH_ADC_P, BOSCH_ADC_T)
        self.assertEqual(self.lib.bmp280_raw_decode((ctypes.c_uint8 * 6)(*raw),
                                                    ctypes.byref(p), ctypes.byref(t)), 0)
        self.assertEqual((p.value, t.value), (BOSCH_ADC_P, BOSCH_ADC_T))
        for raw in (data_bytes(0x80000, BOSCH_ADC_T), data_bytes(BOSCH_ADC_P, 0x80000)):
            self.assertEqual(self.lib.bmp280_raw_decode(
                (ctypes.c_uint8 * 6)(*raw), ctypes.byref(p), ctypes.byref(t)),
                -errno.ENODATA)
        cal = self.bosch()
        self.assertEqual(self.compensate(cal, 0x80000, BOSCH_ADC_P)[0], -errno.ENODATA)
        self.assertEqual(self.compensate(cal, BOSCH_ADC_T, 0x80000)[0], -errno.ENODATA)

    def test_out_of_domain_inputs_and_results(self):
        cal = self.bosch()
        for adc_t, adc_p in ((-1, BOSCH_ADC_P), (0x100000, BOSCH_ADC_P),
                             (BOSCH_ADC_T, -1), (BOSCH_ADC_T, 0x100000)):
            self.assertEqual(self.compensate(cal, adc_t, adc_p)[0], -errno.EINVAL)
        # Temperature far outside -40..85 degC and pressure outside 300..1100 hPa.
        self.assertEqual(self.compensate(cal, 0xfffff, BOSCH_ADC_P)[0], -errno.ERANGE)
        self.assertEqual(self.compensate(cal, 0, BOSCH_ADC_P)[0], -errno.ERANGE)
        self.assertEqual(self.compensate(cal, BOSCH_ADC_T, 0)[0], -errno.ERANGE)
        self.assertEqual(self.compensate(cal, BOSCH_ADC_T, 0xfffff)[0], -errno.ERANGE)

    def test_pressure_intermediate_overflow_rejected(self):
        """Hot in-envelope temperature plus maximal p1..p3 overflows 64 bits."""
        normal = self.bosch()
        hostile = self.bosch(p1=65535, p2=32767, p3=32767)
        hot = None
        for adc_t in range(BOSCH_ADC_T, 0xfffff, 512):
            ret, temp, _ = self.compensate(normal, adc_t, BOSCH_ADC_P)
            if ret == 0 and temp > 7500:
                hot = adc_t
                break
        self.assertIsNotNone(hot)
        self.assertEqual(self.compensate(hostile, hot, BOSCH_ADC_P)[0], -errno.ERANGE)


@unittest.skipIf(CC is None, "host C compiler not available")
class SampleApplicationSimulation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.exe = build_sim(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def assert_fail(self, res, sim, reason=None, opened=True):
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip().splitlines()[-1], "bmp280: FAIL")
        self.assertNotIn("bmp280: PASS", res.stdout)
        self.assertEqual(sim["opens"], "1" if opened else "0")
        self.assertEqual(sim["closes"], sim["opens"])
        if reason:
            self.assertIn(reason, res.stderr)

    def test_default_run_passes_with_fresh_samples(self):
        res, sim = sim_run(self.exe)
        self.assertEqual(res.returncode, 0, res.stderr)
        lines = res.stdout.splitlines()
        self.assertEqual(lines[0], "bmp280: /dev/i2c7 addr 0x76 100000 Hz samples 10")
        self.assertEqual(lines.count("bmp280: addr 0x76 chip ID 0x58 (BMP280)"), 1)
        samples = re.findall(r"^bmp280: \[(\d+)\] T=25\.08 degC P=100653\.25 Pa$",
                             res.stdout, re.M)
        self.assertEqual(samples, [str(i) for i in range(10)])
        self.assertEqual(lines[-2:], ["bmp280: 10 samples", "bmp280: PASS"])
        self.assertEqual((sim["path"], sim["convs"], sim["stale"], sim["closes"],
                          sim["sleep"], sim["shape"], sim["freq_bad"]),
                         ("/dev/i2c7", "10", "0", "1", "1", "0", "0"))

    def test_measuring_bit_clear_after_trigger_cannot_admit_stale_data(self):
        res, sim = sim_run(self.exe, ["-n", "3"], early_clear=1)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual((sim["convs"], sim["stale"]), ("3", "0"))
        self.assertEqual(len(re.findall(r"^bmp280: \[\d+\] ", res.stdout, re.M)), 3)

    def test_options_reach_transfers(self):
        res, sim = sim_run(self.exe, ["-b", "7", "-a", "0x76", "-f", "400000",
                                      "-n", "1"], freq=400000)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(sim["freq_bad"], "0")
        res, sim = sim_run(self.exe, ["-b", "12", "-n", "1"])
        self.assertEqual(sim["path"], "/dev/i2c12")

    def test_wrong_id_fails_without_reset(self):
        res, sim = sim_run(self.exe, id=0x50)
        self.assert_fail(res, sim,
                         "chip ID 0x50 is not BMP280 0x58 or BME280 0x60")
        self.assertEqual((sim["convs"], sim["sleep"]), ("0", "0"))

    def test_bme280_id_is_accepted_for_temperature_and_pressure(self):
        res, sim = sim_run(self.exe, ["-n", "1"], id=0x60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("bmp280: addr 0x76 chip ID 0x60 (BME280)", res.stdout)
        self.assertIn("bmp280: PASS", res.stdout)

    def test_absent_address_fails_bounded(self):
        res, sim = sim_run(self.exe, ["-a", "0x75", "-n", "1"])
        self.assert_fail(res, sim, "chip ID read failed: %d" % -errno.ENXIO)
        self.assertIn("bmp280: error %d" % -errno.ENXIO, res.stderr)

    def test_open_failure(self):
        res, sim = sim_run(self.exe, open_fail=1)
        self.assertEqual(res.returncode, 1)
        self.assertIn("open /dev/i2c7 failed: %d" % -errno.ENOENT, res.stderr)
        self.assertEqual(res.stdout.splitlines()[-1], "bmp280: FAIL")

    def test_midrun_bus_failure_keeps_first_error_and_cleans_up(self):
        res, sim = sim_run(self.exe, nack_after=20)
        self.assert_fail(res, sim, "bmp280: error %d" % -errno.EIO)
        self.assertNotEqual(sim["convs"], "0")

    def test_readiness_timeouts_are_bounded(self):
        for fault, reason in (("nvm_stuck", "NVM copy not complete"),
                              ("meas_stuck", "conversion timeout")):
            res, sim = sim_run(self.exe, **{fault: 1})
            self.assert_fail(res, sim, reason)
            self.assertIn("bmp280: error %d" % -errno.ETIMEDOUT, res.stderr)
            self.assertLess(int(sim["now_us"]), 200000)

    def test_skipped_raw_and_erased_trim_fail(self):
        res, sim = sim_run(self.exe, raw_skip=1)
        self.assert_fail(res, sim, "no fresh conversion")
        res, sim = sim_run(self.exe, erased=1)
        self.assert_fail(res, sim, "trim block invalid: %d" % -errno.EINVAL)

    def test_malformed_cli_stops_before_open(self):
        for args in (["-n", "0"], ["-n", "101"], ["-n", "x"], ["-a", "0x78"],
                     ["-a", "0x07"], ["-f", "9999"], ["-f", "400001"],
                     ["-b", "256"], ["-b", "-1"], ["extra"], ["-q"], ["-n"]):
            res, sim = sim_run(self.exe, args)
            self.assert_fail(res, sim, opened=False)
            self.assertIn("Usage: bmp280", res.stderr, args)

    def test_help_exits_zero_without_open(self):
        res, sim = sim_run(self.exe, ["-h"])
        self.assertEqual((res.returncode, sim["opens"]), (0, "0"))
        self.assertIn("Usage: bmp280", res.stderr)


@unittest.skipIf(CC is None, "host C compiler not available")
class MutationsAreDetected(unittest.TestCase):
    """Each mutation of a production source must break the default run."""

    MUTATIONS = (
        (APP_MAIN, r"msgs\[0\]\.flags\s*=\s*I2C_M_NOSTOP;", "msgs[0].flags = 0;"),
        (APP_MAIN, r"#define BMP280_ID_VALUE\s+0x58", "#define BMP280_ID_VALUE 0x60"),
        (APP_COMP, r"\(b\[0\] \| \(b\[1\] << 8\)\)", "((b[0] << 8) | b[1])"),
        (APP_COMP, r"cal->p1 = bmp280_u16\(&raw\[6\]\);", "cal->p1 = bmp280_u16(&raw[8]);"),
        (APP_COMP, r"t_fine = var1 \+ var2;", "t_fine = var1;"),
    )

    def test_mutations(self):
        for src, pattern, repl in self.MUTATIONS:
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as tmp:
                text, n = re.subn(pattern, repl, src.read_text())
                self.assertEqual(n, 1, pattern)
                mutated = Path(tmp) / src.name
                mutated.write_text(text)
                exe = build_sim(Path(tmp),
                                **{"main_src" if src == APP_MAIN else "comp_src": mutated})
                res, sim = sim_run(exe, ["-n", "2"], early_clear=1)
                ok = (res.returncode == 0 and sim["stale"] == "0" and
                      len(re.findall(r"T=25\.08 degC P=100653\.25 Pa", res.stdout)) == 2)
                self.assertFalse(ok, "mutation survived: " + pattern)


class StaticContracts(unittest.TestCase):
    def test_registers_match_px4_driver(self):
        px4 = c_defines(PX4_H)
        sample = c_defines(APP_MAIN)
        for px4_name, name in (("BMP280_ADDR_CAL", "BMP280_REG_CALIB"),
                               ("BMP280_ADDR_ID", "BMP280_REG_ID"),
                               ("BMP280_ADDR_RESET", "BMP280_REG_RESET"),
                               ("BMP280_ADDR_STATUS", "BMP280_REG_STATUS"),
                               ("BMP280_ADDR_CTRL", "BMP280_REG_CTRL_MEAS"),
                               ("BMP280_ADDR_CONFIG", "BMP280_REG_CONFIG"),
                               ("BMP280_ADDR_DATA", "BMP280_REG_DATA"),
                               ("BMP280_VALUE_ID", "BMP280_ID_VALUE"),
                               ("BMP280_VALUE_RESET", "BMP280_RESET_VALUE")):
            self.assertEqual(sample[name], px4[px4_name], name)

    def test_oversampling_and_wait_match_px4(self):
        text = APP_MAIN.read_text()
        self.assertIn("BMP280_CTRL_P16 | BMP280_CTRL_T2", PX4_HPP.read_text())
        px4 = PX4_H.read_text()
        for bit in ("BMP280_CTRL_T2", "BMP280_CTRL_P16"):
            want = re.search(r"#define %s\s+\((0x\w+)<<(\d)\)" % bit, px4)
            got = re.search(r"#define %s\s+\((0x\w+) << (\d)\)" % bit, text)
            self.assertEqual(want.groups(), got.groups(), bit)
        mt_init = int(re.search(r"BMP280_MT_INIT\s+(\d+)", px4).group(1))
        mt = int(re.search(r"BMP280_MT\s+(\d+)", px4).group(1))
        datasheet_max = 1250 + 2300 * 2 + 2300 * 16 + 575
        self.assertLessEqual(abs(datasheet_max - (mt_init + mt * (16 - 1 + 2 - 1))), 100)
        self.assertRegex(text, r"#define BMP280_OSRS_T\s+2\b")
        self.assertRegex(text, r"#define BMP280_OSRS_P\s+16\b")

    def test_repeated_start_read_and_defaults(self):
        code = strip_c_comments(APP_MAIN.read_text())
        self.assertRegex(code, r"msgs\[0\]\.flags\s*=\s*I2C_M_NOSTOP\s*;")
        self.assertRegex(code, r"msgs\[1\]\.flags\s*=\s*I2C_M_READ\s*;")
        self.assertRegex(code, r'snprintf\(path, sizeof\(path\), "/dev/i2c%d", bus\)')
        self.assertRegex(code, r"#define BMP280_ADDR_DEFAULT\s+0x76")
        self.assertNotIn("0x77,", code)

    def test_kconfig_and_makefiles(self):
        kconfig = (APP_DIR / "Kconfig").read_text()
        block = re.search(r"config EXAMPLES_BMP280\n(.*?)\n\n", kconfig, re.S).group(1)
        self.assertIn("default n", block)
        self.assertIn("depends on I2C_DRIVER", block)
        self.assertRegex(kconfig, r"EXAMPLES_BMP280_DEFAULT_BUS\n.*\n\s*default 7\n")
        self.assertIn("CONFIG_EXAMPLES_BMP280", (APP_DIR / "Make.defs").read_text())
        self.assertIn("bmp280_compensation.c", (APP_DIR / "Makefile").read_text())

    def test_defconfig_selects_only_sci7_i2c(self):
        config = config_values(DEFCONFIG)
        for symbol in ("CONFIG_I2C", "CONFIG_I2C_DRIVER", "CONFIG_I2C_RESET",
                       "CONFIG_RZV_SCI_I2C", "CONFIG_RZV_SCI7_I2C",
                       "CONFIG_EXAMPLES_BMP280", "CONFIG_RZV2H_BUILD_CR8_0",
                       "CONFIG_SYSLOG_RTT"):
            self.assertEqual(config.get(symbol), "y", symbol)
        for symbol in ("CONFIG_RZV_SCI7", "CONFIG_RZV_SCI7_SPI", "CONFIG_RZV_RIIC7",
                       "CONFIG_EXAMPLES_BMM150", "CONFIG_EXAMPLES_GY912",
                       "CONFIG_SENSORS_BMP280", "CONFIG_SENSORS_ICM20948"):
            self.assertNotIn(symbol, config)

    def test_board_sci7_pins_and_bus(self):
        text = BOARD_H.read_text()
        sda = re.search(r"#define BOARD_SCI7_I2C_SDA_GPIO\s*\\\s*\n\s*\((\w+)", text)
        scl = re.search(r"#define BOARD_SCI7_I2C_SCL_GPIO\s*\\\s*\n\s*\((\w+)", text)
        self.assertEqual(sda.group(1), "GPIO_TXD7_MOSI7_SDA7_P7_6_M1")
        self.assertEqual(scl.group(1), "GPIO_RXD7_MISO7_SCL7_P7_7_M1")
        self.assertRegex(text, r"#define BOARD_BMP280_BUS\s+7\b")
        self.assertRegex(text, r"#define BOARD_BMP280_ADDR\s+0x76\b")
        header = SCI_I2C_H.read_text()
        self.assertRegex(header, r"#define BOARD_SCI7_I2C_BUS\s+7\b")
        self.assertRegex(header, r"#define BOARD_SCI_I2C_BUS_BASE\s+10\b")
        self.assertIn("SCI0..6 use 10..16 and SCI8/9 use 18/19", header)


if __name__ == "__main__":
    unittest.main()
