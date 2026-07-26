# NuttX Driver Porting Playbook

**Date:** 2026-07-26
**Status:** Phase 2 (Workflow Enablement)  
**Audience:** Developers porting FSP drivers to NuttX for RZ/V2H

Step-by-step recipe for adding a new driver. Each step references existing exemplars and design patterns documented elsewhere.

---

## Step 1: Read FSP Source

**Goal:** Understand the hardware interface and functional requirements.

**Location:** `refs/px4-freertos-posix-renesas-fsp/rzv/fsp/src/r_<driver>/`

**Read these files:**
- `r_<driver>.h` — API interface (function signatures, config structs)
- `r_<driver>.c` — Implementation (register access, init sequence, ISR patterns)
- `r_<driver>_hal.c` — Hardware abstraction layer (if present)

**Extract and document:**
- Module base address
- Clock resource ID (from CPG)
- Interrupt numbers (ICU entry point, GIC distributor ID)
- Register map (offsets, bit definitions)
- DMA channels (if applicable)
- Pin multiplexing requirements

**Example:** For SPI-B driver:
```
Base:       0x1004A000
CPG:        CPG_SPI_B_CLK (ID = 0x2C)
IRQ (ICU):  SPI_B_INT0 = 32, SPI_B_INT1 = 33
GIC:        (map via interrupt.h)
DMAC:       RX uses DMAC channel 4, TX uses channel 5
Pins:       MOSI=P4_2, MISO=P4_3, CLK=P4_4, CS=P4_5
```

---

## Step 2: Create Hardware Header

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_<driver>.h`

**Content:**
- Register base address macro
- Register offset macros
- Bit definitions and masks
- Interrupt IDs

**Template:**
```c
#ifndef __ARCH_ARM_SRC_RZV_HARDWARE_RZV_<DRIVER>_H
#define __ARCH_ARM_SRC_RZV_HARDWARE_RZV_<DRIVER>_H

#include "chip.h"

/* Register base */
#define RZV_<DRIVER>_BASE     0x1004A000   /* SPI-B example */

/* Register offsets (relative to base) */
#define RZV_<DRIVER>_CTRL_OFF 0x00
#define RZV_<DRIVER>_SR_OFF   0x04
#define RZV_<DRIVER>_DATA_OFF 0x08

/* Register macros */
#define RZV_<DRIVER>_CTRL(base)  (*(volatile uint32_t *)((base) + RZV_<DRIVER>_CTRL_OFF))
#define RZV_<DRIVER>_SR(base)    (*(volatile uint32_t *)((base) + RZV_<DRIVER>_SR_OFF))

/* Bit definitions */
#define RZV_<DRIVER>_CTRL_ENABLE    (1 << 0)
#define RZV_<DRIVER>_CTRL_INT_EN    (1 << 1)
#define RZV_<DRIVER>_SR_RX_READY    (1 << 0)
#define RZV_<DRIVER>_SR_TX_READY    (1 << 1)

/* Interrupt IDs */
#define RZV_<DRIVER>_IRQ0  32
#define RZV_<DRIVER>_IRQ1  33

#endif
```

**Cross-check:** Match against `refs/.../r_<driver>.c` register offsets and bit values. Small errors here cascade.

---

## Step 3: Skeleton Lower-Half Driver

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_<driver>.c`

**Structure:**
```c
#include "rzv_<driver>.h"
#include "hardware/rzv_<driver>.h"

/* Device instance */
static struct rzv_<driver>_dev_s g_rzv_<driver>_dev;

/* Ops table */
static const struct <driver>_ops_s g_rzv_<driver>_ops = {
  .setup = rzv_<driver>_setup,
  .shutdown = rzv_<driver>_shutdown,
  /* ... other ops ... */
};

/* ISR: ack hardware, defer work */
static int rzv_<driver>_isr(int irq, void *context, void *arg) {
  struct rzv_<driver>_dev_s *priv = (void *)arg;
  uint32_t status = RZV_<DRIVER>_SR(priv->base);
  
  /* Clear pending in ICU */
  RZV_ICU_ICLR(priv->icu_id) = 0x01;
  
  if (status & RZV_<DRIVER>_SR_RX_READY) {
    work_queue(HPWORK, &priv->work, rzv_<driver>_rx_worker, priv, 0);
  }
  return OK;
}

/* Deferred work: process data (blocking ops allowed) */
static void rzv_<driver>_rx_worker(FAR void *arg) {
  struct rzv_<driver>_dev_s *priv = (void *)arg;
  /* Read from hardware, update buffers, wake waiting tasks */
}

/* Setup: clock, reset, pins, irq */
static int rzv_<driver>_setup(FAR struct <driver>_dev_s *dev) {
  struct rzv_<driver>_dev_s *priv = (void *)dev;
  
  /* 1. Clock */
  rzv_cpg_enable(priv->clk_id);
  nxsig_usleep(10);
  
  /* 2. Module enable */
  RZV_<DRIVER>_CTRL(priv->base) |= RZV_<DRIVER>_CTRL_ENABLE;
  
  /* 3. Soft reset */
  /* (if module has SRST; depends on FSP) */
  
  /* 4. Pins */
  rzv_pinmux_config(RZV_PINMUX_<DRIVER>_RX, RZV_PIN_FUNC_<n>);
  
  /* 5. IRQ */
  irq_attach(priv->irq, rzv_<driver>_isr, priv);
  up_enable_irq(priv->irq);
  
  /* 6. Module-specific init */
  RZV_<DRIVER>_CTRL(priv->base) |= RZV_<DRIVER>_CTRL_INT_EN;
  
  return OK;
}

/* Shutdown: disable, release resources */
static int rzv_<driver>_shutdown(FAR struct <driver>_dev_s *dev) {
  struct rzv_<driver>_dev_s *priv = (void *)dev;
  
  up_disable_irq(priv->irq);
  irq_detach(priv->irq);
  RZV_<DRIVER>_CTRL(priv->base) &= ~RZV_<DRIVER>_CTRL_ENABLE;
  rzv_cpg_disable(priv->clk_id);
  
  return OK;
}

/* Module initialization */
int rzv_<driver>_initialize(void) {
  struct rzv_<driver>_dev_s *priv = &g_rzv_<driver>_dev;
  
  priv->base = RZV_<DRIVER>_BASE;
  priv->clk_id = RZV_CPG_<DRIVER>_CLK;
  priv->irq = RZV_<DRIVER>_IRQ0;
  nxmutex_init(&priv->lock);
  
  return OK;
}
```

**Reference:** See `rzv_gpt.c` and `rzv_serial.c` for complete implementations.

---

## Step 4: Board Wiring

**File:** `boards/arm/rzv/rdk-rzv2h/src/rzv2h_<driver>.c`

**Content:** Initialize the driver instance and register with upper-half.

```c
#include "nuttx/config.h"
#include "px4_arch/hardware.h"
#include "rzv_<driver>.h"

int rzv2h_<driver>_initialize(void) {
  int ret;
  
  /* Initialize lower-half */
  ret = rzv_<driver>_initialize();
  if (ret < 0) {
    syslog(LOG_ERR, "rzv_<driver>_initialize failed: %d\n", ret);
    return ret;
  }
  
  /* Register upper-half character device */
  ret = <driver>_register("/dev/<driver>0", &g_rzv_<driver>_dev.common);
  if (ret < 0) {
    syslog(LOG_ERR, "<driver>_register failed: %d\n", ret);
    return ret;
  }
  
  return OK;
}
```

**Call this from board init; reference `rzv2h_serial.c` for pattern.**

---

## Step 5: Build System Updates

### 5.1 Kconfig (Driver Enablement)

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig`

Add:
```kconfig
menu "<Driver> (RZV2H)"

config RZV_<DRIVER>
  bool "Enable <Driver> Support"
  default n
  depends on ARCH_CHIP_R9A09G057
  ---help---
    Enable NuttX support for RZ/V2H <Driver> peripheral.
    Requires FSP module r_<driver> for register definitions.

config RZV_<DRIVER>_DMA_RX
  bool "Enable DMA for RX"
  default y
  depends on RZV_<DRIVER> && RZV_DMAC
  ---help---
    Use DMAC for bulk RX transfers (improves throughput).

endmenu
```

### 5.2 Make.defs (Build Rules)

**File:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Make.defs`

Add conditional compilation:
```makefile
ifeq ($(CONFIG_RZV_<DRIVER>),y)
CHIP_CSRCS += rzv_<driver>.c
endif
```

### 5.3 Board-level Makefile

**File:** `boards/arm/rzv/rdk-rzv2h/src/Make.defs`

```makefile
ifeq ($(CONFIG_RZV_<DRIVER>),y)
BOARD_CSRCS += rzv2h_<driver>.c
endif
```

---

## Step 6: Sample Configuration

**Directory:** `boards/arm/rzv/rdk-rzv2h/configs/<driver>/`

Create a minimal defconfig for testing:

**File:** `defconfig`
```
CONFIG_ARCH_CHIP_R9A09G057=y
CONFIG_RZV_<DRIVER>=y
CONFIG_RZV_<DRIVER>_DMA_RX=y
CONFIG_DEBUG_SYMBOLS=y
CONFIG_SYSLOG_TIMESTAMP=y
```

---

## Step 7: Validation Loop

### 7.1 Configure

```bash
cd /home/tringuyen/PX4-Autopilot
./tools/configure.sh rdk-rzv2h:<driver>
```

If custom config absent, fall back to a similar driver config.

### 7.2 Build

```bash
make -j$(nproc) 2>&1 | tee build.log
```

**Fix errors:** undefined references, missing includes, Kconfig syntax.

### 7.3 Link Check

Verify symbols resolved (no undefined references to cpg, dmac, pinmux):

```bash
grep -E "undefined reference|multiple definition" build.log
```

### 7.4 Runtime Test (on RDK-RZ/V2H board)

Flash the image and verify:
- Device appears in `/dev/`
- No crash on open/read/write
- Data transfers match expected byte counts
- No stack overflow (check syslog)

**Example (UART):**
```bash
# Select the physical channel owned by the image under test.
CONSOLE_DEV=/dev/ttyS4
test -e "${CONSOLE_DEV}"
echo "test" > "${CONSOLE_DEV}"
cat "${CONSOLE_DEV}"  # or use a serial monitor
```

RDK-RZ/V2H keeps physical SCI numbering in device names; selecting a console
does not rename it to `/dev/ttyS0`. Standalone NSH target ownership is SCI4
(`/dev/ttyS4`) on CR8-0, SCI5 (`/dev/ttyS5`) on CR8-1, and SCI9
(`/dev/ttyS9`) on CM33. CR8-1 and CM33 mappings remain hardware-validation
targets until their sample configurations are aligned and tested.

The integrated PX4 CR8-0 image uses RTT0 for console/debug output instead.
Its UARTs retain payload ownership: SCI4 LiDAR, SCI5 MAVLink/QGroundControl,
SCI6 RC at 100000 8E2 with the inversion path proved, and SCI9 GPS at
115200 8N1. These framing checks gate the first drone-equivalent run. Never
mix text diagnostics and binary MAVLink on RTT0.

---

## Step 8: Code Review Checklist

Before pushing:

- [ ] Hardware header (`rzv_<driver>.h`) matches FSP register offsets
- [ ] ISR acks interrupt early; defers heavy work
- [ ] Cache invalidate/clean wraps DMA (RX/TX)
- [ ] Init sequence: clock → enable → reset → pins → IRQ → config
- [ ] Error codes propagated (not swallowed)
- [ ] nxmutex protects shared state; critical sections protect R-M-W
- [ ] No malloc/free in ISR
- [ ] Kconfig help text explains constraints and dependencies
- [ ] Make.defs rules added to both chip and board Makefile
- [ ] Sample config compiles without errors

**Cross-reference:** [Design Guidelines](./design-guidelines.md), [Code Standards](../code-standards.md)

---

## Related References

- [Design Guidelines](./design-guidelines.md) — ISR, DMAC, init sequence details
- [Code Standards](../code-standards.md) — formatting, naming, commit conventions
- [FreeRTOS-to-NuttX Mapping](./freertos-to-nuttx-mapping.md) — API substitutions
- FSP Reference: `refs/px4-freertos-posix-renesas-fsp/rzv/fsp/src/r_<driver>/`

---

**Maintenance:** Update when NuttX driver interface or build system changes; track in Phase 3+ reviews.
