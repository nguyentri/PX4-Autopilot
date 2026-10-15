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
 for (int ch=0; ch<10; ch++) if(ch!=4) assert(rzv2h_serial_setup(ch)==0);
 assert(!count);
 fail_pin=10; assert(rzv2h_serial_setup(4)==-EACCES && count==1);
 count=0; fail_pin=11; assert(rzv2h_serial_setup(4)==-EACCES && count==2);
 count=0; fail_pin=0; assert(rzv2h_serial_setup(4)==0 && count==2);
 assert(pins[0]==10 && pins[1]==11);
 return 0;
}
'''
        B.compile_run(code)

if __name__ == '__main__': unittest.main()
