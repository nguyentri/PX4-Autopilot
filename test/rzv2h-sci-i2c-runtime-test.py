#!/usr/bin/env python3
"""Exercise production SCI-I2C transfer and ISR code through host boundaries."""
from pathlib import Path
import re
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
            "static int sci_i2c_wait_idle(", "static void sci_i2c_clear_status(",
            "static int sci_i2c_quiesce(", "static uint32_t sci_i2c_timeout_ms(",
            "static int sci_i2c_transfer("))
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
#define SCI_I2C_DEFAULT_SCL_HZ 100000u
#define SCI_I2C_CESR_TIMEOUT 10000u
#define USEC_PER_MSEC 1000u
#define USEC_PER_TICK 10000u
#define i2cerr(...) ((void)0)
'''
        types = without_includes((NUTTX / "include/nuttx/i2c/i2c_master.h").read_text())
        types += without_includes((ARCH / "rzv_sci_i2c_internal.h").read_text())
        registers = without_includes((ARCH / "hardware/rzv_sci.h").read_text())
        boundary = r'''
static struct rzv_sci_i2c_priv_s priv;
static uint32_t regs[256], tdr[16384];
static unsigned mode, starts, stops, restarts, tdr_count, receive_count, polls;
static atomic_int active, maximum;
static bool condition_pending;
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
static void putreg32(uint32_t value, uintptr_t address) {
    assert(atomic_load(&active) == 1);
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
}
static int sci_i2c_hw_init(struct rzv_sci_i2c_priv_s *value, uint32_t frequency) {
    (void)value; (void)frequency;
    assert(false); /* This fixture keeps the already configured clock. */
    return -ENOTSUP;
}
static int nxsem_tickwait_uninterruptible(sem_t *sem, uint32_t ticks) {
    assert(sem == &priv.sem_isr && ticks > 0 && ticks <= INT32_MAX);
    if (mode == 1) return -ETIMEDOUT;
    regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICSTIF;
    sci_i2c_tei_isr(0, NULL, &priv);
    for (unsigned count = 0; count < 10000; ++count) {
        if (sem_trywait(sem) == 0) return 0;
        if (condition_pending || priv.state == SCI_I2C_STATE_STOP || priv.state == SCI_I2C_STATE_RESTART_PENDING) {
            regs[RZV_SCI_ISR_OFFSET / 4] = SCI_ISR_IICSTIF;
            sci_i2c_tei_isr(0, NULL, &priv);
        } else {
            regs[RZV_SCI_ISR_OFFSET / 4] = mode == 3 ? SCI_ISR_IICACKR : 0;
            sci_i2c_txi_isr(0, NULL, &priv);
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
        assert(!atomic_load(&maximum) && !starts);
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
    } else if (!strcmp(argv[1], "parallel")) {
        pthread_t clients[3];
        for (unsigned i=0; i<3; ++i) assert(pthread_create(&clients[i], NULL, client, NULL) == 0);
        for (unsigned i=0; i<3; ++i) assert(pthread_join(clients[i], NULL) == 0);
        assert(starts == 3 && stops == 3 && atomic_load(&maximum) == 1);
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


if __name__ == "__main__":
    unittest.main()
