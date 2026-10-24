#!/usr/bin/env python3
"""Execute PX4 I2C dispatch and constant-expression bus ownership checks."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAL = ROOT / "platforms/nuttx/src/px4/renesas/rzv"
SPEC = importlib.util.spec_from_file_location(
    "runtime", ROOT / "test/rzv2h-audit-remediation-runtime-test.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def flags(native=(), sci=()):
    result = ""
    if native:
        result += "#define CONFIG_RZV_I2C 1\n"
    if sci:
        result += "#define CONFIG_RZV_SCI_I2C 1\n"
    return result + "".join(f"#define CONFIG_RZV_I2C{i} 1\n" for i in native) + \
        "".join(f"#define CONFIG_RZV_SCI{i}_I2C 1\n" for i in sci)


def dispatch(native, sci, body):
    source = (HAL / "micro_hal/micro_hal.cpp").read_text()
    code = RUNTIME.PRE + flags(native, sci) + r'''
struct i2c_master_s { int unused; };
i2c_master_s native_dev[9], sci_dev[10];
int native_calls[9], sci_calls[10], closes, close_error, blocked = -1;
i2c_master_s *board_i2c_initialize(int channel)
{ assert(channel>=0 && channel<9); if(channel==blocked) return nullptr;
  ++native_calls[channel]; return &native_dev[channel]; }
i2c_master_s *rzv_sci_i2c_initialize(int channel)
{ assert(channel>=0 && channel<10); ++sci_calls[channel]; return &sci_dev[channel]; }
int rzv_i2c_uninitialize(i2c_master_s *dev)
{
  for(int i=0;i<9;i++) if(dev==&native_dev[i]) {++closes;return close_error;}
  return -EINVAL;
}
'''
    code += RUNTIME.extract(source, "struct i2c_master_s *px4_i2cbus_initialize(")
    code += RUNTIME.extract(source, "int px4_i2cbus_uninitialize(")
    code += "\nint main(void) {\n" + body + "\nreturn 0; }\n"
    RUNTIME.run(code, cpp=True)


def validate(native, sci, buses, expected):
    source = (HAL / "include/px4_arch/i2c_hw_description.h").read_text()
    code = flags(native, sci) + r'''
#define I2C_BUS_MAX_BUS_ITEMS 9
struct px4_i2c_bus_t { int bus; };
constexpr void constexpr_assert(bool value,const char *) { if(!value) throw "invalid"; }
'''
    code += RUNTIME.extract(source, "constexpr bool validateI2CConfig(")
    values = list(buses) + [-1] * (9 - len(buses))
    code += "\nconstexpr px4_i2c_bus_t buses[9] = {" + \
        ",".join("{" + str(i) + "}" for i in values) + "};\n"
    code += "static_assert(validateI2CConfig(buses));\n"
    with tempfile.TemporaryDirectory(prefix="rzv2h-i2c-hal-") as directory:
        path = Path(directory) / "contract.cpp"
        path.write_text(code)
        result = subprocess.run(["c++", "-std=c++17", "-Wall", "-Werror",
                                 "-fsyntax-only", str(path)], capture_output=True, text=True)
        if (result.returncode == 0) != expected:
            raise AssertionError(result.stderr or "invalid bus table unexpectedly compiled")


class I2CHal(unittest.TestCase):
    def test_native_instances_and_default_sci7_dispatch_have_correct_provider(self):
        dispatch(range(9), (), r'''
for(int i=0;i<9;i++) {
  assert(px4_i2cbus_initialize(i)==&native_dev[i]);
  assert(native_calls[i]==1 && sci_calls[i]==0);
  assert(px4_i2cbus_uninitialize(&native_dev[i])==0);
}
assert(closes==0); /* PX4 must preserve the board's cached owner. */
blocked=8; assert(px4_i2cbus_initialize(8)==nullptr && native_calls[8]==1);
close_error=-EIO;assert(px4_i2cbus_uninitialize(&native_dev[8])==0 && closes==0);
assert(px4_i2cbus_initialize(-1)==nullptr && px4_i2cbus_initialize(9)==nullptr);
assert(px4_i2cbus_uninitialize(nullptr)==0);
''')
        dispatch((0, 8), (7,), r'''
assert(px4_i2cbus_initialize(0)==&native_dev[0]);
assert(px4_i2cbus_initialize(8)==&native_dev[8]);
assert(px4_i2cbus_initialize(7)==&sci_dev[7]);
assert(px4_i2cbus_initialize(1)==nullptr);
assert(px4_i2cbus_uninitialize(&sci_dev[7])==0 && closes==0);
assert(native_calls[7]==0 && sci_calls[7]==1);
''')
        dispatch((), (7,), r'''
assert(px4_i2cbus_initialize(7)==&sci_dev[7]);
assert(px4_i2cbus_uninitialize(&sci_dev[7])==0);
for(int i=0;i<9;i++) assert(native_calls[i]==0);
''')

    def test_disabled_and_conflicted_requests_do_not_call_a_provider(self):
        dispatch((), (), r'''
for(int i=-1;i<=10;i++) assert(px4_i2cbus_initialize(i)==nullptr);
for(int i=0;i<9;i++) assert(native_calls[i]==0);
for(int i=0;i<10;i++) assert(sci_calls[i]==0);
''')
        dispatch((7,), (7,), r'''
assert(px4_i2cbus_initialize(7)==nullptr);
assert(native_calls[7]==0 && sci_calls[7]==0);
''')
        for i in range(10):
            with self.subTest(sci=i):
                dispatch((), (i,), f'''
assert(px4_i2cbus_initialize({i})==&sci_dev[{i}]);
assert(px4_i2cbus_initialize(-1)==nullptr && px4_i2cbus_initialize(10)==nullptr);
''')

    def test_constant_validation_covers_all_nine_and_preserves_sci7_owner(self):
        for i in range(9):
            with self.subTest(native=i):
                validate((i,), (), (i,), True)
                validate((i,), (), (), False)
        validate((), (7,), (7,), True)
        validate((0, 8), (7,), (0, 7, 8), True)
        validate((7,), (7,), (7,), False)
        validate((), (), (8,), False)
        validate((), (), (9,), False)


if __name__ == "__main__":
    unittest.main()
