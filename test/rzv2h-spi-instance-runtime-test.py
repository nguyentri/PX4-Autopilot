#!/usr/bin/env python3
"""Run the native SPI driver against traced host MMIO and OS boundaries.

The complete production driver and public register/SPI declarations are compiled
unchanged apart from removing target-only includes. The model is a host oracle,
not evidence of electrical operation or the common CPG implementation.
"""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
NUTTX = Path(os.environ.get("RZV_NUTTX_ROOT", ROOT / "platforms/nuttx/NuttX/nuttx"))
ARCH = NUTTX / "arch/arm/src/rzv"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h"
APPS = ROOT / "platforms/nuttx/NuttX/apps"


def without_includes(path):
    return re.sub(r"^\s*#\s*include[^\n]*$", "", path.read_text(), flags=re.M)


PRELUDE = r"""
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <semaphore.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define FAR
#define CODE
#define OK 0
#define UNUSED(x) ((void)(x))
#define DEBUGASSERT(x) assert(x)
#define weak_function __attribute__((weak))
#define aligned_data(n) __attribute__((aligned(n)))
#define ARM_DSB() ((void)0)
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
#define spiwarn(...) ((void)0)
#define CONFIG_SPI_EXCHANGE 1
#define CONFIG_SPI_HWFEATURES 1
#define CONFIG_SPI_BITORDER 1
#define CONFIG_SPI_CMDDATA 1
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
typedef unsigned irqstate_t;
typedef pthread_mutex_t mutex_t;
#define NXMUTEX_INITIALIZER PTHREAD_MUTEX_INITIALIZER
"""


BOUNDARY = r"""
static uint32_t registers[3][256];
static unsigned writes[3], reads[3], enables[3], disables[3], releases[3];
static unsigned reset_requests[3], helper_rollbacks[3];
static bool clocked[3], released[3];
static unsigned semaphores, locks, fault, dma_calls;
static unsigned critical_depth;
static bool internal_oracle;
static unsigned oracle_port, spdr_writes[3], bus_waits, bus_posts, selects;
static uint8_t transmitted[3][64];

static unsigned clock_port(uint32_t id) {
  assert((id >> 16) == 5 && (id & 0xffff) >= 4);
  unsigned bit = id & 0xffff;
  assert((bit - 4) % 3 == 0 && bit <= 10);
  return (bit - 4) / 3;
}
static unsigned address_port(uintptr_t address) {
  assert(address >= 0x12800000u && address < 0x12800c00u);
  assert((address & 3) == 0);
  unsigned port = (address - 0x12800000u) / 0x400u;
  assert(clocked[port] && released[port]);
  if (internal_oracle) assert(port == oracle_port);
  return port;
}
static uint32_t getreg32(uintptr_t address) {
  unsigned port = address_port(address), offset = address & 0x3ff;
  ++reads[port];
  if (internal_oracle && offset == RZV_SPI_SPSR_OFFSET && fault == 7) return 0;
  if (offset == RZV_SPI_SPSR_OFFSET && fault == 5) return SPI_SPSR_OVRF;
  if (offset == RZV_SPI_SPSR_OFFSET)
    return SPI_SPSR_SPTEF | SPI_SPSR_SPRF | SPI_SPSR_CENDF;
  if (offset == RZV_SPI_SPRFSR_OFFSET) return internal_oracle && fault == 8 ? 0 : 1;
  if (internal_oracle && offset == RZV_SPI_SPDR_OFFSET && fault == 6 && spdr_writes[port] >= 4)
    return registers[port][offset / 4] ^ 1u;
  return registers[port][offset / 4];
}
static void putreg32(uint32_t value, uintptr_t address) {
  unsigned port = address_port(address);
  ++writes[port];
  if (internal_oracle && (address & 0x3ff) == RZV_SPI_SPDR_OFFSET) {
    assert(registers[port][RZV_SPI_SPCR_OFFSET / 4] & SPI_SPCR_SPE);
    assert(registers[port][RZV_SPI_SPCR2_OFFSET / 4] & SPI_SPCR2_SPLP2);
    assert(!(registers[port][RZV_SPI_SPCR2_OFFSET / 4] & SPI_SPCR2_SPLP));
    assert((registers[port][RZV_SPI_SPCMD0_OFFSET / 4] & SPI_SPCMD_SPB_MASK) == SPI_SPCMD_SPB_8BIT);
    assert(spdr_writes[port] < 64);
    transmitted[port][spdr_writes[port]++] = (uint8_t)value;
  }
  registers[port][(address & 0x3ff) / 4] = value;
}
int rzv_clock_enable(uint32_t id) {
  unsigned port = clock_port(id);
  assert(!clocked[port]);
  ++enables[port];
  if (fault == 3) return -EIO;
  clocked[port] = true;
  return 0;
}
int rzv_clock_disable(uint32_t id) {
  unsigned port = clock_port(id);
  assert(clocked[port]);
  /* A reset-monitor failure must be unwound before its clock is gated. */
  if (fault == 4) assert(!released[port]);
  ++disables[port]; clocked[port] = false;
  return 0;
}
int rzv_module_unreset(uint32_t id) {
  unsigned port = clock_port(id);
  assert(clocked[port]);
  ++releases[port];
  /* The release request reaches hardware before the monitor can time out. */
  released[port] = true;
  if (fault == 4) {
    if (port == 2) {
      /* The dedicated SPI2 common helper already owns split-reset rollback. */
      released[port] = false; ++helper_rollbacks[port];
    }
    return -ETIMEDOUT;
  }
  return 0;
}
int rzv_module_reset(uint32_t id) {
  unsigned port = clock_port(id);
  assert(clocked[port]);
  ++reset_requests[port]; released[port] = false;
  return 0;
}
uint32_t rzv_clock_get_rate(enum rzv_clock_id_e clock) {
  assert(clock == RZV_CLOCK_P4CLK);
  return 200000000u;
}
static irqstate_t enter_critical_section(void) { return critical_depth++; }
static void leave_critical_section(irqstate_t flags) {
  assert(critical_depth > 0 && --critical_depth == flags);
}
static int nxmutex_lock(mutex_t *lock) {
  if (fault == 1) return -EINTR;
  assert(pthread_mutex_lock(lock) == 0); ++locks; return 0;
}
static int nxmutex_unlock(mutex_t *lock) {
  assert(locks > 0); --locks;
  assert(pthread_mutex_unlock(lock) == 0); return 0;
}
static int nxsem_init(sem_t *sem, int shared, unsigned count) {
  if (fault == 2) return -ENOMEM;
  assert(sem_init(sem, shared, count) == 0); ++semaphores; return 0;
}
static int nxsem_destroy(sem_t *sem) {
  assert(semaphores > 0 && sem_destroy(sem) == 0); --semaphores; return 0;
}
static int nxsem_wait_uninterruptible(sem_t *sem) {
  if (fault == 10) return -EINTR;
  assert(sem_wait(sem) == 0); ++bus_waits; return 0;
}
static int nxsem_post(sem_t *sem) { assert(sem_post(sem) == 0); ++bus_posts; return 0; }
#ifdef CONFIG_RZV_SPI0_DMA
int rzv_dmac_channel_configure(int channel, const struct rzv_dmac_config_s *config) {
  (void)channel; (void)config; ++dma_calls; assert(false); return -ENOTSUP;
}
int rzv_dmac_channel_start(int channel) {
  (void)channel; ++dma_calls; assert(false); return -ENOTSUP;
}
int rzv_dmac_channel_stop(int channel) {
  (void)channel; ++dma_calls; assert(false); return -ENOTSUP;
}
uint32_t rzv_dmac_channel_status(int channel) {
  (void)channel; ++dma_calls; assert(false); return 0;
}
void rzv_dmac_channel_dump(int channel, const char *label) {
  (void)channel; (void)label; ++dma_calls; assert(false);
}
#endif
"""


MAIN = r"""
int main(int argc, char **argv) {
  assert(argc == 2 || argc == 3);
  struct spi_dev_s *devices[3] = {NULL};
  struct spi_dev_s foreign = {NULL};
  assert(rzv_spi_get_channel(NULL) == -EINVAL);
  assert(rzv_spi_get_channel(&foreign) == -EINVAL);
  assert(rzv_spi_get_channel((struct spi_dev_s *)(uintptr_t)1) == -EINVAL);
  assert(rzv_spi_get_base(NULL) == 0 && rzv_spi_get_base(&foreign) == 0);
  assert(rzv_spi_get_base((struct spi_dev_s *)(uintptr_t)1) == 0);
  assert(rzv_spibus_initialize(-1) == NULL);
  assert(rzv_spibus_initialize(INT_MIN) == NULL);
  assert(rzv_spibus_initialize(3) == NULL);
  assert(rzv_spibus_initialize(INT_MAX) == NULL);
  for (int port = 0; port < 3; ++port) {
    if (!(TEST_MASK & (1 << port))) assert(rzv_spibus_initialize(port) == NULL);
    assert(!enables[port] && !writes[port] && !reads[port]);
  }
  assert(!locks && !semaphores);
  assert(rzv2h_spi_sample_transfers_at(-1) == 0);
  assert(rzv2h_spi_sample_transfers_at(3) == 0);
  for (int port = 0; port < 3; ++port)
    assert(rzv2h_spi_sample_transfers_at(port) == 0);

  if (strncmp(argv[1], "failure-", 8) == 0) {
    int port = argc == 3 ? atoi(argv[2]) : TEST_MASK == 7 ? 2 :
               TEST_MASK == 4 ? 2 : TEST_MASK == 2 ? 1 : 0;
    int sibling = (port + 1) % 3;
    if (TEST_MASK == 7) devices[sibling] = rzv_spibus_initialize(sibling);
    unsigned sibling_writes = writes[sibling], previous_sems = semaphores;
    fault = (unsigned)atoi(argv[1] + 8);
    assert(fault >= 1 && fault <= 4);
    assert(rzv_spibus_initialize(port) == NULL);
    assert(!clocked[port] && !writes[port] && !reads[port]);
    assert(!locks && semaphores == previous_sems);
    if (fault == 4) {
      assert(!released[port]);
      assert(reset_requests[port] == (port < 2 ? 1u : 0u));
      assert(helper_rollbacks[port] == (port == 2 ? 1u : 0u));
    }
    if (TEST_MASK == 7) assert(clocked[sibling] && writes[sibling] == sibling_writes);
    fault = 0;
    devices[port] = rzv_spibus_initialize(port);
    assert(devices[port]);
    assert(enables[port] == (strstr(argv[1], "3") || strstr(argv[1], "4") ? 2u : 1u));
  } else {
    for (int port = 0; port < 3; ++port) {
      if (!(TEST_MASK & (1 << port))) continue;
      devices[port] = rzv_spibus_initialize(port);
      assert(devices[port] && "enabled native SPI controller must initialize");
      struct rzv_spi_priv_s *priv = (struct rzv_spi_priv_s *)devices[port];
      assert(priv->config->port == port);
      assert(priv->config->base == 0x12800000u + port * 0x400u);
      assert(priv->config->clk_id == (5u << 16 | (4u + 3u * port)));
      assert(priv->config->spi_clock == RZV_CLOCK_P4CLK);
      unsigned accessor_writes = writes[port], accessor_reads = reads[port];
      assert(rzv_spi_get_channel(devices[port]) == port);
      assert(rzv_spi_get_base(devices[port]) == 0x12800000u + port * 0x400u);
      assert(writes[port] == accessor_writes && reads[port] == accessor_reads);
      assert(priv->actual == 1000000 && priv->nbits == 8 && priv->mode == SPIDEV_MODE0);
      assert(registers[port][RZV_SPI_SPCR_OFFSET / 4] & SPI_SPCR_SPE);
      unsigned before_writes = writes[port], before_reads = reads[port];
      assert(rzv_spibus_initialize(port) == devices[port]);
      assert(writes[port] == before_writes && reads[port] == before_reads);
      assert(enables[port] == 1 && releases[port] == 1);
      for (int sibling = 0; sibling < port; ++sibling)
        if (devices[sibling]) assert(devices[port] != devices[sibling]);
#ifdef CONFIG_RZV_SPI0_DMA
      if (port == 0) continue;
      assert(priv->config->dma_tx_channel == -1 && priv->config->dma_rx_channel == -1);
      assert(priv->config->dma_txbuf == NULL && priv->config->dma_rxbuf == NULL);
#endif
      assert(devices[port]->ops->lock(devices[port], true) == 0);
      assert(devices[port]->ops->send(devices[port], 0xa55a) == 0x5a);
      uint8_t tx[] = {0x12, 0xa5, 0xfe}, rx[3] = {0};
      devices[port]->ops->exchange(devices[port], tx, rx, sizeof(tx));
      assert(!memcmp(tx, rx, sizeof(tx)));
      assert(rzv2h_spi_sample_transfers_at(port) == 4);
      assert(devices[port]->ops->lock(devices[port], false) == 0);
      devices[port]->ops->setbits(devices[port], 16);
      assert(devices[port]->ops->send(devices[port], 0x1a55a) == 0xa55a);
      devices[port]->ops->setbits(devices[port], 32);
      assert(devices[port]->ops->send(devices[port], 0x1234a55a) == 0x1234a55a);
      assert(rzv2h_spi_sample_transfers_at(port) == 6);
      fault = 5;
      assert(devices[port]->ops->send(devices[port], 0x12) == UINT32_MAX);
      assert(rzv2h_spi_sample_transfers_at(port) == 6);
      fault = 0;
      rzv_spi_set_loopback(devices[port], true);
      assert(registers[port][RZV_SPI_SPCR2_OFFSET / 4] & SPI_SPCR2_SPLP2);
      rzv_spi_set_loopback(devices[port], false);
      assert(!(registers[port][RZV_SPI_SPCR2_OFFSET / 4] & (SPI_SPCR2_SPLP | SPI_SPCR2_SPLP2)));
      devices[port]->ops->setmode(devices[port], SPIDEV_MODE3);
      assert(devices[port]->ops->setfrequency(devices[port], 500000) == 500000);
    }
    assert(dma_calls == 0);
  }
  for (int port = 2; port >= 0; --port) {
    if (!devices[port]) continue;
    assert(rzv_spibus_uninitialize(devices[port]) == 0);
    assert(rzv_spi_get_channel(devices[port]) == -ENODEV);
    assert(rzv_spi_get_base(devices[port]) == 0);
    unsigned before = writes[port];
    assert(rzv_spibus_uninitialize(devices[port]) == -EINVAL && writes[port] == before);
    for (int sibling = 0; sibling < port; ++sibling)
      if (devices[sibling]) assert(clocked[sibling]);
    assert(rzv_spibus_initialize(port) == devices[port]);
    struct rzv_spi_priv_s *priv = (struct rzv_spi_priv_s *)devices[port];
    assert(priv->nbits == 8 && priv->actual == 1000000 && priv->mode == SPIDEV_MODE0);
    assert(rzv_spibus_uninitialize(devices[port]) == 0);
  }
  assert(rzv_spibus_uninitialize(NULL) == -EINVAL);
  assert(!locks && !semaphores && !critical_depth && !selects);
  assert(rzv2h_spi_sample_transfers() == rzv2h_spi_sample_transfers_at(0));
  for (int port = 0; port < 3; ++port) assert(!clocked[port]);
  return 0;
}
"""


def compile_run(source, arguments, extra_sources=()):
    with tempfile.TemporaryDirectory(prefix="rzv2h-spi-instances-") as temporary:
        directory = Path(temporary)
        path, binary = directory / "test.c", directory / "test"
        path.write_text(source)
        other_paths = []
        for index, extra in enumerate(extra_sources):
            other_path = directory / f"extra-{index}.c"
            other_path.write_text(extra)
            other_paths.append(str(other_path))
        result = subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-function", "-pthread", str(path), *other_paths,
             "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        result = subprocess.run([str(binary), *arguments], capture_output=True,
                                text=True, check=False, timeout=20)
        if result.returncode:
            raise AssertionError(f"exit={result.returncode}\n{result.stderr}")


def configuration(mask, dma=False):
    config = f"#define TEST_MASK {mask}\n#define CONFIG_RZV_SPI 1\n" + "".join(
        f"#define CONFIG_RZV_SPI{port} 1\n"
        for port in range(3) if mask & (1 << port)
    )
    if dma:
        config += """#define CONFIG_RZV_SPI0_DMA 1
#define CONFIG_RZV_DMAC_SPI0_TX_CHANNEL 48
#define CONFIG_RZV_DMAC_SPI0_RX_CHANNEL 49
"""
    return config


def driver_source(mask, dma=False, sample=True, controlled=False):
    prelude = PRELUDE + ("" if sample else "#undef CONFIG_RZV2H_SAMPLE_TEST_API\n")
    if controlled:
        prelude += "#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1\n"
    return (prelude + configuration(mask, dma) +
            without_includes(NUTTX / "include/nuttx/spi/spi.h") +
            without_includes(ARCH / "rzv_clock.h") +
            without_includes(ARCH / "hardware/rzv_spi.h") +
            without_includes(ARCH / "hardware/rzv_dmac.h") +
            without_includes(ARCH / "rzv_dmac.h") +
            without_includes(ARCH / "rzv_spi.h") + BOUNDARY +
            without_includes(ARCH / "rzv_spi.c"))


SAMPLE_LOOPBACK_MAIN = r"""
static void reject_select(struct spi_dev_s *dev, uint32_t devid, bool selected) {
  (void)dev; (void)devid; (void)selected; ++selects; assert(false);
}
int main(int argc, char **argv) {
  assert(argc == 2);
  unsigned injected = (unsigned)atoi(argv[1]);
  struct spi_dev_s *devices[3] = {NULL};
  struct spi_ops_s ops[3];
  assert(rzv2h_spi_sample_loopback_at(-1) == -EINVAL);
  assert(rzv2h_spi_sample_loopback_at(3) == -EINVAL);
  assert(rzv2h_spi_sample_loopback_at(INT_MAX) == -EINVAL);
  for (int port = 0; port < 3; ++port) {
    assert(rzv2h_spi_sample_loopback_at(port) == -ENODEV);
    assert(!reads[port] && !writes[port] && !enables[port]);
    if (TEST_MASK & (1 << port)) {
      devices[port] = rzv_spibus_initialize(port); assert(devices[port]);
      ops[port] = *devices[port]->ops; ops[port].select = reject_select;
      devices[port]->ops = &ops[port];
    }
  }
  for (int port = 0; port < 3; ++port) {
    if (!(TEST_MASK & (1 << port))) {
      assert(rzv2h_spi_sample_loopback_at(port) == -ENODEV);
      assert(!reads[port] && !writes[port]); continue;
    }
    struct rzv_spi_priv_s *priv = (struct rzv_spi_priv_s *)devices[port];
    uint32_t saved_spcr = SPI_SPCR_MSTR | SPI_SPCR_BPEN | SPI_SPCR_SCKASE | SPI_SPCR_SPPE;
    if (injected != 11) saved_spcr |= SPI_SPCR_SPE;
    uint32_t saved_spcr2 = SPI_SPCR2_SPLP | SPI_SPCR2_MOIFE | SPI_SPCR2_RMFM(7);
    uint32_t saved_cmd = SPI_SPCMD_SPB_VAL(SPI_SPB_32_BITS) | SPI_SPCMD_LSBF |
      SPI_SPCMD_CPOL | SPI_SPCMD_CPHA | SPI_SPCMD_SSLA(2) | SPI_SPCMD_SSLKP |
      SPI_SPCMD_BRDV(3) | SPI_SPCMD_SLNDEN;
    registers[port][RZV_SPI_SPCR_OFFSET / 4] = saved_spcr;
    registers[port][RZV_SPI_SPCR2_OFFSET / 4] = saved_spcr2;
    registers[port][RZV_SPI_SPCMD0_OFFSET / 4] = saved_cmd;
    priv->nbits = 32; priv->mode = SPIDEV_MODE3;
    uint32_t other_regs[3][256]; memcpy(other_regs, registers, sizeof(registers));
    unsigned before_reads = reads[port], before_writes = writes[port];
    unsigned waits_before = bus_waits, posts_before = bus_posts;
    internal_oracle = true; oracle_port = port; fault = injected;
    int result = rzv2h_spi_sample_loopback_at(port);
    internal_oracle = false; fault = 0;
    int expected = injected == 1 || injected == 10 ? -EINTR :
                   injected == 5 || injected == 6 || injected == 7 || injected == 8 ? -EIO : 0;
#ifndef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT
    expected = -EPERM;
#endif
#ifdef CONFIG_RZV_SPI0_DMA
    if (port == 0) expected = -ENOTSUP;
#endif
    assert(result == expected);
    assert(registers[port][RZV_SPI_SPCR_OFFSET / 4] == saved_spcr);
    assert(registers[port][RZV_SPI_SPCR2_OFFSET / 4] == saved_spcr2);
    assert(registers[port][RZV_SPI_SPCMD0_OFFSET / 4] == saved_cmd);
    assert(priv->nbits == 32 && priv->mode == SPIDEV_MODE3 && priv->frequency == 1000000);
    assert(!locks && !critical_depth && !selects && !dma_calls);
    for (int sibling = 0; sibling < 3; ++sibling)
      if (sibling != port) assert(!memcmp(registers[sibling], other_regs[sibling], sizeof(registers[0])));
    if (expected == -EPERM || expected == -ENOTSUP || expected == -EINTR) {
      assert(reads[port] == before_reads && writes[port] == before_writes);
      assert(bus_waits == waits_before && bus_posts == posts_before);
    } else {
      assert(bus_waits == waits_before + 1 && bus_posts == posts_before + 1);
      if (!result) {
        assert(spdr_writes[port] >= 8);
        bool differs = false;
        for (unsigned i = 1; i < spdr_writes[port]; ++i)
          differs |= transmitted[port][i] != transmitted[port][0];
        assert(differs);
      } else if (injected == 6) assert(spdr_writes[port] == 4);
      else if (injected == 8) assert(spdr_writes[port] == 1);
      else assert(spdr_writes[port] == 0);
    }
    int available;
    assert(sem_getvalue(&priv->exclsem, &available) == 0 && available == 1);
  }
  for (int port = 0; port < 3; ++port) {
    if (!devices[port]) continue;
    assert(rzv_spibus_uninitialize(devices[port]) == 0);
    unsigned before = reads[port] + writes[port];
    assert(rzv2h_spi_sample_loopback_at(port) == -ENODEV);
    assert(reads[port] + writes[port] == before);
  }
  assert(!semaphores && !locks && !selects && !dma_calls);
  return 0;
}
"""


BOARD_BOUNDARY = r"""
#define BOARD_SPI0_MOSI_GPIO 0x900u
#define BOARD_SPI0_MISO_GPIO 0x901u
#define BOARD_SPI0_SCK_GPIO 0x902u
#define BOARD_SPI0_SS0_GPIO 0x903u
#define syslog(...) ((void)0)
int rzv_gpioconfig(uint32_t pin);
void rzv_gpiowrite(uint32_t pin, bool high);
int spi_register(struct spi_dev_s *dev, int bus);
"""


BOARD_MAIN = r"""
static unsigned gpio_configs, gpio_writes, node_registrations;
static int registration_fault, gpio_fault;
int rzv_gpioconfig(uint32_t pin) {
  assert(pin >= 0x900 && pin <= 0x903); ++gpio_configs;
  return gpio_fault ? -EIO : 0;
}
void rzv_gpiowrite(uint32_t pin, bool high) {
  assert(pin == 0x903); (void)high; ++gpio_writes;
}
int spi_register(struct spi_dev_s *dev, int bus) {
  assert(dev && bus == 0); ++node_registrations; return registration_fault;
}
int board_spi_initialize(void);
int rzv2h_spi_sample_state_at(int port, struct rzv2h_bus_sample_state_s *out);
int rzv2h_spi_sample_state(struct rzv2h_bus_sample_state_s *out);
void rzv_spi_select(struct spi_dev_s *dev, uint32_t devid, bool selected);
uint8_t rzv_spi_status(struct spi_dev_s *dev, uint32_t devid);
int test_board_invalid_arguments(void);
int main(int argc, char **argv) {
  assert(argc == 2);
  UNUSED(argv);
  assert(dma_calls == 0 && selects == 0);
  struct rzv2h_bus_sample_state_s state;
  assert(rzv2h_spi_sample_state_at(-1, &state) == -EINVAL);
  assert(rzv2h_spi_sample_state_at(3, &state) == -EINVAL);
  assert(rzv2h_spi_sample_state_at(0, NULL) == -EINVAL);
  for (int port = 0; port < 3; ++port) {
    assert(rzv2h_spi_sample_state_at(port, &state) ==
           (TEST_MASK & (1 << port) ? 0 : -ENODEV));
    assert(!state.identity && !state.registrations && !state.transfers);
  }
  assert(!gpio_configs && !gpio_writes && !node_registrations && !semaphores);
  assert(!enables[0] && !enables[1] && !enables[2]);
  assert(rzv_spi_status(NULL, 0) == 0);
  rzv_spi_select(NULL, 0, true);
  assert(!gpio_writes);
#if TEST_REJECT
  assert(board_spi_initialize() == TEST_REJECT);
  assert(!gpio_configs && !gpio_writes && !node_registrations && !semaphores);
  for (int port = 0; port < 3; ++port) assert(!enables[port] && !writes[port]);
  return 0;
#else
  assert(test_board_invalid_arguments() == 0);
  if (!strcmp(argv[1], "registration-failure")) {
    registration_fault = -EACCES;
    assert(board_spi_initialize() == -EACCES);
    assert(rzv2h_spi_sample_state_at(0, &state) == 0);
    assert(!state.identity && !state.registrations && !clocked[0]);
    assert(!semaphores && !locks);
#ifdef CONFIG_RZV_SPI0
    assert(!g_spi0_priv.initialized);
#endif
    assert(disables[0] == 1);
    unsigned before = writes[0];
    registration_fault = 0;
    assert(board_spi_initialize() == 0 && writes[0] > before);
    assert(enables[0] == 2 && node_registrations == 2);
  } else if (!strcmp(argv[1], "pin-failure")) {
    gpio_fault = 1;
    assert(board_spi_initialize() == -EIO);
    assert(!enables[0] && !writes[0] && !node_registrations);
    gpio_fault = 0;
  } else if (!strcmp(argv[1], "lower-failure")) {
    fault = 4;
    assert(board_spi_initialize() == -ENODEV);
    assert(!clocked[0] && !writes[0] && !node_registrations && !semaphores);
    fault = 0;
  }
  assert(board_spi_initialize() == 0);
  unsigned pins_before = gpio_configs, nodes_before = node_registrations;
  assert(board_spi_initialize() == 0);
  assert(gpio_configs == pins_before && node_registrations == nodes_before);
#ifdef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT
  assert(!gpio_configs && !gpio_writes && !node_registrations);
#else
  assert(gpio_configs >= 4 && node_registrations >= 1);
#endif
  struct spi_dev_s *devices[3] = {NULL};
  for (int port = 0; port < 3; ++port) {
    if (!(TEST_MASK & (1 << port))) continue;
    assert(rzv2h_spi_sample_state_at(port, &state) == 0 && state.identity);
    devices[port] = (struct spi_dev_s *)state.identity;
    assert(state.channel == (unsigned)port);
    assert(state.base == 0x12800000u + port * 0x400u);
#ifdef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT
    assert(state.registrations == 0);
    assert(rzv_spi_status(devices[port], 0) == 0);
#else
    assert(state.registrations == 1);
    assert(rzv_spi_status(devices[port], 0) == SPI_STATUS_PRESENT);
#endif
    unsigned previous_gpio_writes = gpio_writes;
    if (port != 0 || !state.registrations) {
      rzv_spi_select(devices[port], 0, true);
      assert(gpio_writes == previous_gpio_writes);
    }
    assert(state.transfers == 0);
    assert(devices[port]->ops->send(devices[port], 0x55 + port) == 0x55u + port);
    assert(rzv2h_spi_sample_state_at(port, &state) == 0 && state.transfers == 1);
    for (int sibling = port + 1; sibling < 3; ++sibling) {
      if (!(TEST_MASK & (1 << sibling))) continue;
      assert(rzv2h_spi_sample_state_at(sibling, &state) == 0 && !state.transfers);
      assert(state.identity != (uintptr_t)devices[port]);
    }
  }
  assert(rzv2h_spi_sample_state(&state) == (TEST_MASK & 1 ? 0 : -ENODEV));
  for (int port = 0; port < 3; ++port)
    if (devices[port]) assert(rzv_spibus_uninitialize(devices[port]) == 0);
  assert(!semaphores && !locks);
  return 0;
#endif
}
"""


def board_sources(mask, controlled, conflict=None, rejection="0"):
    flags = configuration(mask) + "#define CONFIG_SPI_DRIVER 1\n"
    flags += f"#define TEST_REJECT {rejection}\n"
    if controlled:
        flags += "#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1\n"
    if conflict is not None:
        flags += f"#define CONFIG_RZV_SCI{conflict}_SPI 1\n"
    sample_header = without_includes(BOARD / "include/rzv2h-sample-test.h")
    board = (PRELUDE + flags + without_includes(NUTTX / "include/nuttx/spi/spi.h") +
             without_includes(ARCH / "rzv_spi.h") + sample_header + BOARD_BOUNDARY +
             without_includes(BOARD / "src/rzv2h_spi.c") + r"""
int test_board_invalid_arguments(void) {
  struct spi_dev_s *dev = NULL;
  assert(rzv2h_board_spi_bringup(-1, &dev) == -EINVAL);
  assert(rzv2h_board_spi_bringup(3, &dev) == -EINVAL);
  assert(rzv2h_board_spi_bringup(0, NULL) == -EINVAL);
  for (int port = 0; port < 3; ++port)
    if (!(TEST_MASK & (1 << port)))
      assert(rzv2h_board_spi_bringup(port, &dev) == -ENODEV);
  assert(dev == NULL);
  return 0;
}
""")
    main = driver_source(mask) + flags + sample_header + BOARD_MAIN
    return main, (board,)


class NativeSPIInstances(unittest.TestCase):
    def test_real_rtt_case_list_and_failed_prerequisite_guard(self):
        for family in range(1, 6):
            with self.subTest(family=family):
                config = f"""
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY {family}
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_CHANNEL 0
#define CONFIG_TESTING_RZV_HWTEST_INSTANCE_OUTPUT 0
"""
                app_boundary = r"""
#include <inttypes.h>
static unsigned getters;
static unsigned guard_failure;
static bool identity_failure;
static unsigned stable_failure;
static void host_syslog(int priority, const char *format, ...) {
  (void)priority; (void)format;
}
#define syslog host_syslog
#define LOG_INFO 6
char g_hwtest_fail_reason[128];
int rzv2h_driver_instance_get(unsigned int family, int channel,
                              unsigned int output,
                              struct rzv2h_driver_instance_state_s *out) {
  if (channel < 0 || channel >= 16)
    return (guard_failure == 1 && channel == -1) ||
           (guard_failure == 2 && channel == 16) ? 0 : -EINVAL;
  if (out == NULL) return -EINVAL;
  ++getters;
  if (identity_failure) return -EIO;
  memset(out, 0, sizeof(*out));
  out->family = family; out->channel = channel; out->output = output;
  if (family == 2) {
    struct spi_dev_s *dev = rzv_spibus_initialize(channel);
    if (dev == NULL) return -ENODEV;
    out->identity = (uintptr_t)dev; out->base = rzv_spi_get_base(dev);
  } else { out->identity = 0x1000 + family; out->base = 0x2000 + family; }
  if (stable_failure == 1) return -EIO;
  if (stable_failure == 2) out->identity++;
  if (stable_failure == 3) out->base++;
  if (stable_failure == 4) out->family++;
  if (stable_failure == 5) out->channel++;
  if (stable_failure == 6) out->output++;
  return 0;
}
"""
                main = r"""
int main(void) {
  unsigned count;
  const struct hwtest_case_s *cases = driver_instance_cases(&count);
  assert(count == (CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2 ? 4u : 3u));
  assert(!strcmp(cases[0].name, "guard") && !strcmp(cases[1].name, "identity") &&
         !strcmp(cases[2].name, "stable"));
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
  assert(!strcmp(cases[3].suite, "instance") && !strcmp(cases[3].name, "loopback"));
  assert(cases[3].fn() == HWTEST_FAIL);
  assert(!getters && !reads[0] && !writes[0] && !enables[0]);
#endif
  /* Identity cannot initialize hardware until the invalid-index guard passed. */
  assert(cases[1].fn() == HWTEST_FAIL && !getters);
  assert(!reads[0] && !writes[0] && !enables[0]);
  assert(cases[0].fn() == HWTEST_PASS && !getters);
  identity_failure = true;
  assert(cases[1].fn() == HWTEST_FAIL);
  unsigned before = getters;
  assert(cases[2].fn() == HWTEST_FAIL && getters == before);
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
  assert(cases[3].fn() == HWTEST_FAIL);
  assert(!reads[0] && !writes[0] && !enables[0] && getters == before);
#endif
  identity_failure = false;
  assert(cases[1].fn() == HWTEST_PASS);
  assert(cases[2].fn() == HWTEST_PASS);

  /* A fresh failed guard must invalidate readiness from a successful run. */
  unsigned io_before, calls_before;
  for (unsigned bad_guard = 1; bad_guard <= 2; ++bad_guard) {
    io_before = reads[0] + writes[0]; calls_before = getters;
    guard_failure = bad_guard;
    assert(cases[0].fn() == HWTEST_FAIL);
    assert(cases[1].fn() == HWTEST_FAIL && getters == calls_before);
    assert(cases[2].fn() == HWTEST_FAIL && getters == calls_before);
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
    assert(cases[3].fn() == HWTEST_FAIL);
#endif
    assert(reads[0] + writes[0] == io_before);
    guard_failure = 0;
    assert(cases[0].fn() == HWTEST_PASS);
    assert(cases[1].fn() == HWTEST_PASS && cases[2].fn() == HWTEST_PASS);
  }

  /* Identity failure blocks stable/loopback even after previous success. */
  identity_failure = true;
  assert(cases[1].fn() == HWTEST_FAIL);
  calls_before = getters; io_before = reads[0] + writes[0];
  assert(cases[2].fn() == HWTEST_FAIL && getters == calls_before);
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
  assert(cases[3].fn() == HWTEST_FAIL);
#endif
  assert(reads[0] + writes[0] == io_before);
  identity_failure = false;

  /* Provider errors or unstable identity metadata cannot authorize loopback. */
  for (unsigned failure = 1; failure <= 6; ++failure) {
    assert(cases[1].fn() == HWTEST_PASS);
    stable_failure = failure;
    assert(cases[2].fn() == HWTEST_FAIL);
    stable_failure = 0;
    io_before = reads[0] + writes[0]; calls_before = getters;
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
    assert(cases[3].fn() == HWTEST_FAIL);
#endif
    assert(reads[0] + writes[0] == io_before && getters == calls_before);
  }
  assert(cases[1].fn() == HWTEST_PASS && cases[2].fn() == HWTEST_PASS);
#if CONFIG_TESTING_RZV_HWTEST_INSTANCE_FAMILY == 2
  internal_oracle = true; oracle_port = 0;
  assert(cases[3].fn() == HWTEST_PASS && spdr_writes[0] >= 8);
  internal_oracle = false;
  assert(!(registers[0][RZV_SPI_SPCR2_OFFSET / 4] & SPI_SPCR2_SPLP2));
  assert(rzv_spibus_uninitialize((struct spi_dev_s *)g_state.identity) == 0);
#endif
  assert(!selects && !semaphores && !locks && !dma_calls);
  return 0;
}
"""
                code = (driver_source(1, controlled=True) + config +
                        without_includes(BOARD / "include/rzv2h-sample-test.h") +
                        without_includes(APPS / "testing/rzv_hwtest/hwtest.h") +
                        app_boundary +
                        without_includes(APPS / "testing/rzv_hwtest/core/driver_instance_test.c") +
                        main)
                compile_run(code, [])

    def test_sample_loopback_runs_real_byte_oracle_on_all_controllers(self):
        for mask in (1, 2, 4, 7):
            with self.subTest(mask=mask):
                compile_run(driver_source(mask, controlled=True) + SAMPLE_LOOPBACK_MAIN, ["0"])

    def test_sample_loopback_failures_restore_every_controller(self):
        for fault in (1, 5, 6, 7, 8, 10, 11):
            with self.subTest(fault=fault):
                compile_run(driver_source(7, controlled=True) + SAMPLE_LOOPBACK_MAIN, [str(fault)])

    def test_sample_loopback_refuses_unowned_or_dma_controllers(self):
        compile_run(driver_source(7) + SAMPLE_LOOPBACK_MAIN, ["0"])
        compile_run(driver_source(7, dma=True, controlled=True) + SAMPLE_LOOPBACK_MAIN, ["0"])

    def test_default_driver_builds_without_sample_api(self):
        main = r"""
int main(void) {
  struct spi_dev_s *dev = rzv_spibus_initialize(0);
  assert(dev && semaphores == 1 && clocked[0] && !dma_calls && !selects);
  assert(rzv_spibus_uninitialize(dev) == 0);
  assert(!semaphores && !locks && !clocked[0]);
  return 0;
}
"""
        compile_run(driver_source(1, sample=False) + main, [])

    def test_each_enabled_controller_has_independent_real_state(self):
        for mask in (1, 2, 4, 7):
            with self.subTest(mask=mask):
                compile_run(driver_source(mask) + MAIN, ["lifecycle"])

    def test_initialization_failures_unwind_and_retry_with_a_live_sibling(self):
        for stage in range(1, 5):
            with self.subTest(stage=stage):
                compile_run(driver_source(7) + MAIN, [f"failure-{stage}"])

    def test_reset_release_timeout_restores_reset_before_clock_gating(self):
        for port in range(3):
            with self.subTest(port=port):
                compile_run(driver_source(7) + MAIN, ["failure-4", str(port)])

    def test_other_controllers_remain_polled_with_spi0_dma_selected(self):
        compile_run(driver_source(7, dma=True) + MAIN, ["lifecycle"])

    def test_board_controlled_initialization_is_pinless_and_indexed(self):
        for mask in (1, 2, 4, 7):
            with self.subTest(mask=mask):
                main, board = board_sources(mask, controlled=True)
                compile_run(main, ["lifecycle"], board)

    def test_spi0_board_failures_publish_only_after_success_and_retry(self):
        for mode in ("lifecycle", "registration-failure", "pin-failure", "lower-failure"):
            with self.subTest(mode=mode):
                main, board = board_sources(1, controlled=False)
                compile_run(main, [mode], board)

    def test_unowned_board_routes_fail_before_spi0_or_any_side_effects(self):
        for mask in (2, 4, 3, 5, 7):
            with self.subTest(mask=mask):
                main, board = board_sources(mask, controlled=False, rejection="-ENOTSUP")
                compile_run(main, ["reject"], board)

    def test_native_sci_character_bus_collisions_fail_before_side_effects(self):
        for port in range(3):
            with self.subTest(port=port):
                main, board = board_sources(1 << port, controlled=False,
                                            conflict=port, rejection="-EBUSY")
                compile_run(main, ["reject"], board)

    def test_pinless_unregistered_native_and_distinct_sci_controller_can_coexist(self):
        for port in range(3):
            with self.subTest(port=port):
                main, board = board_sources(1 << port, controlled=True, conflict=port)
                compile_run(main, ["lifecycle"], board)


if __name__ == "__main__":
    unittest.main()
