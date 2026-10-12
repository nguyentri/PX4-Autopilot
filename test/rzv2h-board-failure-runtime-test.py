#!/usr/bin/env python3
"""Run board pin and watchdog setup failures through production functions."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src'
SPEC = importlib.util.spec_from_file_location('boundaries', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
BOUNDARIES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARIES)
definition = BOUNDARIES.EXTRACT.definition


class BoardFailures(unittest.TestCase):
    def test_i2c_pin_failure_unwind_and_retry(self):
        source = (BOARD / 'rzv2h_i2c.c').read_text()
        code = BOUNDARIES.PRELUDE + r'''
#define CONFIG_RZV_I2C0 1
#define CONFIG_I2C_DRIVER 1
#define BOARD_I2C0_SDA_GPIO 10
#define BOARD_I2C0_SCL_GPIO 11
#define i2cerr(...) ((void)0)
#define i2cinfo(...) ((void)0)
struct i2c_master_s { int unused; };
static struct i2c_master_s device, *g_i2c[4];
static int pin_calls, fail_pin, init_calls, registration_error, references;
static int rzv_gpioconfig(unsigned pin) {
  assert(pin == 10u + pin_calls++);
  return pin_calls == fail_pin ? -EIO : 0;
}
static struct i2c_master_s *rzv_i2c_initialize(int bus) {
  assert(bus == 0); ++init_calls; ++references; return &device;
}
static int i2c_register(struct i2c_master_s *dev, int bus) {
  assert(dev == &device && bus == 0); return registration_error;
}
static void rzv_i2c_uninitialize(struct i2c_master_s *dev) {
  assert(dev == &device); --references;
}
''' + definition(source, 'struct i2c_master_s *board_i2c_initialize(int bus)') + r'''
int main(void) {
  assert(board_i2c_initialize(-1) == NULL);
  assert(board_i2c_initialize(4) == NULL && !pin_calls);
  for (fail_pin = 1; fail_pin <= 2; ++fail_pin) {
    pin_calls = 0;
    assert(board_i2c_initialize(0) == NULL);
    assert(pin_calls == fail_pin && !init_calls && !g_i2c[0]);
  }
  fail_pin = 0; pin_calls = 0; registration_error = -ENOMEM;
  assert(board_i2c_initialize(0) == NULL && !references && !g_i2c[0]);
  pin_calls = 0; registration_error = 0;
  assert(board_i2c_initialize(0) == &device && references == 1);
  int old_calls = pin_calls;
  assert(board_i2c_initialize(0) == &device && pin_calls == old_calls);
  return 0;
}
'''
        BOUNDARIES.compile_run(code)

    def test_serial_and_led_pin_failure_retry(self):
        serial = (BOARD / 'rzv2h_serial.c').read_text()
        leds = (BOARD / 'rzv2h_auto_leds.c').read_text()
        code = BOUNDARIES.PRELUDE + r'''
#define CONFIG_RZV_SCI3 1
#define BOARD_SCI3_TXD_GPIO 10
#define BOARD_SCI3_RXD_GPIO 11
#define BOARD_NLEDS 2
#define _err(...) ((void)0)
#define sinfo(...) ((void)0)
#define led_dumppins(...) ((void)0)
static const unsigned g_led_gpio[2] = {10, 11};
static int calls, fail_pin;
static int rzv_gpioconfig(unsigned pin) {
  assert(pin == 10u + calls++);
  return calls == fail_pin ? -EIO : 0;
}
''' + definition(serial, 'int rzv2h_serial_setup(int channel)')
        code += definition(leds, 'uint32_t board_userled_initialize(void)') + r'''
int main(void) {
  for (fail_pin = 1; fail_pin <= 2; ++fail_pin) {
    calls = 0;
    assert(rzv2h_serial_setup(3) == -EIO && calls == fail_pin);
    calls = 0;
    assert(board_userled_initialize() == 0 && calls == fail_pin);
  }
  fail_pin = 0; calls = 0;
  assert(rzv2h_serial_setup(3) == 0 && calls == 2);
  calls = 0;
  assert(board_userled_initialize() == BOARD_NLEDS && calls == 2);
  assert(board_userled_initialize() == BOARD_NLEDS && calls == 2);
  return 0;
}
'''
        BOUNDARIES.compile_run(code)

    def test_uart_pin_setup_does_not_touch_another_channel(self):
        source = (BOARD / 'rzv2h_serial.c').read_text()
        code = BOUNDARIES.PRELUDE + r'''
#define CONFIG_RZV_SCI3 1
#define CONFIG_RZV_SCI4 1
#define BOARD_SCI3_TXD_GPIO 10
#define BOARD_SCI3_RXD_GPIO 11
#define BOARD_P7_0_GPIO 14
#define BOARD_P7_1_GPIO 15
#define _err(...) ((void)0)
#define sinfo(...) ((void)0)
static int calls[20];
static int rzv_gpioconfig(unsigned pin) {
  ++calls[pin]; return pin == 15 ? -EIO : 0;
}
''' + definition(source, 'int rzv2h_serial_setup(int channel)') + r'''
int main(void) {
  assert(rzv2h_serial_setup(3) == 0);
  assert(calls[10] == 1 && calls[11] == 1 && !calls[14] && !calls[15]);
  assert(rzv2h_serial_setup(4) == -EIO);
  assert(calls[10] == 1 && calls[11] == 1 && calls[14] == 1 && calls[15] == 1);
  assert(rzv2h_serial_setup(-2) == -EINVAL && rzv2h_serial_setup(10) == -EINVAL);
  return 0;
}
'''
        BOUNDARIES.compile_run(code)

    def test_bringup_preserves_first_error_and_skips_failed_led_registration(self):
        source = (BOARD / 'rzv2h_bringup.c').read_text()
        code = BOUNDARIES.PRELUDE + r'''
#define HAVE_LEDS 1
#define CONFIG_ARCH_BUTTONS 1
#define CONFIG_RZV_I2C0 1
#define CONFIG_FS_PROCFS 1
#define LED_DRIVER_PATH "/dev/userleds"
#define UNUSED(x) ((void)(x))
#define syslog(...) ((void)0)
static int led_count, buttons, registered, i2c_calls, mount_error;
static uint32_t board_userled_initialize(void) { return led_count; }
static uint32_t board_button_initialize(void) { return buttons; }
static int userled_lower_initialize(const char *path) {
  (void)path; ++registered; return 0;
}
static void *board_i2c_initialize(int bus) { assert(bus == 0); ++i2c_calls; return NULL; }
static int nx_mount(const char *source, const char *target, const char *type,
                    unsigned flags, const void *data) {
  (void)source; (void)target; (void)type; (void)flags; (void)data;
  return mount_error;
}
''' + definition(source, 'int board_bringup(void)') + r'''
int main(void) {
  assert(board_bringup() == -ENODEV && !registered && i2c_calls == 1);
  led_count = 2; buttons = 1; mount_error = -EACCES;
  assert(board_bringup() == -EACCES && registered == 1 && i2c_calls == 2);
  mount_error = 0; buttons = 0;
  assert(board_bringup() == -ENODEV && registered == 2 && i2c_calls == 3);
  return 0;
}
'''
        BOUNDARIES.compile_run(code)

    def test_watchdog_feeder_failures_precede_start_and_preserve_errno(self):
        source = (BOARD / 'rzv2h_wdt_test.c').read_text()
        code = '#define _POSIX_C_SOURCE 200809L\n' + BOUNDARIES.PRELUDE + r'''
#include <signal.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#define syslog(...) ((void)0)
#define WDT_DEVPATH "/dev/watchdog0"
#define WDT_TIMEOUT_MS 5000
#define REFRESH_PERIOD_MS 2500
#define STATUS_PRINT_INTERVAL 10
#define WDIOC_SETTIMEOUT 1
#define WDIOC_START 2
static int g_wdt_fd = -1;
static bool g_wdt_running, g_refresh_enabled, g_timer_started;
static bool g_action_installed;
static struct sigaction g_previous_action, current_action;
static volatile uint32_t g_refresh_count;
static timer_t g_timer_id;
static int failure, cleanup_failure, starts, created, deleted, armed, closed;
static void wdt_timer_handler(int s, siginfo_t *i, void *c) { (void)s; (void)i; (void)c; }
static void wdt_print_info(void) {}
static int test_open(const char *path, int mode) { (void)path; (void)mode; return 3; }
static int test_close(int fd) { assert(fd == 3); ++closed; errno = ENOSPC; return 0; }
static int test_sigaction(int signal, const struct sigaction *action, struct sigaction *old) {
  assert(signal == SIGALRM);
  if (old && failure == 5) { errno = EPERM; return -1; }
  if (!old && cleanup_failure == 3) { errno = EACCES; return -1; }
  if (old) *old = current_action;
  current_action = *action;
  errno = ENOSPC; return 0;
}
static int test_timer_create(clockid_t clock, struct sigevent *event, timer_t *timer) {
  assert(clock == CLOCK_REALTIME && event->sigev_signo == SIGALRM);
  if (failure == 1) { errno = EAGAIN; return -1; }
  *timer = (timer_t)1; ++created; return 0;
}
static int test_timer_settime(timer_t timer, int flags, const struct itimerspec *value, struct itimerspec *old) {
  (void)flags; (void)old; assert(timer == (timer_t)1);
  if (value->it_value.tv_sec && failure == 2) { errno = EINVAL; return -1; }
  if (!value->it_value.tv_sec && cleanup_failure == 1) { errno = EINTR; return -1; }
  armed = value->it_value.tv_sec != 0; return 0;
}
static int test_timer_delete(timer_t timer) {
  assert(timer == (timer_t)1);
  if (cleanup_failure == 2) { errno = EBUSY; return -1; }
  ++deleted; armed = 0; errno = ENOSPC; return 0;
}
static unsigned test_sleep(unsigned seconds) { (void)seconds; g_wdt_running = false; return 0; }
static int test_ioctl(int fd, int request, unsigned long arg) {
  (void)arg; assert(fd == 3);
  if (request == WDIOC_SETTIMEOUT) {
    if (failure == 4) { errno = ERANGE; return -1; }
    return 0;
  }
  assert(request == WDIOC_START && armed && g_timer_started);
  ++starts;
  if (failure == 3) { errno = EIO; return -1; }
  return 0;
}
#define open test_open
#define close test_close
#define ioctl test_ioctl
#define sigaction test_sigaction
#define timer_create test_timer_create
#define timer_settime test_timer_settime
#define timer_delete test_timer_delete
#define sleep test_sleep
'''
        # A function-like macro preserves the public struct sigaction name.
        code = code.replace('#define sigaction test_sigaction', '#define sigaction(...) test_sigaction(__VA_ARGS__)')
        code += 'static int wdt_stop_timer(void);\n'
        code += definition(source, 'static int wdt_start_timer(void)')
        code += definition(source, 'static int wdt_stop_timer(void)')
        code += definition(source, 'int wdt_test_main(int argc, char *argv[])') + r'''
int main(void) {
  char *argv[] = {"wdt_test", NULL};
  const int errors[] = {0, -EAGAIN, -EINVAL, -EIO, -ERANGE, -EPERM};
  for (failure = 1; failure <= 5; ++failure) {
    current_action.sa_handler = SIG_IGN;
    starts = created = deleted = closed = armed = 0;
    assert(wdt_test_main(1, argv) == errors[failure]);
    assert(!g_wdt_running && !g_timer_started && !g_action_installed);
    assert(current_action.sa_handler == SIG_IGN && closed == 1);
    assert(starts == (failure == 3));
    assert(created == deleted);
  }
  for (failure = 2; failure <= 3; ++failure) {
    for (cleanup_failure = 1; cleanup_failure <= 3; ++cleanup_failure) {
      assert(wdt_test_main(1, argv) == errors[failure]);
      assert(g_timer_started == (cleanup_failure == 2));
      assert(g_action_installed == (cleanup_failure != 1));
      int old_failure = cleanup_failure;
      cleanup_failure = 0;
      assert(wdt_stop_timer() == 0 && !g_timer_started && !g_action_installed);
      cleanup_failure = old_failure;
    }
    cleanup_failure = 0;
  }
  failure = 0;
  for (cleanup_failure = 1; cleanup_failure <= 3; ++cleanup_failure) {
    assert(wdt_start_timer() == 0);
    int result = wdt_stop_timer();
    assert(result == (cleanup_failure == 1 ? -EINTR :
                      cleanup_failure == 2 ? -EBUSY : -EACCES));
    assert(g_timer_started == (cleanup_failure == 2));
    assert(g_action_installed == (cleanup_failure != 1));
    if (cleanup_failure != 1) assert(wdt_start_timer() == -EBUSY);
    int previous_failure = cleanup_failure;
    cleanup_failure = 0;
    assert(wdt_stop_timer() == 0 && !g_timer_started && !g_action_installed);
    assert(current_action.sa_handler == SIG_IGN);
    cleanup_failure = previous_failure;
  }
  cleanup_failure = 0;
  failure = 0; starts = created = deleted = closed = armed = 0;
  assert(wdt_test_main(1, argv) == 0 && starts == 1 && created == deleted);
  assert(!g_timer_started && !g_action_installed && !armed && closed == 1);
  assert(current_action.sa_handler == SIG_IGN);
  return 0;
}
'''
        BOUNDARIES.compile_run(code)


if __name__ == '__main__':
    unittest.main()
