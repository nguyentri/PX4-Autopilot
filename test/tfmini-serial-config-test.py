#!/usr/bin/env python3
"""Execute production initialization against a serial syscall boundary."""
from pathlib import Path
import runpy
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = runpy.run_path(str(ROOT / 'test/rzv2h-board-test-support.py'))
REPAIR = runpy.run_path(str(ROOT / 'test/rzv2h-audit-remediation-runtime-test.py'))


class SerialConfiguration(unittest.TestCase):
    def test_final_115200_8n1_raw_attributes_are_applied_before_start(self):
        body = SUPPORT['body']((ROOT / 'src/drivers/distance_sensor/tfmini/TFMINI.cpp').read_text(),
                               'TFMINI::init')
        code = r'''
#include <cassert>
#include <cstdint>
#include <termios.h>
#include <fcntl.h>
#define PX4_ERR(...) ((void)0)
#define PX4_OK 0
static unsigned applies, closes, starts;
static bool fail_apply;
int param_find(const char *) { return 0; }
void param_get(int, int32_t *) {}
namespace math { float radians(float x) { return x; } }
struct Range { void set_min_distance(float) {} void set_max_distance(float) {} void set_fov(float) {} };
int host_open(const char *, int) { return 12; }
int host_close(int fd) { assert(fd == 12); ++closes; return 0; }
int host_getattr(int fd, termios *t) {
  assert(fd == 12);
  t->c_cflag = PARENB | CSTOPB | CRTSCTS | CS7;
  t->c_iflag = ICRNL | IXON | ISTRIP;
  t->c_oflag = OPOST | ONLCR;
  t->c_lflag = ICANON | ECHO | ISIG;
  return 0;
}
int host_setattr(int fd, int mode, const termios *t) {
  assert(fd == 12 && mode == TCSANOW);
  assert(cfgetispeed(t) == B115200 && cfgetospeed(t) == B115200);
  assert((t->c_cflag & CSIZE) == CS8);
  assert(!(t->c_cflag & (PARENB | CSTOPB | CRTSCTS)));
  assert((t->c_cflag & (CLOCAL | CREAD)) == (CLOCAL | CREAD));
  assert(!(t->c_iflag & (ICRNL | IXON | ISTRIP)));
  assert(!(t->c_oflag & (OPOST | ONLCR)));
  assert(!(t->c_lflag & (ICANON | ECHO | ISIG)));
  assert(t->c_cc[VMIN] == 1 && t->c_cc[VTIME] == 1);
  ++applies;
  return fail_apply ? -1 : 0;
}
#define open host_open
#define close host_close
#define tcgetattr host_getattr
#define tcsetattr host_setattr
class TFMINI { public:
  int init();
  int _fd{-1}; const char *_port{"/dev/test"}; Range _px4_rangefinder;
  void start() { assert(applies == closes && _fd == -1); ++starts; }
};
int TFMINI::init()
''' + body + r'''
int main() {
  TFMINI driver;
  assert(driver.init() == 0 && applies == 1 && closes == 1 && starts == 1);
  fail_apply = true;
  assert(driver.init() < 0 && applies == 2 && closes == 2 && starts == 1);
}
'''
        REPAIR['run'](code, cpp=True)


if __name__ == '__main__':
    unittest.main()
