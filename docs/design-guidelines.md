# NuttX Driver Design Guidelines

**Date:** 2026-07-11  
**Status:** Phase 2 (Workflow Enablement)  
**Scope:** RZ/V2H driver architecture patterns, ISR rules, DMA integration, init sequencing

This document codifies patterns used in reference drivers (rzv_gpt.c, rzv_serial.c). Follow these patterns when porting new drivers from FSP to NuttX.

---

## 1. Lower-Half / Upper-Half Split

### 1.1 Pattern Overview

NuttX device drivers use a **two-layer architecture**:

- **Lower-half:** Hardware-specific; lives in `arch/arm/src/rzv/`
  - Direct register access
  - Interrupt handlers
  - Clock/pin/DMA setup
  - No OS-dependent calls; minimal blocking

- **Upper-half:** Middleware/character-device interface; lives in `drivers/`
  - POSIX read/write/ioctl
  - Task-safe buffering, queues
  - Calls into lower-half via ops table

### 1.2 Lower-Half Skeleton

```c
/* File: platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_<driver>.h */

struct rzv_<driver>_dev_s {
  struct <driver>_dev_s common;    /* NuttX upper-half interface */
  uint32_t base;                   /* Register base address */
  uint32_t clk_id;                 /* CPG clock resource ID */
  int irq;                         /* Interrupt number */
  /* Driver-specific state */
  volatile uint8_t flags;          /* Status: RZV_<DRIVER>_FLAG_* */
  /* DMA resource pointers (if applicable) */
  struct rzv_dmac_s *tx_dmac;
  struct rzv_dmac_s *rx_dmac;
};

/* Ops table; implement all required callbacks */
static const struct <driver>_ops_s g_rzv_<driver>_ops = {
  .setup = rzv_<driver>_setup,
  .shutdown = rzv_<driver>_shutdown,
  .ioctl = rzv_<driver>_ioctl,
  /* ... other ops ... */
};

/* Initialize device state; called once at boot */
int rzv_<driver>_initialize(void);

/* Register lower-half with upper-half */
int <driver>_register(FAR const char *path, 
                      FAR struct <driver>_dev_s *dev);
```

### 1.3 Upper-Half Integration

Upper-half driver calls ops table:

```c
/* File: drivers/<driver>/<driver>_main.c (sketch) */

static ssize_t <driver>_read(FAR struct file *filep, FAR char *buffer,
                             size_t buflen) {
  FAR struct <driver>_dev_s *priv = filep->f_inode->i_private;
  /* Call lower-half (non-blocking) */
  return priv->ops->read(priv, buffer, buflen);
}

static int <driver>_ioctl(FAR struct file *filep, int cmd, unsigned long arg) {
  return priv->ops->ioctl(priv, cmd, arg);
}
```

---

## 2. Interrupt Service Routine (ISR) Rules

### 2.1 Core Constraints

ISRs in NuttX **cannot**:
- Sleep, wait on semaphores, or call blocking OS functions
- Call malloc/free (use pre-allocated buffers)
- Call printf (use DEBUGASSERT or deferred logging via work-queue)

ISRs **can**:
- Post to work-queues for deferred work
- Update simple state (flags, counters)
- Acknowledge hardware (clear pending bits, read status)

### 2.2 Interrupt Acknowledgment Sequence

**Order matters:**
1. Read hardware status register (preserves which interrupt fired)
2. **Clear pending bit** in the interrupt controller (ICU or GIC)
3. Process the event (minimal logic; defer heavy work)
4. Return HANDLED or NOT_HANDLED

**Example (pseudocode):**
```c
static int rzv_<driver>_isr(int irq, void *context, void *arg) {
  struct rzv_<driver>_dev_s *priv = (void *)arg;
  
  /* Step 1: read status */
  uint32_t status = RZV_<DRIVER>_STATUS(priv->base);
  
  /* Step 2: clear pending in ICU (GIC will auto-clear if configured) */
  RZV_ICU_ICLR(priv->icu_id) = 0x01;  /* Clear pending flag */
  
  /* Step 3: defer heavy work */
  if (status & RZV_<DRIVER>_STATUS_RX_RDY) {
    work_queue(HPWORK, &priv->work, rzv_<driver>_rx_worker, priv, 0);
  }
  
  return OK;  /* or IRQ_HANDLED */
}
```

### 2.3 Deferred Work Pattern

Use work-queue for actual data processing:

```c
static void rzv_<driver>_rx_worker(FAR void *arg) {
  struct rzv_<driver>_dev_s *priv = (void *)arg;
  uint32_t status;
  
  /* Now we can call blocking OS functions, sleep, etc. */
  nxmutex_lock(&priv->lock);
  status = RZV_<DRIVER>_STATUS(priv->base);
  /* Process RX data */
  nxmutex_unlock(&priv->lock);
}
```

---

## 3. DMAC Integration Checklist

Use Direct Memory Access for bulk data transfer (serial RX/TX, SPI, I2C).

### 3.1 Cache Coherency

**Critical:** RZ/V2H has a data cache (32 KB per core). DMA bypasses cache:

| Operation | Action | Timing |
|-----------|--------|--------|
| **Before RX DMA** | Invalidate D-cache (address range of RX buffer) | Before: `cplevel_dcache_invalidate(addr, len)` |
| **After RX DMA** | Confirm cache line is invalid | DMA complete callback |
| **Before TX DMA** | Clean D-cache (ensure buffer reflects latest writes) | Before: `cplevel_dcache_clean(addr, len)` |
| **After TX DMA** | Barrier (no further writes to buffer until complete) | Callback posts event to application |

**Why:** If core writes to cache, then DMA reads without cache-clean, DMA sees stale data.

### 3.2 DMAC Configuration

```c
struct rzv_dmac_xfer_s {
  uint32_t src;              /* Source (or HW register for RX) */
  uint32_t dst;              /* Destination (or HW register for TX) */
  uint32_t len;              /* Byte count */
  uint32_t src_incr;         /* 0: fixed, 1: incr by src_width */
  uint32_t dst_incr;         /* 0: fixed, 1: incr by dst_width */
  uint8_t src_width;         /* 1, 2, 4, 8 bytes */
  uint8_t dst_width;         /* 1, 2, 4, 8 bytes */
  uint8_t unit;              /* Transaction unit (1, 2, 4, 8 bytes) */
  dmac_callback_t callback;  /* Called at completion */
};
```

### 3.3 Alignment & Length Bounds

- **Buffers:** Align to max(src_width, dst_width)
- **Transfer length:** Must be integral multiple of unit size
- **Max length:** Check DMAC register width (typically 24-bit for length field)

**Example:**
```c
/* RX buffer for UART (1-byte units) */
uint8_t rx_buf[256] __attribute__((aligned(4)));  /* DMA may do 4-byte chunks */

/* Configure RX DMA */
xfer.src = RZV_SCIF_RDR(base);    /* Hardware register; no increment */
xfer.dst = (uint32_t)rx_buf;      /* Destination buffer */
xfer.len = 256;                    /* Byte count */
xfer.src_incr = 0;                /* Reg doesn't move */
xfer.dst_incr = 1;                /* Buffer increments */
xfer.src_width = 1;
xfer.dst_width = 1;
xfer.unit = 1;
xfer.callback = rzv_dmac_rx_done;  /* Deferred work posted here */

rzv_dmac_xfer(priv->rx_dmac, &xfer);
```

---

## 4. Initialization Sequence

**Order is critical; violating sequence causes hangs or faults.**

1. **Clock (CPG):** Enable clock for the module
   ```c
   rzv_cpg_enable(priv->clk_id);
   ```

2. **Module enable:** Assert module enable bit
   ```c
   RZV_<DRIVER>_ENABLE(priv->base) = 1;
   ```

3. **Soft reset:** De-assert soft reset (if module has one)
   ```c
   RZV_<DRIVER>_SRST(priv->base) = 0;  /* Release reset */
   (void)RZV_<DRIVER>_SRST(priv->base);/* Read-back barrier */
   ```

4. **Pin mux:** Configure pinmux for peripheral
   ```c
   rzv_pinmux_config(RZV_PINMUX_<DRIVER>_TX, RZV_PIN_FUNC_<n>);
   ```

5. **ICU / IRQ routing:** Attach interrupt controller
   ```c
   irq_attach(priv->irq, rzv_<driver>_isr, priv);
   up_enable_irq(priv->irq);
   ```

6. **GIC (if needed):** Enable interrupt at distributor (for CA55)
   ```c
   arm_gic_irq_enable(priv->irq);
   ```

7. **Driver-specific init:** Configure module registers, thresholds, modes
   ```c
   RZV_<DRIVER>_CTRL(priv->base) = RZV_<DRIVER>_CTRL_MODE_ACTIVE;
   ```

8. **Upper-half registration:** Register with NuttX character device
   ```c
   <driver>_register("/dev/<driver>0", priv);
   ```

---

## 5. Reset Sequencing Hazards

### 5.1 Soft Reset Bit Ordering

Some modules require bit-level sequence:

```c
/* Problematic: sets and reads same register (may not latch reset) */
RZV_<DRIVER>_SRST(base) = 0;

/* Correct: write, then read different register as barrier */
RZV_<DRIVER>_SRST(base) = 0;
(void)RZV_<DRIVER>_SRST(base);  /* Read-back ensures write committed */
```

The read-back acts as a memory barrier; do not omit.

### 5.2 Clock Stability

After enabling clock via CPG, allow settling time:

```c
rzv_cpg_enable(priv->clk_id);
nxsig_usleep(10);  /* Clock stabilization delay (HW-specific) */
```

Typically 1–10 μs; check FSP `r_<driver>_api.c` for timing.

---

## 6. Error Propagation

### 6.1 Return Codes

Propagate errors immediately; don't swallow in lower-half:

```c
static int rzv_<driver>_setup(FAR struct <driver>_dev_s *dev) {
  int ret;
  
  ret = rzv_pinmux_config(RZV_PINMUX_..., RZV_PIN_FUNC_...);
  if (ret < 0) {
    syslog(LOG_ERR, "pinmux failed: %d\n", ret);
    return ret;  /* Propagate to caller */
  }
  
  return OK;
}
```

### 6.2 DEBUGASSERT for Logic Errors

Use for invariants that indicate a bug, not runtime failures:

```c
DEBUGASSERT(priv != NULL);
DEBUGASSERT(priv->base != 0);  /* Catches uninitialized pointers */
DEBUGASSERT((len & 0x3) == 0); /* Length is 4-byte aligned */
```

DEBUGASSERT is stripped in non-debug builds; use syslog for recovery paths.

---

## 7. Concurrency & Critical Sections

### 7.1 Hardware Register Read-Modify-Write

Register R-M-W is not atomic; protect with critical section:

```c
static void rzv_<driver>_set_flag(struct rzv_<driver>_dev_s *priv, uint32_t flag) {
  irqstate_t state = up_irq_save();
  
  uint32_t reg = RZV_<DRIVER>_CTRL(priv->base);
  reg |= flag;
  RZV_<DRIVER>_CTRL(priv->base) = reg;
  
  up_irq_restore(state);
}
```

**Pattern:**
```c
irqstate_t state = up_irq_save();
/* R-M-W sequence; interrupts disabled */
up_irq_restore(state);
```

### 7.2 Mutex for Software State

Use nxmutex for non-atomic software structures:

```c
struct rzv_<driver>_dev_s {
  /* ... */
  struct nxmutex_s lock;
};

/* During init */
nxmutex_init(&priv->lock);

/* During operation */
nxmutex_lock(&priv->lock);
priv->flags |= RZV_<DRIVER>_FLAG_BUSY;
nxmutex_unlock(&priv->lock);
```

---

## 8. Reference Exemplars

Inspect these drivers for complete pattern implementation:

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c` — timer driver (ISR, work-queue, init sequence)
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c` — UART driver (DMA integration, lower/upper split)

Read the actual code; this guide is a summary.

---

## 9. Related References

- [Code Standards](./code-standards.md) — formatting rules
- [System Architecture](./system-architecture.md) — core topology, IPC
- [Hardware Overview](./renesas/hardware.md) — clock, IRQ, GIC, DMAC
- [Porting Playbook](./renesas/porting-playbook.md) — step-by-step guide

---

**Maintenance:** Revise when new driver patterns emerge or FSP releases breaking changes to register maps.
