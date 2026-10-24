#!/usr/bin/env python3
"""Exercise route rejection, isolation and pin-error propagation."""
from pathlib import Path
import importlib.util
import unittest
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

class SerialBoardRuntime(unittest.TestCase):
    def test_invalid_unassigned_and_selected_route(self):
        source = (ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_serial.c').read_text()
        code = B.PRELUDE + r'''
#define CONFIG_RZV_SCI4 1
#define BOARD_P7_0_GPIO 10
#define BOARD_P7_1_GPIO 11
#define _err(...) ((void)0)
#define sinfo(...) ((void)0)
static int pins[2], count, fail_pin;
static int rzv_gpioconfig(unsigned int pin)
{ assert(count<2); pins[count++]=pin; return pin==(unsigned)fail_pin ? -EACCES : 0; }
''' + B.EXTRACT.definition(source, 'int rzv2h_serial_setup(int channel)') + r'''
int main(void)
{
 assert(rzv2h_serial_setup(-2)==-EINVAL && rzv2h_serial_setup(10)==-EINVAL);
 for (int ch=0; ch<10; ch++) if(ch!=4) assert(rzv2h_serial_setup(ch)==-ENODEV);
 assert(!count);
 fail_pin=10; assert(rzv2h_serial_setup(4)==-EACCES && count==1);
 count=0; fail_pin=11; assert(rzv2h_serial_setup(4)==-EACCES && count==2);
 count=0; fail_pin=0; assert(rzv2h_serial_setup(4)==0 && count==2);
 assert(pins[0]==10 && pins[1]==11);
 return 0;
}
'''
        B.compile_run(code)

    def test_unassigned_routes_need_opt_in_and_controlled_init_never_muxes_pads(self):
        source = (ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_serial.c').read_text()
        for admission in ("", "#define CONFIG_RZV2H_SCI_UART_PRECONFIGURED 1", "#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1"):
            with self.subTest(admission=admission):
                code = B.PRELUDE + admission + r'''
#define CONFIG_RZV_SCI0 1
#define CONFIG_RZV_SCI4 1
#define BOARD_P7_0_GPIO 10
#define BOARD_P7_1_GPIO 11
#define _err(...) ((void)0)
#define sinfo(...) ((void)0)
static unsigned pins;
static int rzv_gpioconfig(unsigned int pin) {(void)pin; ++pins; return 0;}
''' + B.EXTRACT.definition(source, 'int rzv2h_serial_setup(int channel)') + r'''
int main(void) {
#ifdef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT
  assert(rzv2h_serial_setup(0) == 0 && rzv2h_serial_setup(4) == 0);
  assert(rzv2h_serial_setup(-1) == 0 && !pins);
#elif defined(CONFIG_RZV2H_SCI_UART_PRECONFIGURED)
  assert(rzv2h_serial_setup(0) == 0 && !pins);
  assert(rzv2h_serial_setup(4) == 0 && pins == 2);
#else
  assert(rzv2h_serial_setup(0) == -ENOTSUP && !pins);
  assert(rzv2h_serial_setup(-1) == -ENOTSUP && !pins);
  assert(rzv2h_serial_setup(4) == 0 && pins == 2);
#endif
  assert(rzv2h_serial_setup(9) == -ENODEV);
  return 0;
}
'''
                B.compile_run(code)

    def test_payload_uart4_5_6_9_keep_distinct_routes(self):
        source = (ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_serial.c').read_text()
        code = B.PRELUDE + r'''
#define CONFIG_RZV_SCI4 1
#define CONFIG_RZV_SCI5 1
#define CONFIG_RZV_SCI6 1
#define CONFIG_RZV_SCI9 1
#define BOARD_P7_0_GPIO 70
#define BOARD_P7_1_GPIO 71
#define BOARD_P7_2_GPIO 72
#define BOARD_P7_3_GPIO 73
#define BOARD_P7_5_GPIO 75
#define BOARD_P8_2_GPIO 82
#define BOARD_P8_3_GPIO 83
#define _err(...) ((void)0)
#define sinfo(...) ((void)0)
static unsigned pins[7], count;
static int rzv_gpioconfig(unsigned int pin) {assert(count < 7); pins[count++] = pin; return 0;}
''' + B.EXTRACT.definition(source, 'int rzv2h_serial_setup(int channel)') + r'''
int main(void) {
  const unsigned expected[7] = {70,71,72,73,75,82,83};
  assert(rzv2h_serial_setup(4) == 0 && count == 2);
  assert(rzv2h_serial_setup(5) == 0 && count == 4);
  assert(rzv2h_serial_setup(6) == 0 && count == 5);
  assert(rzv2h_serial_setup(9) == 0 && count == 7);
  assert(!memcmp(expected, pins, sizeof(pins)));
  count = 0;
  assert(rzv2h_serial_setup(-1) == 0 && count == 7 && !memcmp(expected, pins, sizeof(pins)));
  return 0;
}
'''
        B.compile_run(code)

if __name__ == '__main__': unittest.main()
