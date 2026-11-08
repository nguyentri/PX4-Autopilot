#!/usr/bin/env python3
"""Exercise production SCI-I2C transfer and ISR code through host boundaries."""
from pathlib import Path
import re
import importlib.util
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
ARCH = NUTTX / "arch/arm/src/rzv"


def function(source, signature):
    start = source.rindex(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end] + "\n"


def without_includes(source):
    return re.sub(r"^\s*#\s*include[^\n]*$", "", source, flags=re.M)


class SCITransactions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-sci-transactions-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        transfer_source = (ARCH / "rzv_sci_i2c.c").read_text()
        functions = "\n".join(function(transfer_source, signature) for signature in (
            "void sci_i2c_clear_pending(",
            "void sci_i2c_disable(",
            "static int sci_i2c_wait_idle(", "static void sci_i2c_clear_status(",
            "static int sci_i2c_quiesce(", "static uint32_t sci_i2c_timeout_ms(",
            "static int sci_i2c_transfer(",
            "uint32_t rzv2h_sci_i2c_sample_transfers_at(",
            "uint32_t rzv2h_sci_i2c_sample_transfers("))
        prelude = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
#include <stdlib.h>
#include <semaphore.h>
#include <pthread.h>
#include <stdatomic.h>
#define FAR
#define CODE
#define OK 0
#define irqstate_t unsigned
#define ARM_DSB() ((void)0)
#ifdef CONFIG_RZV2H_BUILD_CM33
#define RZV_IRQ_FIRST 16u
#else
#define RZV_IRQ_FIRST 32u
#endif
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
static uint32_t g_sample_transfers[10];
#define SCI_I2C_CHANNEL_COUNT 10u
#define SCI_I2C_DEFAULT_SCL_HZ 100000u
#define SCI_I2C_CESR_TIMEOUT 10000u
#define RZV_CLOCK_P5CLK 5u
#define SCI_I2C_PCLK_FALLBACK_HZ 100000000u
#define USEC_PER_MSEC 1000u
#define USEC_PER_TICK 10000u
#define i2cerr(...) ((void)0)
'''
        types = without_includes((NUTTX / "include/nuttx/i2c/i2c_master.h").read_text())
        types += without_includes((ARCH / "rzv_sci_i2c_internal.h").read_text())
        registers = without_includes((ARCH / "hardware/rzv_sci.h").read_text())
        for header in (ARCH / "hardware/rzv_intc_gic.h",
                       NUTTX / "arch/arm/include/rzv/rzv2h_irq.h",
                       NUTTX / "arch/arm/src/armv8-m/nvic.h"):
            registers += without_includes(header.read_text())
        boundary = r'''
static struct rzv_sci_i2c_priv_s priv;
static uint32_t regs[256], tdr[16384];
static uint32_t pending[16];
static unsigned mode, starts, stops, restarts, tdr_count, receive_count, polls;
static unsigned late_txi;
/* The TXI handler acknowledges its own GIC/NVIC pending bit once on entry,
 * even while the transfer keeps CCR0 enabled, and must never write
 * CFCLR.TDREC (with TE=1 that re-arms TDRE and raises a mid-frame TXI).
 */
static bool in_txi_isr, txi_entry_ack_due;
static atomic_int active, maximum;
static bool condition_pending;
#ifdef CONFIG_RZV2H_BUILD_CM33
#define PENDING_BASE NVIC_IRQ_CLRPEND(0)
#define PENDING_INPUT(irq) ((irq) - RZV_IRQ_FIRST)
#else
#define PENDING_BASE RZV_INTC_GIC_GICD_ICDICPR(0)
#define PENDING_INPUT(irq) (irq)
#endif
static unsigned txi_input(void) {return PENDING_INPUT(RZV_IRQ_SCI_TXI(priv.channel));}
static void queue_stale_txi(void) {unsigned bit = txi_input(); pending[bit / 32] |= 1u << (bit % 32);}
static void assert_no_pending_txi(void) {unsigned bit = txi_input(); assert(!(pending[bit / 32] & (1u << (bit % 32))));}
static void up_udelay(unsigned delay) {(void)delay;}
static uint32_t rzv_clock_get_rate(unsigned id) {assert(id == RZV_CLOCK_P5CLK); return 100000000u;}
static void *kmm_malloc(size_t size) { return mode == 4 ? NULL : malloc(size); }
static void kmm_free(void *pointer) { free(pointer); }
static int nxsem_post(sem_t *sem) {
    if (sem == &priv.sem_excl) assert(atomic_fetch_sub(&active, 1) == 1);
    return sem_post(sem) == 0 ? 0 : -errno;
}
static int nxsem_wait_uninterruptible(sem_t *sem) {
    assert(sem == &priv.sem_excl);
    int ret;
    do { ret = sem_wait(sem); } while (ret && errno == EINTR);
    if (ret) return -errno;
    assert(atomic_fetch_add(&active, 1) == 0);
    atomic_store(&maximum, 1);
    return 0;
}
static int nxsem_reset(sem_t *sem, int value) {
    assert(sem == &priv.sem_isr && value == 0);
    while (sem_trywait(sem) == 0) {}
    return 0;
}
static irqstate_t enter_critical_section(void) { return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; }
static uint8_t getreg8(uintptr_t address) {
    assert(atomic_load(&active) == 1);
    assert(address == RZV_SCI_CESR_OFFSET);
    ++polls;
    if (mode == 2 && regs[RZV_SCI_CCR0_OFFSET / 4]) return 0;
    return regs[RZV_SCI_CCR0_OFFSET / 4] ? SCI_CESR_TIST | SCI_CESR_RIST : 0;
}
static uint32_t getreg32(uintptr_t address) {
    assert(atomic_load(&active) == 1);
    if (address == RZV_SCI_RDR_OFFSET) return 0x11 + receive_count++;
    return regs[address / 4];
}
static void txi_event(void) {
    assert(!in_txi_isr);
    in_txi_isr = txi_entry_ack_due = true;
    sci_i2c_txi_isr(0, NULL, &priv);
    assert(!txi_entry_ack_due); /* every TXI acknowledges its pending bit */
    in_txi_isr = false;
}
static void inject_late_txi(void) {
    unsigned saved_tdr = tdr_count, saved_rx = receive_count;
    uint32_t saved_byte = priv.byte_idx;
    enum sci_i2c_state_e saved_state = priv.state;
    txi_event();
    ++late_txi;
    assert(tdr_count == saved_tdr && receive_count == saved_rx);
    assert(priv.byte_idx == saved_byte && priv.state == saved_state);
}
static void putreg32(uint32_t value, uintptr_t address) {
    assert(atomic_load(&active) == 1);
    if (address >= PENDING_BASE && address < PENDING_BASE + sizeof(pending)) {
        unsigned txi = txi_input(), tei = PENDING_INPUT(RZV_IRQ_SCI_TEI(priv.channel));
        assert((address == PENDING_BASE + 4u * (txi / 32) && value == (1u << (txi % 32))) ||
               (address == PENDING_BASE + 4u * (tei / 32) && value == (1u << (tei % 32))));
        bool txi_entry_ack = txi_entry_ack_due &&
                             address == PENDING_BASE + 4u * (txi / 32) && value == (1u << (txi % 32));
        txi_entry_ack_due = false;
        assert(txi_entry_ack || regs[RZV_SCI_CCR0_OFFSET / 4] == 0 ||
               priv.state == SCI_I2C_STATE_START_PENDING ||
               priv.state == SCI_I2C_STATE_RESTART_PENDING);
        pending[(address - PENDING_BASE) / 4] &= ~value;
        return;
    }
    if (in_txi_isr && address == RZV_SCI_CFCLR_OFFSET) assert(!(value & SCI_CFCLR_TDREC));
    if (address == RZV_SCI_ICR_OFFSET) {
        if (value & (SCI_ICR_IICSTAREQ | SCI_ICR_IICSTPREQ | SCI_ICR_IICRSTAREQ)) condition_pending = true;
        if (value & SCI_ICR_IICSTAREQ) ++starts;
        if (value & SCI_ICR_IICSTPREQ) ++stops;
        if (value & SCI_ICR_IICRSTAREQ) ++restarts;
        value &= ~(SCI_ICR_IICSTAREQ | SCI_ICR_IICSTPREQ | SCI_ICR_IICRSTAREQ);
    }
    if (address == RZV_SCI_TDR_OFFSET) { assert(tdr_count < 16384); tdr[tdr_count++] = value & 0xff; }
    if (address == RZV_SCI_ICFCLR_OFFSET) { regs[RZV_SCI_ISR_OFFSET / 4] &= ~SCI_ISR_IICSTIF; condition_pending = false; }
    regs[address / 4] = value;
    if (mode >= 5 && mode <= 7 && address == RZV_SCI_CCR0_OFFSET &&
        (value & SCI_CCR0_TIE)) {assert_no_pending_txi(); inject_late_txi();}
}
static void putreg8(uint8_t value, uintptr_t address) {
    assert(address == RZV_SCI_CCR0_OFFSET + 2);
    putreg32((regs[RZV_SCI_CCR0_OFFSET / 4] & ~(0xffu << 16)) | ((uint32_t)value << 16), RZV_SCI_CCR0_OFFSET);
}
static int sci_i2c_hw_init(struct rzv_sci_i2c_priv_s *value, uint32_t frequency) {
    (void)value; (void)frequency;
    assert(false); /* This fixture keeps the already configured clock. */
    return -ENOTSUP;
}
static int nxsem_tickwait_uninterruptible(sem_t *sem, uint32_t ticks) {
    assert(sem == &priv.sem_isr && ticks > 0 && ticks <= INT32_MAX);
    if (mode == 1) return -ETIMEDOUT;
    if (mode >= 5 && mode <= 7) {inject_late_txi(); queue_stale_txi();}
    regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICSTIF;
    sci_i2c_tei_isr(0, NULL, &priv);
    if (mode >= 5 && mode <= 7) assert_no_pending_txi();
    for (unsigned count = 0; count < 10000; ++count) {
        if (sem_trywait(sem) == 0) return 0;
        if (condition_pending || priv.state == SCI_I2C_STATE_STOP || priv.state == SCI_I2C_STATE_RESTART_PENDING) {
            bool starting = priv.state != SCI_I2C_STATE_STOP;
            if (mode >= 5 && mode <= 7 && condition_pending) {
                inject_late_txi();
                if (starting) queue_stale_txi();
            }
            regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICSTIF;
            sci_i2c_tei_isr(0, NULL, &priv);
            if (mode >= 5 && mode <= 7 && starting) assert_no_pending_txi();
        } else {
            regs[RZV_SCI_ISR_OFFSET / 4] = mode == 3 ? SCI_ISR_IICACKR : 0;
            txi_event();
        }
    }
    assert(false); return -ETIMEDOUT;
}
'''
        main = r'''
static void *client(void *unused) {
    (void)unused;
    uint8_t payload = 0x20;
    struct i2c_msg_s msg = {.frequency = 100000, .addr = 0x10, .buffer = &payload, .length = 1};
    assert(sci_i2c_transfer(&priv.dev, &msg, 1) == 0);
    return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2);
    for (unsigned i=0; i<16; ++i) pending[i] = UINT32_MAX;
    sem_init(&priv.sem_excl, 0, 1); sem_init(&priv.sem_isr, 0, 0);
    priv.cur_scl_hz = priv.actual_scl_hz = 100000;
    uint8_t command = 0x40, data[3] = {};
    struct i2c_msg_s messages[2] = {
        {.frequency = 100000, .addr = 0x10, .buffer = &command, .length = 1},
        {.frequency = 100000, .addr = 0x10, .flags = I2C_M_READ, .buffer = data, .length = 3}
    };
    if (!strcmp(argv[1], "invalid")) {
        assert(sci_i2c_transfer(NULL, messages, 1) == -EINVAL);
        assert(sci_i2c_transfer(&priv.dev, NULL, 1) == -EINVAL);
        assert(sci_i2c_transfer(&priv.dev, messages, 0) == -EINVAL);
        messages[0].length = -1;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == -EINVAL);
        messages[0].length = 1; messages[0].addr = 0x80;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == -EINVAL);
        messages[0].addr = 0x10; messages[0].flags = I2C_M_NOSTOP;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == -ENOTSUP);
        messages[1].frequency = 400000;
        assert(sci_i2c_transfer(&priv.dev, messages, 2) == -ENOTSUP);
        messages[0].flags = 0; messages[1].frequency = 100000;
        /* A read phase with no bytes cannot NACK its last byte: rejected,
         * alone or with only empty NOSTART continuations. */
        messages[1].length = 0;
        assert(sci_i2c_transfer(&priv.dev, messages, 2) == -EINVAL);
        struct i2c_msg_s empty_read[2] = {
            {.frequency = 100000, .addr = 0x10, .flags = I2C_M_READ, .buffer = data, .length = 0},
            {.frequency = 100000, .addr = 0x10, .flags = I2C_M_READ | I2C_M_NOSTART, .buffer = data, .length = 0}
        };
        assert(sci_i2c_transfer(&priv.dev, empty_read, 2) == -EINVAL);
        assert(!atomic_load(&maximum) && !starts);
        /* A zero-length write probe and an empty read head with a non-empty
         * NOSTART continuation stay valid. */
        messages[0].length = 0;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
        empty_read[1].length = 3;
        assert(sci_i2c_transfer(&priv.dev, empty_read, 2) == 0);
    } else if (!strcmp(argv[1], "allocation")) {
        mode = 4;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == -ENOMEM);
        assert(starts == 0 && priv.metadata == NULL && !atomic_load(&active));
        mode = 0;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
    } else if (!strcmp(argv[1], "empty-continuations")) {
        struct i2c_msg_s *chain = calloc(4096, sizeof(*chain));
        assert(chain);
        chain[0] = messages[0];
        for (unsigned i = 1; i < 4096; ++i) {
            chain[i].frequency = 100000; chain[i].addr = 0x10;
            chain[i].flags = I2C_M_NOSTART;
        }
        assert(sci_i2c_transfer(&priv.dev, chain, 4096) == 0);
        assert(starts == 1 && stops == 1 && tdr_count == 2);
        assert(priv.metadata == NULL);
        free(chain);
    } else if (!strcmp(argv[1], "read-continuations")) {
        struct i2c_msg_s *chain = calloc(1024, sizeof(*chain));
        uint8_t *bytes = calloc(1024, 1);
        assert(chain && bytes);
        for (unsigned i = 0; i < 1024; ++i) {
            chain[i].frequency = 100000; chain[i].addr = 0x10;
            chain[i].flags = I2C_M_READ | (i ? I2C_M_NOSTART : 0);
            chain[i].buffer = &bytes[i]; chain[i].length = 1;
        }
        assert(sci_i2c_transfer(&priv.dev, chain, 1024) == 0);
        assert(starts == 1 && stops == 1 && receive_count == 1024);
        for (unsigned i = 0; i < 1024; ++i) assert(bytes[i] == (uint8_t)(0x11 + i));
        assert(priv.metadata == NULL);
        free(bytes); free(chain);
    } else if (!strcmp(argv[1], "pending-start-write") ||
               !strcmp(argv[1], "pending-start-read") ||
               !strcmp(argv[1], "pending-stop-start")) {
        uint8_t bytes[] = {0x5a, 0xa5, 0x3c};
        messages[0].buffer = bytes; messages[0].length = 3;
        mode = !strcmp(argv[1], "pending-start-write") ? 5 :
               (!strcmp(argv[1], "pending-start-read") ? 6 : 7);
        if (mode == 6) messages[0].flags = I2C_M_READ;
        assert(sci_i2c_transfer(&priv.dev, messages, mode == 7 ? 2 : 1) == 0);
        assert(late_txi >= 2 && starts == (mode == 7 ? 2u : 1u));
        assert(stops == starts && tdr[0] == (mode == 6 ? 0x21u : 0x20u));
        if (mode == 6) {
            assert(tdr_count == 4 && receive_count == 3);
            for (unsigned i=0; i<3; ++i) assert(bytes[i] == 0x11u + i);
        } else {
            assert(tdr[1] == 0x5a && tdr[2] == 0xa5 && tdr[3] == 0x3c);
            assert(tdr_count == (mode == 7 ? 8u : 4u));
            if (mode == 7) {
                assert(tdr[4] == 0x21);
                for (unsigned i=0; i<3; ++i) assert(data[i] == 0x11u + i);
            }
        }
    } else if (!strcmp(argv[1], "parallel")) {
        pthread_t clients[3];
        for (unsigned i=0; i<3; ++i) assert(pthread_create(&clients[i], NULL, client, NULL) == 0);
        for (unsigned i=0; i<3; ++i) assert(pthread_join(clients[i], NULL) == 0);
        assert(starts == 3 && stops == 3 && atomic_load(&maximum) == 1);
    } else if (!strcmp(argv[1], "telemetry")) {
        priv.channel = 7;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
        priv.channel = 0;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
        assert(rzv2h_sci_i2c_sample_transfers_at(7) == 1);
        assert(rzv2h_sci_i2c_sample_transfers_at(0) == 2);
        assert(rzv2h_sci_i2c_sample_transfers_at(4) == 0);
        assert(rzv2h_sci_i2c_sample_transfers_at(10) == 0);
        assert(rzv2h_sci_i2c_sample_transfers() == 3);
    } else if (!strcmp(argv[1], "timeout") || !strcmp(argv[1], "enable-timeout") || !strcmp(argv[1], "nack")) {
        mode = !strcmp(argv[1], "timeout") ? 1 : (!strcmp(argv[1], "enable-timeout") ? 2 : 3);
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == (mode == 3 ? -ENXIO : -ETIMEDOUT));
        if (mode == 2) assert(polls >= SCI_I2C_CESR_TIMEOUT && starts == 0);
        assert(atomic_load(&active) == 0);
        assert(regs[RZV_SCI_CCR0_OFFSET / 4] == 0);
        mode = 0;
        assert(sci_i2c_transfer(&priv.dev, messages, 1) == 0);
    } else {
        if (!strcmp(argv[1], "repeated-start")) messages[0].flags = I2C_M_NOSTOP;
        assert(sci_i2c_transfer(&priv.dev, messages, 2) == 0);
        assert(data[0] == 0x11 && data[1] == 0x12 && data[2] == 0x13);
        assert(tdr[0] == 0x20 && tdr[1] == command && tdr[2] == 0x21);
        if (!strcmp(argv[1], "repeated-start")) assert(starts == 1 && restarts == 1 && stops == 1);
        else assert(starts == 2 && restarts == 0 && stops == 2);
    }
    int available;
    sem_getvalue(&priv.sem_excl, &available);
    assert(available == 1 && atomic_load(&active) == 0);
}
'''
        path = directory / "transactions.c"
        path.write_text(prelude + types + registers + boundary +
                        without_includes((ARCH / "rzv_sci_i2c_isr.c").read_text()) + functions + main)
        cls.binary = directory / "transactions"
        subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-Wno-sign-compare", "-pthread", str(path), "-o", str(cls.binary)], check=True)

    def case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonzero_channel_transfer_counters_are_independent(self): self.case("telemetry")
    def test_late_txi_before_start_completion_preserves_write_payload(self): self.case("pending-start-write")
    def test_late_txi_before_start_completion_preserves_read_address(self): self.case("pending-start-read")
    def test_late_txi_after_stop_before_next_start_preserves_message_order(self): self.case("pending-stop-start")

    def test_empty_continuations_need_no_recursive_isr_calls(self): self.case("empty-continuations")
    def test_long_read_segment_delivers_every_byte(self): self.case("read-continuations")
    def test_metadata_allocation_failure_allows_retry(self): self.case("allocation")

    def test_repeated_start_reads_all_bytes(self): self.case("repeated-start")
    def test_separate_messages_issue_separate_start_stop(self): self.case("separate-start")
    def test_address_nack_releases_bus_and_allows_retry(self): self.case("nack")
    def test_timeout_quiesces_bus_and_allows_retry(self): self.case("timeout")
    def test_enable_timeout_never_issues_start(self): self.case("enable-timeout")
    def test_invalid_requests_never_lock_or_touch_bus(self): self.case("invalid")
    def test_three_concurrent_clients_use_exclusive_bus(self): self.case("parallel")


SPEC = importlib.util.spec_from_file_location("sci_channel_boundaries", ROOT / "test/rzv2h_sci_spi_contract_test.py")
S = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S)


def initializer_harness():
    """Add the I2C stop boundary to the shared initializer fixture."""
    code = S.initializer_harness("i2c")
    if not re.search(r"static void(?: TEST_UNUSED)? up_udelay\(", code):
        code = code.replace("static const uint32_t expected_clocks[]", """
static void up_udelay(unsigned delay) {assert(delay > 0);}
static const uint32_t expected_clocks[]""")
    marker = "static irqstate_t enter_critical_section(void)"
    code = code.replace(marker, """
static void putreg8(uint8_t value, uintptr_t address) {
    assert((address & 3u) == 2u);
    uintptr_t word = address & ~(uintptr_t)3u;
    putreg32((getreg32(word) & ~(0xffu << 16)) | ((uint32_t)value << 16), word);
}
""" + marker, 1)
    source = (ARCH / "rzv_sci_i2c.c").read_text()
    marker = "static int sci_i2c_wait_idle("
    code = code.replace(marker, function(source, "void sci_i2c_disable(") + marker, 1)
    return code


class SCIInitialization(unittest.TestCase):
    def test_all_ten_real_initializers_roll_back_and_retry(self):
        for core in ((), ("-DCONFIG_RZV2H_BUILD_CM33=1",)):
            with self.subTest(core=core):
                S.compile_and_run(initializer_harness(), defines=core)

    def test_disabled_conflicted_and_unowned_channels_fail_before_side_effects(self):
        for variant in ("TEST_DISABLED", "TEST_CONFLICT", "TEST_UNOWNED"):
            with self.subTest(variant=variant):
                S.compile_and_run(initializer_harness(), defines=(f"-D{variant}=1",))

    def test_pinless_reset_rejects_before_quiesce_gpio_or_semaphore(self):
        source = (ARCH / "rzv_sci_i2c.c").read_text()
        code = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include <assert.h>
#define sem_t int
struct i2c_master_s {int unused;};
'''
        code += without_includes((ARCH / "rzv_sci_i2c_internal.h").read_text())
        code += r'''
static unsigned side_effects;
static int nxsem_wait_uninterruptible(int *sem) {(void)sem; ++side_effects; return 0;}
static int nxsem_post(int *sem) {(void)sem; ++side_effects; return 0;}
static int sci_i2c_quiesce(struct rzv_sci_i2c_priv_s *priv) {(void)priv; ++side_effects; return 0;}
static int sci_i2c_recover_bus(struct rzv_sci_i2c_priv_s *priv) {(void)priv; ++side_effects; return 0;}
'''
        code += function(source, "static int sci_i2c_reset(")
        code += r'''
int main(void) {
  struct rzv_sci_i2c_priv_s priv = {0};
  assert(sci_i2c_reset(NULL) == -ENOTSUP && !side_effects);
  assert(sci_i2c_reset(&priv.dev) == -ENOTSUP && !side_effects);
  priv.pins_configured = true;
  assert(sci_i2c_reset(&priv.dev) == -ENOTSUP && !side_effects);
  return 0;
}
'''
        S.compile_and_run(code)

    def test_legacy_sci0_and_sci7_pin_routes_are_retained(self):
        S.compile_and_run(initializer_harness(), defines=("-DTEST_ROUTE=1",))

    def test_all_ten_board_registrations_preserve_bus_allocation_and_retry(self):
        S.compile_and_run(S.board_harness("i2c", list(range(10))))

    def test_controller_without_character_device_allows_distinct_native_riic7(self):
        S.compile_and_run(S.board_harness("i2c", [7], register=False),
                          defines=("-DCONFIG_RZV_I2C7=1",))

    def test_sci7_only_compatibility_wrapper_reports_sci7(self):
        S.compile_and_run(S.board_harness("i2c", [7]))

    def test_riic7_collision_and_unowned_board_route_reject_before_side_effects(self):
        for channel, controlled, flags in (
            (7, True, ("-DTEST_REJECT=-EBUSY", "-DCONFIG_RZV_I2C7=1")),
            (4, False, ("-DTEST_REJECT=-ENOTSUP",)),
        ):
            with self.subTest(channel=channel):
                code = S.board_harness("i2c", [channel], controlled=controlled)
                code = code.replace("static const unsigned selected_channels[]", "static const unsigned TEST_UNUSED selected_channels[]")
                S.compile_and_run(code, defines=flags)


if __name__ == "__main__":
    unittest.main()
