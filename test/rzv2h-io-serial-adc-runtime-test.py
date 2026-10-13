#!/usr/bin/env python3
"""Exercise native serial/address contracts and the PX4 ADC scan lifecycle."""
from pathlib import Path
import importlib.util
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'remediation', ROOT / 'test/rzv2h-audit-remediation-runtime-test.py')
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)
ARCH = RUNTIME.ARCH
PRE = RUNTIME.PRE
header = RUNTIME.header
extract = RUNTIME.extract
run = RUNTIME.run


class IOContracts(unittest.TestCase):
    def test_io_serial_hooks_use_native_channel_and_status_contract(self):
        for board in ('rdk-rzv2h-io-cm33', 'rdk-rzv2h-io-cr8_1'):
            for enabled in (False, True):
                with self.subTest(board=board, enabled=enabled):
                    source = (ROOT / 'boards/renesas' / board / 'src/init.c').read_text()
                    signature = re.search(r'(?:int|void) rzv2h_serial_setup\([^\n]*', source).group()
                    code = PRE + 'struct serial_icounter_struct;\n'
                    code += header(ARCH / 'rzv_serial.h')
                    if enabled:
                        code += '#define CONFIG_RZV_SCI1 1\n'
                    code += r'''
#define BOARD_SCI1_TXD_GPIO 52
#define BOARD_SCI1_RXD_GPIO 53
#define GPIO_TXD1_MOSI1_SDA1_P5_2_M1 BOARD_SCI1_TXD_GPIO
#define GPIO_RXD1_MISO1_SCL1_P5_3_M1 BOARD_SCI1_RXD_GPIO
static int calls, failure_at;
static int px4_arch_configgpio(unsigned pin) {
  assert(pin == (calls % 2 ? BOARD_SCI1_RXD_GPIO : BOARD_SCI1_TXD_GPIO));
  ++calls; return calls == failure_at ? -EIO : 0;
}
''' + extract(source, signature) + r'''
int main(void) {
  int (*setup)(int) = &rzv2h_serial_setup;
  assert(setup(-2) == -EINVAL && setup(10) == -EINVAL && calls == 0);
  assert(setup(0) == 0 && setup(9) == 0 && calls == 0);
#ifdef CONFIG_RZV_SCI1
  assert(setup(1) == 0 && calls == 2);
  calls = 0; failure_at = 1;
  assert(setup(1) == -EIO && calls == 1);
  calls = 0; failure_at = 2;
  assert(setup(-1) == -EIO && calls == 2);
  calls = 0; failure_at = 0;
  assert(setup(-1) == 0 && calls == 2);
#else
  assert(setup(1) == 0 && setup(-1) == 0 && calls == 0);
#endif
}
'''
                    # The disabled build must not depend on any GPIO calls.
                    code = code.replace('static int px4_arch_configgpio',
                                        'static __attribute__((unused)) int px4_arch_configgpio')
                    run(code)

    def test_sci_gpio_aliases_match_each_core_and_keep_overrides(self):
        # Matched R9A09G057H CMSIS SCI-B/GPIO headers: cr vs cm iodefines.
        for cm33 in (False, True):
            for override in (False, True):
                with self.subTest(cm33=cm33, override=override):
                    code = PRE
                    if cm33:
                        code += '#define CONFIG_RZV2H_BUILD_CM33 1\n'
                    if override:
                        for channel in range(10):
                            code += f'#define RZV_SCI{channel}_BASE 0x{0x1000 + channel * 0x100:x}u\n'
                        code += '#define RZV_GPIO0_BASE 0x12340000u\n'
                    code += header(ARCH / 'hardware/rzv_sci.h')
                    code += header(ARCH / 'hardware/rzv_gpio.h')
                    code += '\nint main(void) {\n'
                    for channel in range(10):
                        base = (0x1000 + channel * 0x100 if override else
                                (0x42800C00 if cm33 else 0x12800C00) + channel * 0x400)
                        code += f'assert(RZV_SCI{channel}_BASE == 0x{base:x}u);\n'
                    gpio = 0x12340000 if override else (0x40410020 if cm33 else 0x10410020)
                    code += f'assert(RZV_GPIO_BASE == 0x{gpio:x}u);\n}}\n'
                    run(code)

    def test_adc_samples_trigger_native_scans_and_bound_failures(self):
        native = (ARCH / 'rzv_adc.c').read_text()
        adc_header = (RUNTIME.NUTTX / 'include/nuttx/analog/adc.h').read_text()
        record = re.search(r'struct adc_msg_s\s*\{.*?\n\}[^;]*;', adc_header, re.S).group()
        code = PRE + r'''
#include <deque>
#include <fcntl.h>
#define CONFIG_ADC 1
#define PX4_ERR(...) ((void)0)
#define PX4_INFO(...) ((void)0)
#define aerr(...) ((void)0)
#define ainfo(...) ((void)0)
#define BOARD_ADC_VREF 3300
#define ADC_RESOLUTION_BITS 12
#define __BEGIN_DECLS extern "C" {
#define __END_DECLS }
#define ANIOC_TRIGGER 1
#define ANIOC_GET_NCHANNELS 2
#define ADC_ADCSR_ADST ADC_E_ADCSR_ADST
#define ADC_ADCSR_ADIE ADC_E_ADCSR_ADIE
#define ADC_ADCER_ADPRC_12BIT 0
#define RZV_ADC_MAX_CHANNELS 8
#define end_packed_struct __attribute__((packed))
typedef int sem_t;
struct adc_dev_s { void *ad_priv; };
struct adc_callback_s { int (*au_receive)(adc_dev_s *, uint8_t, int32_t); };
''' + header(ROOT / 'src/drivers/drv_adc.h').replace('#pragma once', '') + '\n' + record
        code += header(ARCH / 'hardware/rzv_adc.h')
        for name in ('rzv_adc_config_s', 'rzv_adc_priv_s'):
            code += re.search(r'struct ' + name + r'\s*\{.*?\n\};', native, re.S).group() + '\n'
        code += r'''
static uint16_t regs[1024];
static unsigned starts, elapsed, delay_us = 50, ioctl_error, read_error;
static bool stalled, malformed;
static std::deque<adc_msg_s> fifo;
static uint16_t rzv_adc_getreg(rzv_adc_priv_s *, unsigned off) { return regs[off]; }
static void rzv_adc_putreg(rzv_adc_priv_s *, unsigned off, uint16_t value) { regs[off] = value; }
static void rzv_adc_putreg8(rzv_adc_priv_s *, unsigned off, uint8_t value) { regs[off] = value; }
static void rzv_adc_modifyreg(rzv_adc_priv_s *, unsigned off, uint16_t clear, uint16_t set) {
  if (off == RZV_ADC_E_ADCSR_OFFSET && (set & ADC_ADCSR_ADST)) { ++starts; elapsed = 0; }
  regs[off] = (regs[off] & ~clear) | set;
}
static int rzv_icu_attach(int, int (*)(int, void *, void *), void *, bool) { return 400; }
static int nxsem_wait_uninterruptible(int *) { return 0; }
static int nxsem_post(int *) { return 0; }
'''
        for signature in ('static void rzv_adc_reset(', 'static int rzv_adc_interrupt(',
                          'static int rzv_adc_setup(', 'static void rzv_adc_rxint(',
                          'static int rzv_adc_ioctl('):
            code += extract(native, signature)
        code += r'''
static rzv_adc_config_s config{};
static rzv_adc_priv_s priv{};
static adc_dev_s dev{&priv};
static int receive(adc_dev_s *, uint8_t channel, int32_t value) {
  adc_msg_s sample{}; sample.am_channel = channel; sample.am_data = value;
  fifo.push_back(sample); return 0;
}
static adc_callback_s callback{receive};
static void complete_scan() {
  if (!(regs[RZV_ADC_E_ADCSR_OFFSET] & ADC_ADCSR_ADST) || stalled || elapsed < delay_us) return;
  regs[RZV_ADC_E_ADDR_OFFSET(0)] = 1000 + starts;
  regs[RZV_ADC_E_ADDR_OFFSET(7)] = 2000 + starts;
  regs[RZV_ADC_E_ADCSR_OFFSET] &= ~ADC_ADCSR_ADST;
  assert(rzv_adc_interrupt(400, nullptr, &priv) == 0);
}
[[maybe_unused]] static void up_udelay(unsigned us) { elapsed += us; complete_scan(); }
[[maybe_unused]] static int adapter_ioctl(int, int command, unsigned long arg) {
  if (ioctl_error) { errno = ioctl_error; return -1; }
  int ret = rzv_adc_ioctl(&dev, command, arg);
  if (ret < 0) { errno = -ret; return -1; }
  return ret;
}
static int adapter_open(const char *, int) {
  priv.dev = &dev; priv.cb = &callback; priv.config = &config;
  priv.chanmask = 0x81; priv.nchannels = 2;
  fifo.clear(); assert(rzv_adc_setup(&dev) == 0); rzv_adc_rxint(&dev, true); return 9;
}
static int adapter_close(int) { rzv_adc_rxint(&dev, false); rzv_adc_reset(&priv); return 0; }
static ssize_t adapter_read(int, void *data, size_t size) {
  if (read_error) { errno = read_error; return -1; }
  if (malformed) { memset(data, 0, 1); return 1; }
  complete_scan();
  if (fifo.empty()) { errno = EAGAIN; return -1; }
  size_t count = 0;
  while (!fifo.empty() && count + sizeof(adc_msg_s) <= size) {
    memcpy(static_cast<char *>(data) + count, &fifo.front(), sizeof(adc_msg_s));
    fifo.pop_front(); count += sizeof(adc_msg_s);
  }
  return count;
}
#define open adapter_open
#define close adapter_close
#define read adapter_read
#define ioctl adapter_ioctl
''' + header(ROOT / 'platforms/nuttx/src/px4/renesas/rzv/adc/adc.cpp')
        code += r'''
int main() {
  static_assert(sizeof(adc_msg_s) == 5 && sizeof(px4_adc_msg_t) == 5);
  uint32_t (*sample)(uint32_t, unsigned) = &px4_arch_adc_sample;
  assert(sample(0, 0) == UINT32_MAX);
  assert(px4_arch_adc_init(0) == 0 && starts == 0);
  for (unsigned i = 1; i <= 10; ++i) {
    assert(sample(0, 0) == 1000 + i && starts == i);
    assert(elapsed >= delay_us && elapsed <= 1000);
  }
  assert(sample(0, 7) == 2011 && starts == 11);
  // A queued old record must not satisfy a new request.
  adc_msg_s stale{}; stale.am_data = 1; fifo.push_back(stale);
  assert(sample(0, 0) == 1012 && starts == 12);
  assert(sample(0, 8) == UINT32_MAX && starts == 12);
  stalled = true;
  assert(sample(0, 0) == UINT32_MAX && elapsed <= 1000);
  assert(!g_sample_valid[0] && !g_sample_valid[7]);
  // Existing in-flight scan can complete after EBUSY without an extra start.
  stalled = false; elapsed = 0;
  assert(sample(0, 7) == 2013 && starts == 13);
  ioctl_error = EIO;
  assert(sample(0, 0) == UINT32_MAX && !g_sample_valid[0]); ioctl_error = 0;
  read_error = EBADF;
  assert(sample(0, 7) == UINT32_MAX && !g_sample_valid[7]); read_error = 0;
  malformed = true;
  assert(sample(0, 0) == UINT32_MAX); malformed = false;
  assert(sample(0, 1) == UINT32_MAX && elapsed <= 1000);
  px4_arch_adc_uninit(0);
  assert(sample(0, 0) == UINT32_MAX && g_adc_fd == -1);
  assert(px4_arch_adc_init(0) == 0 && sample(0, 0) == 1015);
  px4_arch_adc_uninit(0);
}
'''
        run(code, cpp=True)


if __name__ == '__main__':
    unittest.main()
