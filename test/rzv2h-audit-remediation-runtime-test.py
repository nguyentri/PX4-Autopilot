#!/usr/bin/env python3
"""Run repaired production entry points at explicit host I/O boundaries."""
from pathlib import Path
import importlib.util
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / 'platforms/nuttx/NuttX/nuttx'
ARCH = NUTTX / 'arch/arm/src/rzv'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)
extract = BOUNDARY.EXTRACT.definition
PRE = BOUNDARY.PRELUDE + '#include <sys/types.h>\n#define FAR\n#define DEBUGASSERT assert\n'


def run(code, cpp=False):
    with tempfile.TemporaryDirectory(prefix='rzv2h-remediation-runtime-') as directory:
        path = Path(directory)
        source = path / ('test.cpp' if cpp else 'test.c')
        source.write_text(code)
        subprocess.run(['c++' if cpp else 'cc', '-std=c++17' if cpp else '-std=c11',
                        '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
                        str(source), '-o', str(path / 'test')], check=True)
        subprocess.run([str(path / 'test')], check=True)


def header(path):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', path.read_text(), flags=re.M)


def raw_write_fake():
    """Host write() with the raw IPC driver's contract: one whole ring entry
    per call, anything else fails with EMSGSIZE as rzv_ipc_raw_write() does."""
    driver = (ARCH / 'rzv_ipc_raw.c').read_text()
    assert re.search(r'if \(buflen != RZV_IPC_RAW_PAYLOAD_SIZE\)\s*\{\s*return -EMSGSIZE;', driver)
    size = re.search(r'^#define RZV_IPC_RAW_PAYLOAD_SIZE\s+(\d+)u?$',
                     (NUTTX / 'include/nuttx/ipc/rzv_ipc_raw.h').read_text(), flags=re.M).group(1)
    return r'''
#include <array>
#include <deque>
static constexpr size_t RAW_ENTRY_SIZE = ''' + size + r''';
static std::deque<std::array<uint8_t, RAW_ENTRY_SIZE>> written;
static ssize_t test_write(int fd, const void *data, size_t size) {
  if (size != RAW_ENTRY_SIZE) { errno = EMSGSIZE; return -1; }
  std::array<uint8_t, RAW_ENTRY_SIZE> frame{}; memcpy(frame.data(), data, size); written.push_back(frame); return size;
}
'''


def raw_ioctl_fake():
    """Host ioctl() over the public raw IPC contract (stats and recovery
    request codes from the real header); tests set the stats or an errno."""
    contract = header(NUTTX / 'include/nuttx/ipc/rzv_ipc_raw.h')
    return '#define _DIOC(nr) (0x0d00 | (nr))\n' + contract + r'''
#include <vector>
static struct rzv_ipc_raw_stats_s raw_stats{};
static int raw_ioctl_errno;
static std::vector<int> raw_ioctl_calls;
inline int test_ioctl(int fd, int cmd, unsigned long arg) {
  raw_ioctl_calls.push_back(cmd);
  if (raw_ioctl_errno != 0) { errno = raw_ioctl_errno; return -1; }
  if (cmd == RZV_IPC_RAWIOC_GET_STATS) memcpy(reinterpret_cast<void *>(arg), &raw_stats, sizeof(raw_stats));
  return 0;
}
#define ioctl test_ioctl
'''


def cr8_1_transport_harness(owner=ROOT / 'boards/renesas/rdk-rzv2h-io-cr8_1/px4io_cr8_1'):
    """IO-core SharedMemTransport over an in-memory IPCC entry queue."""
    code = PRE + r'''
#include <deque>
#include <array>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
''' + header(owner / 'protocol.h').replace('#pragma once', '')
    code += header(owner / 'sharedmem_transport.h').replace('#pragma once', '')
    code += r'''
static std::deque<std::array<uint8_t, 64>> entries;
static ssize_t test_read(int fd, void *data, size_t size) {
  if (entries.empty()) { errno = EAGAIN; return -1; }
  memcpy(data, entries.front().data(), size); entries.pop_front(); return size;
}
''' + raw_write_fake() + raw_ioctl_fake() + r'''
static int test_open(const char *path, int flags) { return 123; }
static int test_close(int fd) { return 0; }
static uint64_t hrt_absolute_time() { return 10; }
[[maybe_unused]] static int poll_calls, poll_timeout, poll_result = 1;
[[maybe_unused]] static short poll_revents = POLLIN;
[[maybe_unused]] static int test_poll(struct pollfd *fds, nfds_t count, int timeout) {
  assert(count == 1 && fds[0].fd == 123 && fds[0].events == POLLIN);
  ++poll_calls; poll_timeout = timeout; fds[0].revents = poll_result > 0 ? poll_revents : 0;
  return poll_result;
}
#define poll test_poll
#define read test_read
#define write test_write
#define open test_open
#define close test_close
'''
    code += header(owner / 'sharedmem_transport.cpp')
    code += r'''
static uint32_t crc(const uint8_t *data, size_t size) {
  uint32_t value = 0xffffffffu;
  for (size_t i = 0; i < size; ++i) {
    value ^= data[i];
    for (int j = 0; j < 8; ++j) value = (value >> 1) ^ ((value & 1) ? 0xedb88320u : 0);
  }
  return ~value;
}
template<typename T> static void push(T msg, int type, unsigned sequence, bool bad = false) {
  msg.header.magic = IPC_MAGIC; msg.header.version = IPC_PROTOCOL_VERSION;
  msg.header.msg_type = type; msg.header.sequence = sequence; msg.header.crc32 = 0;
  msg.header.crc32 = crc(reinterpret_cast<uint8_t *>(&msg), sizeof(msg));
  if (bad) ++msg.header.crc32;
  std::array<uint8_t, 64> frame{}; memcpy(frame.data(), &msg, sizeof(msg)); entries.push_back(frame);
}
template<typename T> static void enqueue(int type, unsigned sequence, bool bad = false) {
  push(T{}, type, sequence, bad);
}
'''
    return code


class RepairRuntime(unittest.TestCase):
    def test_irq_clock_and_reset_fail_closed(self):
        source = (ARCH / 'rzv_irq.c').read_text()
        code = PRE + r'''
#define RZV_CPG_CLK_ICU 5
#define _err(...) ((void)0)
static int clock_error, reset_error, resets, panic_count, gic, icu, enabled;
#define PANIC() (++panic_count)
static int rzv_clock_enable(int id) { return clock_error; }
static int rzv_module_unreset(int id) { ++resets; return reset_error; }
static void rzv_gic_initialize(void) { ++gic; }
static void rzv_icu_initialize(void) { ++icu; }
static void up_irq_enable(void) { ++enabled; }
''' + extract(source, 'void up_irqinitialize(') + r'''
int main(void) {
  clock_error = -ETIMEDOUT;
  up_irqinitialize();
  assert(panic_count == 1 && !resets && !gic && !icu && !enabled);
  clock_error = 0; reset_error = -EIO;
  up_irqinitialize();
  assert(panic_count == 2 && resets == 1 && !gic && !icu && !enabled);
  reset_error = 0;
  up_irqinitialize();
  assert(panic_count == 2 && gic == 1 && icu == 1 && enabled == 1);
}
'''
        run(code)

    def test_spi_send_preserves_failure_sentinel_at_all_widths(self):
        source = (ARCH / 'rzv_spi.c').read_text()
        code = PRE + header(ARCH / 'hardware/rzv_spi.h') + r'''
#define CONFIG_RZV_SPI0_DMA 1
#define SPI_TIMEOUT_CYCLES 2
#define spierr(...) ((void)0)
struct spi_dev_s { int unused; };
struct rzv_spi_config_s { int dma_tx_channel, port; };
struct rzv_spi_priv_s { struct spi_dev_s dev; struct rzv_spi_config_s *config; unsigned nbits; };
static int failure;
static void rzv_spi_setbitorder(struct rzv_spi_priv_s *p, bool order) {}
static size_t rzv_spi_wordsize(struct rzv_spi_priv_s *p) { return p->nbits / 8; }
static int rzv_spi_dma_exchange(struct rzv_spi_priv_s *p, const void *tx, void *rx, size_t bytes) {
  *(uint32_t *)rx = 0xaabbccddu; return failure;
}
static uint32_t rzv_spi_getreg32(struct rzv_spi_priv_s *p, unsigned off) { return 0; }
static void rzv_spi_putreg32(struct rzv_spi_priv_s *p, unsigned off, uint32_t value) {}
''' + extract(source, 'static uint32_t rzv_spi_send(struct spi_dev_s *dev, uint32_t wd)\n') + r'''
int main(void) {
  struct rzv_spi_config_s cfg = {.dma_tx_channel = 48};
  struct rzv_spi_priv_s p = {.config = &cfg};
  const unsigned widths[] = {8, 16, 32};
  const uint32_t values[] = {0xdd, 0xccdd, 0xaabbccdd};
  for (unsigned i = 0; i < 3; ++i) {
    p.nbits = widths[i]; failure = -EIO;
    assert(rzv_spi_send(&p.dev, 123) == UINT32_MAX);
    failure = -ETIMEDOUT; assert(rzv_spi_send(&p.dev, 123) == UINT32_MAX);
    failure = 0; assert(rzv_spi_send(&p.dev, 123) == values[i]);
  }
}
'''
        run(code)

    def test_buffered_ipcc_retains_failed_packets_in_order(self):
        circ = (NUTTX / 'mm/circbuf/circbuf.c').read_text()
        code = PRE + header(NUTTX / 'include/nuttx/mm/circbuf.h')
        for signature in ('size_t circbuf_used(', 'ssize_t circbuf_peekat(',
                          'ssize_t circbuf_peek(', 'ssize_t circbuf_skip('):
            code += extract(circ, signature)
        code += r'''
#define RZV_OPENAMP_RPMSG_BUFFER_SIZE 4
struct ipcc_lower_s { struct circbuf_s txbuf; };
static int g_rzv_ipcc_txlock;
static int nxmutex_lock(int *m) { return 0; }
static int nxmutex_unlock(int *m) { return 0; }
static ssize_t result;
static char sent[4];
static ssize_t rzv_rpmsg_send(const char *data, size_t size) {
  memcpy(sent, data, size); return result;
}
''' + extract((ARCH / 'rzv_ipc_ipcc.c').read_text(), 'static ssize_t rzv_ipcc_write_notify(') + r'''
int main(void) {
  char data[8] = "efghabcd";
  struct ipcc_lower_s lower = {.txbuf = {.base = data, .size = 8, .head = 12, .tail = 4}};
  result = -ENODEV;
  assert(rzv_ipcc_write_notify(&lower) == -ENODEV && lower.txbuf.tail == 4);
  assert(memcmp(sent, "abcd", 4) == 0);
  result = -ENOMEM;
  assert(rzv_ipcc_write_notify(&lower) == -ENOMEM && lower.txbuf.tail == 4);
  result = 4;
  assert(rzv_ipcc_write_notify(&lower) == 4 && lower.txbuf.tail == 8);
  assert(memcmp(sent, "abcd", 4) == 0);
  assert(rzv_ipcc_write_notify(&lower) == 4 && lower.txbuf.tail == 12);
  assert(memcmp(sent, "efgh", 4) == 0);
  assert(rzv_ipcc_write_notify(&lower) == 0);
}
'''
        run(code)

    def test_riic_short_reads_and_continuations_program_nack_before_data(self):
        source = (ARCH / 'rzv_i2c.c').read_text()
        code = '#define _POSIX_C_SOURCE 200809L\n' + PRE
        code += header(NUTTX / 'include/nuttx/nuttx.h')
        code += header(ARCH / 'hardware/rzv_i2c.h') + r'''
#include <time.h>
#define RIIC_TIMEOUT_MS 1000
#define i2cerr(...) ((void)0)
typedef unsigned irqstate_t;
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) {}
struct i2c_master_s { int unused; };
#define I2C_M_READ 1
#define I2C_M_NOSTART 0x0080
struct i2c_msg_s { uint16_t addr, flags; uint8_t *buffer; int length; };
''' + re.search(r'enum rzv_i2c_state_e\n\{.*?\n\};', source, re.S).group() + '\n' + re.search(r'struct rzv_i2c_priv_s\n\{.*?\n\};', source, re.S).group().replace('sem_t ', 'int ') + '\n'
        code += r'''
static uint8_t regs[256];
static int reads, target, stop_requested, posts, restarts, resets, unlocks, wait_mode;
static int chain_scans, dummy_pending;
static struct rzv_i2c_priv_s *active;
static void rzv_icu_clear_irq(int irq) {}
static int nxsem_post(int *sem) {
  if (active && sem == &active->sem_excl) {
    assert(active->state == RIIC_STATE_IDLE && !regs[RZV_RIIC_ICIER_OFFSET]); ++unlocks;
  } else ++posts;
  return 0;
}
static int nxsem_wait_uninterruptible(int *sem) { return 0; }
static int nxsem_reset(int *sem, int value) { return 0; }
static int nxsem_timedwait_uninterruptible(int *sem, struct timespec *ts);
static uint8_t rzv_i2c_getreg(struct rzv_i2c_priv_s *p, unsigned off) {
  if (off == RZV_RIIC_ICDRR_OFFSET) {
    if (dummy_pending) {dummy_pending=0;assert(p->read_remaining==(uint64_t)target);return 0;}
    if (target - reads <= 2 && !restarts) assert(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_ACKBT);
    if (target - reads == 1) assert(stop_requested || restarts);
    return (uint8_t)++reads;
  }
  return regs[off];
}
static void rzv_i2c_putreg(struct rzv_i2c_priv_s *p, unsigned off, uint8_t val) {
  if (off == RZV_RIIC_ICMR3_OFFSET && ((val ^ regs[off]) & RIIC_ICMR3_ACKBT))
    assert(regs[off] & RIIC_ICMR3_ACKWP);
  if (off == RZV_RIIC_ICCR2_OFFSET && (val & RIIC_ICCR2_RS)) {
    assert(!(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_ACKBT)); ++restarts;
  }
  if (off == RZV_RIIC_ICCR1_OFFSET && (val & RIIC_ICCR1_IICRST) &&
      !(regs[off] & RIIC_ICCR1_IICRST)) {
    assert(!regs[RZV_RIIC_ICIER_OFFSET]); ++resets; memset(regs, 0, sizeof(regs));
  }
  regs[off] = val;
}
static void rzv_i2c_sendstop(struct rzv_i2c_priv_s *p) { ++stop_requested; }
'''
        for signature in ('static void rzv_i2c_set_nack(', 'static void rzv_i2c_abort(',
                          'static void rzv_i2c_sendstart(', 'static void rzv_i2c_sendaddr(',
                          'static void rzv_i2c_irq_nextmsg(',
                          'static uint64_t rzv_i2c_read_remaining(', 'static int rzv_i2c_rxi_interrupt(',
                          'static int rzv_i2c_txi_interrupt(',
                          'static int rzv_i2c_err_interrupt(', 'static int rzv_i2c_stp_interrupt(',
                          'static int rzv_i2c_transfer(struct i2c_master_s *dev,\n'):
            definition = extract(source, signature)
            if signature == 'static uint64_t rzv_i2c_read_remaining(':
                definition = definition.replace('\n{', '\n{\n  ++chain_scans;', 1)
            code += definition
        code += r'''
static void check(int length, bool split) {
  uint8_t data[5] = {0};
  struct i2c_msg_s msgs[2] = {{.flags = I2C_M_READ, .buffer = data, .length = split ? 1 : length},
    {.flags = I2C_M_READ | I2C_M_NOSTART, .buffer = data + 1, .length = length - 1}};
  struct rzv_i2c_priv_s p = {.msgs = msgs, .msgc = split ? 2 : 1,
    .ptr = data, .dcnt = msgs[0].length, .state = RIIC_STATE_DATA_READ};
  memset(regs, 0, sizeof(regs)); reads = stop_requested = posts = restarts = 0; target = length;
  regs[RZV_RIIC_ICMR3_OFFSET] = RIIC_ICMR3_WAIT;
  chain_scans = 0;
  p.state = RIIC_STATE_ADDR_READ;dummy_pending=1;
  rzv_i2c_txi_interrupt(1,NULL,&p);
  for (int i = 0; i < length; ++i) rzv_i2c_rxi_interrupt(1, NULL, &p);
  assert(chain_scans == 1 && p.read_remaining == 0);
  assert(reads == length && stop_requested == 1 && p.state == RIIC_STATE_STOP);
  assert(!(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_WAIT));
  for (int i = 0; i < length; ++i) assert(data[i] == i + 1);
  rzv_i2c_stp_interrupt(1, NULL, &p); assert(!posts);
  regs[RZV_RIIC_ICSR2_OFFSET] = RIIC_ICSR2_STOP;
  rzv_i2c_stp_interrupt(1, NULL, &p); assert(posts == 1 && p.state == RIIC_STATE_IDLE);
  rzv_i2c_stp_interrupt(1, NULL, &p); assert(posts == 1);
  rzv_i2c_set_nack(&p, false); assert(!(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_ACKBT));
}
static void check_restart(void) {
  uint8_t data[2] = {0};
  struct i2c_msg_s msgs[2] = {{.flags = I2C_M_READ, .buffer = data, .length = 2},
    {.buffer = data, .length = 1}};
  struct rzv_i2c_priv_s p = {.msgs = msgs, .msgc = 2,
    .ptr = data, .dcnt = 2, .state = RIIC_STATE_DATA_READ};
  memset(regs, 0, sizeof(regs)); reads = stop_requested = posts = restarts = 0; target = 2;
  p.state = RIIC_STATE_ADDR_READ;dummy_pending=1;
  rzv_i2c_txi_interrupt(1,NULL,&p);
  regs[RZV_RIIC_ICMR3_OFFSET] = RIIC_ICMR3_WAIT;
  rzv_i2c_rxi_interrupt(1, NULL, &p);
  assert(regs[RZV_RIIC_ICMR3_OFFSET] & RIIC_ICMR3_ACKBT);
  rzv_i2c_rxi_interrupt(1, NULL, &p);
  assert(restarts == 1 && reads == 2 && !stop_requested && !posts);
  assert(p.state == RIIC_STATE_RESTART && (regs[RZV_RIIC_ICIER_OFFSET] & RIIC_ICIER_TIE));
}
static int nxsem_timedwait_uninterruptible(int *sem, struct timespec *ts) {
  regs[RZV_RIIC_ICSR2_OFFSET] = RIIC_ICSR2_NACKF;
  rzv_i2c_err_interrupt(1, NULL, active);
  assert(!posts && active->state == RIIC_STATE_STOP && active->result == -ENXIO);
  assert(regs[RZV_RIIC_ICIER_OFFSET] == RIIC_ICIER_SPIE);
  assert(regs[RZV_RIIC_ICSR2_OFFSET] & RIIC_ICSR2_NACKF);
  if (wait_mode) return -ETIMEDOUT;
  regs[RZV_RIIC_ICSR2_OFFSET] |= RIIC_ICSR2_STOP;
  rzv_i2c_stp_interrupt(1, NULL, active);
  rzv_i2c_stp_interrupt(1, NULL, active);
  assert(posts == 1 && active->result == -ENXIO);
  return 0;
}
static void check_errors(void) {
  struct rzv_i2c_priv_s p = {0}; active = &p;
  uint8_t data = 0; struct i2c_msg_s msg = {.buffer = &data, .length = 1};
  for (int mode = 0; mode < 2; ++mode) {
    memset(regs, 0, sizeof(regs)); posts = resets = unlocks = 0; wait_mode = mode;
    regs[RZV_RIIC_ICBRH_OFFSET] = 7; regs[RZV_RIIC_ICBRL_OFFSET] = 9;
    assert(rzv_i2c_transfer(&p.dev, &msg, 1) == -ENXIO);
    assert(unlocks == 1 && resets == mode && posts == (mode ? 0 : 1));
    assert(regs[RZV_RIIC_ICBRH_OFFSET] == 7 && regs[RZV_RIIC_ICBRL_OFFSET] == 9);
    assert(!regs[RZV_RIIC_ICSR2_OFFSET]);
  }
  const unsigned errors[] = {RIIC_ICSR2_AL, RIIC_ICSR2_TMOF, RIIC_ICSR2_NACKF};
  const int results[] = {-EAGAIN, -ETIMEDOUT, -ENXIO};
  for (unsigned i = 0; i < 3; ++i) {
    p.state = RIIC_STATE_DATA_WRITE; posts = resets = 0;
    regs[RZV_RIIC_ICCR2_OFFSET] = 0; regs[RZV_RIIC_ICSR2_OFFSET] = errors[i];
    rzv_i2c_err_interrupt(1, NULL, &p);
    assert(posts == 1 && resets == 1 && p.state == RIIC_STATE_IDLE && p.result == results[i]);
    rzv_i2c_err_interrupt(1, NULL, &p); assert(posts == 1);
  }
  active = NULL;
}
int main(void) {
  check(1, false); check(2, false); check(5, false); check(2, true); check(5, true);
  check_restart(); check_errors();
}
'''
        run(code)

    def test_riic_routes_attach_and_unwind_fixed_stop(self):
        source = (ARCH / 'rzv_i2c.c').read_text()
        code = PRE + header(NUTTX / 'include/nuttx/nuttx.h')
        code += header(ARCH / 'hardware/rzv_i2c.h')
        code += header(NUTTX / 'arch/arm/include/rzv/rzv2h_irq.h')
        code += '#define RZV_IRQ_FIRST 32\n'
        code += re.search(r'enum rzv_i2c_state_e\n\{.*?\n\};', source, re.S).group() + '\n'
        state = re.search(r'struct rzv_i2c_priv_s\n\{.*?\n\};', source, re.S).group()
        code += state.replace('struct i2c_master_s dev;', 'int dev;').replace('sem_t ', 'int ') + '\n'
        fields = re.findall(r'int (irq_\w+);', state)
        code += r'''
#define RZV_CPG_DOMAIN(x) (x)
#define RZV_CPG_BIT(x) (x)
#define RZV_MODULE_CLKON(domain, bit) ((void)(domain), (void)(bit))
#define RZV_MODULE_CLKOFF(domain, bit) ((void)(domain), (void)(bit))
#define i2cerr(...) ((void)0)
typedef int (*xcpt_t)(int, void *, void *);
static bool installed[512], enabled[512], typed[512], edge[512];
static int failure_at, attempts, port;
static void up_udelay(int delay) {}
static void rzv_i2c_set_frequency(struct rzv_i2c_priv_s *p, uint32_t f) {}
static void rzv_i2c_putreg(struct rzv_i2c_priv_s *p, unsigned off, uint8_t val) {}
static int rzv_i2c_rxi_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_i2c_txi_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_i2c_tei_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_i2c_err_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_i2c_stp_interrupt(int irq, void *ctx, void *arg) { return 0; }
static int rzv_icu_attach(int event, xcpt_t handler, void *arg, bool enable) {
  assert(!enable);
  assert((event == 84 + 2 * port && handler == rzv_i2c_rxi_interrupt) ||
         (event == 83 + 2 * port && handler == rzv_i2c_txi_interrupt));
  if (++attempts == failure_at) return -ENOMEM;
  int irq = event == 84 + 2 * port ? 385 : 386;
  assert(!installed[irq]); installed[irq] = true; return irq;
}
static void rzv_icu_detach(int irq) {
  assert(irq == 385 || irq == 386); assert(installed[irq]);
  installed[irq] = enabled[irq] = false;
}
static int irq_attach(int irq, xcpt_t handler, void *arg) {
  int base = 206 + 6 * port;
  assert((irq == base && handler == rzv_i2c_tei_interrupt) ||
         (irq == base + 2 && handler == rzv_i2c_stp_interrupt) ||
         ((irq == base + 1 || irq == base + 4 || irq == base + 5) && handler == rzv_i2c_err_interrupt));
  if (++attempts == failure_at) return -EIO;
  assert(!installed[irq]); installed[irq] = true; return 0;
}
static void __attribute__((unused)) rzv_gic_set_irq_type(int irq, bool pulse) {
  assert(installed[irq] && !enabled[irq]); typed[irq] = true; edge[irq] = pulse;
}
static void up_enable_irq(int irq) { assert(typed[irq] && installed[irq]); enabled[irq] = true; }
static void up_disable_irq(int irq) { enabled[irq] = false; }
static void irq_detach(int irq) {
  assert(irq < 385 && installed[irq] && !enabled[irq]); installed[irq] = false;
}
'''
        if 'static void rzv_i2c_detach_irqs(' in source:
            code += extract(source, 'static void rzv_i2c_detach_irqs(')
        code += extract(source, 'static int rzv_i2c_init(') + extract(source, 'static void rzv_i2c_deinit(')
        code += r'''
int main(void) {
  for (port = 0; port < 4; ++port) for (failure_at = 0; failure_at <= 7; ++failure_at) {
    attempts = 0; memset(typed, 0, sizeof(typed));
    struct rzv_i2c_priv_s p = {.port = port,
''' + ', '.join(f'.{field} = -1' for field in fields) + r'''};
    int ret = rzv_i2c_init(&p);
    if (failure_at) assert(ret == (failure_at <= 2 ? -ENOMEM : -EIO));
    else {
      assert(ret == 0 && attempts == 7 && edge[385] && edge[386]);
      int expected[] = {385, 386, 206 + 6 * port, 207 + 6 * port,
                        208 + 6 * port, 210 + 6 * port, 211 + 6 * port};
      for (unsigned i = 0; i < sizeof(expected) / sizeof(expected[0]); ++i)
        assert(installed[expected[i]] && enabled[expected[i]]);
      rzv_i2c_deinit(&p);
    }
    for (int irq = 0; irq < 512; ++irq) assert(!installed[irq] && !enabled[irq]);
''' + '\n'.join(f'    assert(p.{field} == -1);' for field in fields) + r'''
  }
}
'''
        run(code)


    def test_io_board_initializers_propagate_service_errors(self):
        for core in ('cm33', 'cr8_1'):
            source = (ROOT / f'boards/renesas/rdk-rzv2h-io-{core}/src/init.c').read_text()
            code = PRE + r'''
#define CONFIG_RZV_IPC_RAW 1
static int platform_result, ipc_result, platform_calls, ipc_calls;
static int px4_platform_init(void) { ++platform_calls; return platform_result; }
static int board_ipc_initialize(void) { ++ipc_calls; return ipc_result; }
''' + extract(source, 'int board_app_initialize(') + r'''
int main(void) {
  platform_result = -EIO; assert(board_app_initialize(0) == -EIO);
  assert(platform_calls == 1 && !ipc_calls);
  platform_result = 0; ipc_result = -ENOMEM; assert(board_app_initialize(0) == -ENOMEM);
  assert(platform_calls == 2 && ipc_calls == 1);
  ipc_result = 0; assert(board_app_initialize(0) == 0 && ipc_calls == 2);
}
'''
            run(code)

    def test_cm33_systick_uses_i7clk_and_handles_pending_reload(self):
        source = (ARCH / 'rzv_timerisr_cm33.c').read_text()
        code = PRE + r'''
#include <time.h>
#undef CLOCKS_PER_SEC
#define CLOCKS_PER_SEC 1000
#define USEC_PER_TICK 1000u
#define USEC_PER_SEC 1000000u
#define NSEC_PER_USEC 1000u
#define NVIC_SYSTICK_CTRL 1
#define NVIC_SYSTICK_RELOAD 2
#define NVIC_SYSTICK_CURRENT 3
#define NVIC_INTCTRL 4
#define NVIC_INTCTRL_PENDSTSET (1u << 26)
#define NVIC_INTCTRL_PENDSTCLR (1u << 25)
#define NVIC_SYSTICK_RELOAD_MASK 0x00ffffffu
#define NVIC_SYSTICK_CTRL_ENABLE 1
#define NVIC_SYSTICK_CTRL_TICKINT 2
#define NVIC_SYSTICK_CTRL_CLKSOURCE 4
#define NVIC_IRQ_SYSTICK 15
#define RZV_CLOCK_I7CLK 7
static uint32_t g_systick_period, regs[5], pending_reads;
static int panics, attach_error, attached, ticks;
typedef unsigned irqstate_t;
#define PANIC() (++panics)
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) {}
static clock_t clock_systime_ticks(void) { return ticks; }
static uint32_t rzv_clock_get_rate(int id) { assert(id == RZV_CLOCK_I7CLK); return 200000000; }
static void nxsched_process_timer(void) { ++ticks; }
static uint32_t getreg32(unsigned addr) {
  assert(addr >= 1 && addr <= 4);
  if (addr == NVIC_INTCTRL && ++pending_reads == 2) regs[addr] |= NVIC_INTCTRL_PENDSTSET;
  return regs[addr];
}
static void putreg32(uint32_t value, unsigned addr) { assert(addr >= 1 && addr <= 4); regs[addr] = value; }
static int irq_attach(int irq, int (*handler)(int, void *, void *), void *arg) {
  assert(irq == 15); ++attached; return attach_error;
}
''' + extract(source, 'static int rzv_systick_interrupt(')
        code += extract(source, 'void up_timer_initialize(')
        code += extract(source, 'int up_timer_gettime(') + r'''
int main(void) {
  attach_error = -ENOMEM; up_timer_initialize();
  assert(panics == 1 && regs[NVIC_SYSTICK_CTRL] == 0);
  attach_error = 0; up_timer_initialize();
  assert(g_systick_period == 200000 && regs[NVIC_SYSTICK_RELOAD] == 199999);
  assert(regs[NVIC_SYSTICK_CTRL] == 7 && attached == 2);
  ticks = 10; regs[NVIC_INTCTRL] = 0; regs[NVIC_SYSTICK_CURRENT] = 199999;
  struct timespec ts; assert(up_timer_gettime(&ts) == 0);
  assert(ts.tv_sec == 0 && ts.tv_nsec == 11000000);
  rzv_systick_interrupt(15, NULL, NULL); assert(ticks == 11);
  regs[NVIC_INTCTRL] = 0; pending_reads = 10; regs[NVIC_SYSTICK_CURRENT] = 1;
  up_timer_gettime(&ts); long before = ts.tv_nsec;
  regs[NVIC_SYSTICK_CURRENT] = 0; up_timer_gettime(&ts); assert(ts.tv_nsec >= before);
  before = ts.tv_nsec; regs[NVIC_INTCTRL] = NVIC_INTCTRL_PENDSTSET;
  up_timer_gettime(&ts); assert(ts.tv_nsec >= before); before = ts.tv_nsec;
  regs[NVIC_SYSTICK_CURRENT] = 199999; up_timer_gettime(&ts); assert(ts.tv_nsec >= before);
}
'''
        run(code)

    def test_adc_cache_reads_changing_records_and_reports_errors(self):
        source = (ROOT / 'platforms/nuttx/src/px4/renesas/rzv/adc/adc.cpp').read_text()
        adc_header = (NUTTX / 'include/nuttx/analog/adc.h').read_text()
        record = re.search(r'struct adc_msg_s\s*\{.*?\n\}[^;]*;', adc_header, re.S).group()
        code = PRE + r'''
#include <unistd.h>
#include <fcntl.h>
#define __BEGIN_DECLS extern "C" {
#define __END_DECLS }
#define PX4_ERR(...) ((void)0)
#define PX4_INFO(...) ((void)0)
#define ADC_MAX_CHANNELS 8
#define ADC_SAMPLE_COUNT 8
#define ADC_BASE_PATH "/dev/adc"
#define BOARD_ADC_VREF 3300
#define ADC_RESOLUTION_BITS 12
#define end_packed_struct __attribute__((packed))
''' + header(ROOT / 'src/drivers/drv_adc.h').replace('#pragma once', '') + '\n' + record + r'''
static int g_adc_fd = -1;
static px4_adc_msg_t g_samples[ADC_MAX_CHANNELS];
static bool g_sample_valid[ADC_MAX_CHANNELS];
int px4_arch_adc_update();
'''
        for signature in ('int px4_arch_adc_init(', 'void px4_arch_adc_uninit(',
                          'float px4_arch_adc_reference_v(',
                          'uint32_t px4_arch_adc_temp_sensor_mask(', 'uint32_t px4_arch_adc_dn_fullcount(',
                          'int px4_arch_adc_update()\n'):
            code += extract(source, signature)
        code += r'''
int main() {
  int fds[2]; assert(pipe(fds) == 0); g_adc_fd = fds[0];
  assert(fcntl(g_adc_fd, F_SETFL, O_NONBLOCK) == 0);
  assert(px4_arch_adc_update() == -EAGAIN && !g_sample_valid[0]);
  adc_msg_s records[2]{}; records[0].am_channel = 0; records[0].am_data = 1234;
  records[1].am_channel = 7; records[1].am_data = 4095;
  assert(write(fds[1], records, sizeof(records)) == sizeof(records));
  assert(px4_arch_adc_update() == 2 && g_samples[0].am_data == 1234 && g_samples[7].am_data == 4095);
  assert(px4_arch_adc_update() == -EAGAIN && g_sample_valid[0] && g_sample_valid[7]);
  records[0].am_data = 567; assert(write(fds[1], records, sizeof(records[0])) == sizeof(records[0]));
  assert(px4_arch_adc_update() == 1 && g_samples[0].am_data == 567 && !g_sample_valid[1]);
  assert(write(fds[1], "x", 1) == 1); assert(px4_arch_adc_update() == -EIO && !g_sample_valid[0]);
  close(g_adc_fd); assert(px4_arch_adc_update() == -EBADF && !g_sample_valid[7]); g_adc_fd = -1;
  close(fds[1]); px4_arch_adc_uninit(0);
  assert(px4_arch_adc_update() == -ENODEV && px4_arch_adc_temp_sensor_mask() == 0);
}
'''
        run(code, cpp=True)

    def test_feedback_and_fault_frames_are_retained_once_under_backlog(self):
        code = cr8_1_transport_harness()
        code += r'''
int main() {
  SharedMemTransport transport("/dev/ipcc3"); assert(transport.init(true));
  PWMFeedback_t pwm{}; FaultStatus_t fault{};
  enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 1);
  enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, 2);
  assert(transport.receive_pwm_feedback(pwm) && pwm.header.sequence == 2);
  assert(transport.receive_fault_status(fault) && fault.header.sequence == 1);
  assert(!transport.receive_fault_status(fault) && !transport.receive_pwm_feedback(pwm));
  enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, 3);
  enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 4);
  assert(transport.receive_fault_status(fault) && fault.header.sequence == 4);
  assert(transport.receive_pwm_feedback(pwm) && pwm.header.sequence == 3);
  for (unsigned i = 0; i < 40; ++i) enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, i);
  assert(!transport.receive_pwm_feedback(pwm) && entries.size() == 24);
  for (unsigned i = 0; i < 40; ++i) {
    assert(transport.receive_fault_status(fault) && fault.header.sequence == i);
  }
  assert(!transport.receive_fault_status(fault) && entries.empty());
  enqueue<FaultStatus_t>(MSG_TYPE_FAULT_STATUS, 1, true);
  enqueue<PWMFeedback_t>(MSG_TYPE_PWM_FEEDBACK, 5);
  assert(transport.receive_pwm_feedback(pwm) && pwm.header.sequence == 5);
  assert(!transport.receive_fault_status(fault));
}
'''
        run(code, cpp=True)


    def test_actuator_natural_units_arming_and_rc_bounds(self):
        source = (ROOT / 'boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp').read_text()
        code = PRE + '#include <cmath>\n'
        pwm = (ROOT / 'src/drivers/drv_pwm_output.h').read_text()
        for name in ('PWM_LOWEST_MIN', 'PWM_HIGHEST_MAX'):
            code += re.search(rf'^#define {name} \d+$', pwm, re.M).group(0) + '\n'
        code += 'namespace math { template<typename T> constexpr T constrain(T v, T lo, T hi) '
        code += '{ return v < lo ? lo : (v > hi ? hi : v); } }\n'
        code += header(ROOT / 'boards/renesas/rdk-rzv2h/px4io_cr8_0/protocol.h').replace('#pragma once', '')
        with tempfile.TemporaryDirectory(prefix='rzv2h-uorb-headers-') as directory:
            files = ['ActuatorOutputs.msg', 'ActuatorArmed.msg', 'versioned/VehicleStatus.msg', 'InputRc.msg']
            subprocess.run(['python3', str(ROOT / 'Tools/msg/px_generate_uorb_topic_files.py'),
                            '--headers', '-f', *(str(ROOT / 'msg' / f) for f in files),
                            '-i', str(ROOT / 'msg'), '-e', str(ROOT / 'Tools/msg/templates/uorb'),
                            '-o', directory], check=True)
            code += '#define __EXPORT\n#define ORB_DECLARE(...)\nstruct orb_metadata;\n'
            for name in ('actuator_outputs', 'actuator_armed', 'vehicle_status', 'input_rc'):
                code += header(Path(directory) / (name + '.h')).replace('#pragma once', '')
        code += r'''
template<typename T> struct SubscriptionBoundary {
  T value{}; bool ready{};
  bool update(T *destination) { if (!ready) return false; *destination = value; ready = false; return true; }
};
struct PublicationBoundary {
  input_rc_s value{}; unsigned count{};
  void publish(const input_rc_s &message) { value = message; ++count; }
};
static uint64_t now_us = 123;
static uint64_t hrt_absolute_time() { return now_us; }
class UorbBridgeCR8 {
public:
''' + re.search(r'\n(\tstatic constexpr uint64_t DISARMED_REFRESH_US = [^;]+;)',
                (ROOT / 'boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.h').read_text()).group(1) + r'''
  uint64_t _last_actuator_tx_us{0};
  bool _actuator_cmd_armed{false};
  actuator_outputs_s _actuator_outputs{};
  actuator_armed_s _actuator_armed{};
  vehicle_status_s _safety_status{};
  SubscriptionBoundary<actuator_outputs_s> _actuator_outputs_sub;
  SubscriptionBoundary<actuator_armed_s> _actuator_armed_sub;
  SubscriptionBoundary<vehicle_status_s> _safety_status_sub;
  PublicationBoundary _input_rc_pub;
  uint16_t _seq_actuator{}, _expected_seq_rc{};
  struct { unsigned tx_actuator_count{}, sequence_gaps{}, rx_rc_count{}; } _stats;
  ActuatorCommand_t sent{};
  bool send_msg(MessageType_e type, uint16_t &sequence, void *message, size_t size) {
    assert(type == MSG_TYPE_ACTUATOR_CMD && size == sizeof(sent));
    memcpy(&sent, message, size); ++sequence; return true;
  }
  void process_actuator_outputs();
  void publish_input_rc(const InputRC_t &message);
};
'''
        code += extract(source, 'void UorbBridgeCR8::process_actuator_outputs(')
        code += extract(source, 'void UorbBridgeCR8::publish_input_rc(') + r'''
int main() {
  UorbBridgeCR8 bridge;
  auto &out = bridge._actuator_outputs_sub; auto &arm = bridge._actuator_armed_sub;
  auto &safety = bridge._safety_status_sub;
  out.value.noutputs = 2; out.value.output[0] = 1500; out.value.output[1] = 2000;
  out.value.output[2] = 1500; out.ready = true;
  bridge.process_actuator_outputs();
  assert(bridge.sent.outputs[0] == 1500 && bridge.sent.outputs[1] == 2000);
  assert(!bridge.sent.outputs[2] && !bridge.sent.armed && !bridge.sent.safety_off);
  arm.value.armed = true; arm.ready = true;
  bridge.process_actuator_outputs(); assert(!bridge.sent.armed);
  safety.value.safety_off = true; safety.ready = true;
  bridge.process_actuator_outputs(); assert(bridge.sent.armed && bridge.sent.safety_off);
  arm.value.manual_lockdown = true; arm.ready = true;
  bridge.process_actuator_outputs(); assert(!bridge.sent.armed && bridge.sent.outputs[0] == 1500);
  arm.value.manual_lockdown = false; arm.value.armed = false; arm.value.force_failsafe = true; arm.ready = true;
  safety.value.safety_off = false; safety.ready = true;
  bridge.process_actuator_outputs(); assert(bridge.sent.armed && bridge.sent.outputs[1] == 2000);
  arm.value.lockdown = true; arm.ready = true;
  bridge.process_actuator_outputs(); assert(!bridge.sent.armed);
  arm.value.lockdown = false; arm.value.force_failsafe = false; arm.value.armed = true; arm.ready = true;
  safety.value.safety_off = true; safety.ready = true;
  // Valid PX4 PWM parameter values pass unchanged; others are bounded per channel.
  const float input[] = {800, 2200, 949.6f, 0, 0.4f, NAN, INFINITY, -1, 48, 2600, 65536, 1e30f};
  const uint16_t expect[] = {800, 2200, 950, 0, 0, 0, 0, 0, PWM_LOWEST_MIN, PWM_HIGHEST_MAX, PWM_HIGHEST_MAX,
                             PWM_HIGHEST_MAX};
  for (unsigned n = 0; n < sizeof(input) / sizeof(input[0]); ++n) {
    out.value.output[0] = input[n]; out.ready = true;
    bridge.process_actuator_outputs();
    assert(bridge.sent.outputs[0] == expect[n] && bridge.sent.outputs[1] == 2000 && bridge.sent.armed);
  }
  for (float &value : out.value.output) value = 1500;
  for (unsigned count : {8u, 9u, 16u, 17u}) {
    out.value.noutputs = count; out.ready = true;
    bridge.process_actuator_outputs();
    const bool valid = count <= actuator_outputs_s::NUM_ACTUATOR_OUTPUTS;
    assert(bridge.sent.armed == valid);
    for (unsigned i = 0; i < IPC_MAX_ACTUATORS; ++i) assert(bridge.sent.outputs[i] == (valid ? 1500 : 0));
  }
  // A quiet mixer: the disarmed command is resent within the lease, an armed
  // one never, so only fresh mixer output keeps an armed lease alive.
  static_assert(UorbBridgeCR8::DISARMED_REFRESH_US == 20000, "PX4IO 20 ms floor");
  out.value.noutputs = 2; out.ready = true; arm.value = {}; arm.ready = true;
  safety.value.safety_off = false; safety.ready = true;
  bridge.process_actuator_outputs();
  unsigned sends = bridge._stats.tx_actuator_count; const uint16_t sequence = bridge._seq_actuator;
  assert(!bridge.sent.armed && bridge.sent.outputs[0] == 1500);
  now_us += UorbBridgeCR8::DISARMED_REFRESH_US - 1; bridge.process_actuator_outputs();
  assert(bridge._stats.tx_actuator_count == sends);
  memset(&bridge.sent, 0, sizeof(bridge.sent));
  now_us += 1; bridge.process_actuator_outputs();
  assert(bridge._stats.tx_actuator_count == sends + 1 && bridge._seq_actuator == uint16_t(sequence + 1));
  assert(!bridge.sent.armed && bridge.sent.outputs[0] == 1500 && bridge.sent.outputs[1] == 1500);
  arm.value.armed = true; arm.ready = true; safety.value.safety_off = true; safety.ready = true;
  bridge.process_actuator_outputs(); assert(bridge.sent.armed);
  sends = bridge._stats.tx_actuator_count;
  for (int i = 0; i < 10; ++i) { now_us += UorbBridgeCR8::DISARMED_REFRESH_US; bridge.process_actuator_outputs(); }
  assert(bridge._stats.tx_actuator_count == sends);
  arm.value.armed = false; arm.ready = true; bridge.process_actuator_outputs();
  assert(!bridge.sent.armed && bridge._stats.tx_actuator_count == sends + 1);
  now_us += UorbBridgeCR8::DISARMED_REFRESH_US; bridge.process_actuator_outputs();
  assert(bridge._stats.tx_actuator_count == sends + 2);
  InputRC_t message{};
  for (unsigned count : {0u, 16u, 17u, 18u, 255u}) {
    unsigned before = bridge._input_rc_pub.count; message.channel_count = count;
    for (unsigned i = 0; i < 16; ++i) message.channels[i] = 1000 + i;
    bridge.publish_input_rc(message);
    assert(bridge._input_rc_pub.count == before + (count <= 16 ? 1 : 0));
    if (count == 16) assert(bridge._input_rc_pub.value.values[15] == 1015);
  }
}
'''
        code = '#include <initializer_list>\n' + code
        run(code, cpp=True)


    def test_mhu_attach_enables_through_the_core_irq_layer(self):
        source = (ARCH / 'rzv_mhu_core.c').read_text()
        for cm33 in (False, True):
            code = PRE + ('#define CONFIG_RZV2H_BUILD_CM33 1\n' if cm33 else '') + r'''
typedef int (*xcpt_t)(int, void *, void *);
static int attach_error, attached, enabled, disabled, detached;
static int irq_attach(int irq, xcpt_t handler, void *arg) { attached = irq; return attach_error; }
static void up_enable_irq(int irq) { enabled = irq; }
static void up_disable_irq(int irq) { disabled = irq; }
static void irq_detach(int irq) { detached = irq; }
'''
            # SPI routing lives in up_enable_irq(); the MHU never touches the GIC.
            self.assertNotIn('ICDIPTR', source)
            code += extract(source, 'int rzv_mhu_attach_isr(')
            code += extract(source, 'int rzv_mhu_detach_isr(') + r'''
static int handler(int irq, void *context, void *arg) { return 0; }
int main(void) {
  attach_error = -ENOMEM;
  assert(rzv_mhu_attach_isr(310, 0, handler, NULL) == -ENOMEM);
  assert(!enabled);
  attach_error = 0;
  assert(rzv_mhu_attach_isr(310, 0, handler, NULL) == 310 && attached == 310 && enabled == 310);
  assert(rzv_mhu_detach_isr(310) == 0 && disabled == 310 && detached == 310);
}
'''
            run(code)


if __name__ == '__main__':
    unittest.main()
