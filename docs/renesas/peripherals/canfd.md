# CAN-FD Peripheral Specification

**Date:** 2026-07-11  
**Hardware:** Renesas RZ/V2H (R9A09G057H)  
**Scope:** CAN-FD controller block documentation for driver development.

---

## Hardware Block Overview

**Peripheral:** Flexible Data-rate CAN (CAN-FD) controller supporting classical CAN 2.0B and CAN-FD.

**Instances on RDK-RZ/V2H:**
- CAN0: Channel 0 (primary UAV link)
- CAN1: Channel 1 (redundant or alternate link)

---

## Pin Assignment

### CAN0
- **TXD:** Port 6 Pin 0 (alternate function 2)
- **RXD:** Port 6 Pin 1 (alternate function 2)
- **Termination:** 120 Ω pull-up/pull-down on board (verify with schematics).

### CAN1
- **TXD:** Port 7 Pin 4 (alternate function 2)
- **RXD:** Port 7 Pin 5 (alternate function 2)

**Verification:** Cross-reference `rzv_pinmap.h` and board defconfig.

---

## Clock Source

**Peripheral Clock:** CANFD_CLK (from CPG module).

**Derivation:**
- PCLK base: 100 MHz (typical)
- CANFD divisor: Set via CPG CK_ON register
- Final frequency: PCLK / divisor (check datasheet Table X for supported divisors)

**Bitrate Calculation:**
```
Bitrate = CANFD_CLK / (1 + (TSEG1 + TSEG2))
```

- **250 kbps:** CANFD_CLK = 50 MHz, TSEG1 = 8, TSEG2 = 3
- **500 kbps:** CANFD_CLK = 100 MHz, TSEG1 = 8, TSEG2 = 3
- **1 Mbps:** CANFD_CLK = 100 MHz, TSEG1 = 4, TSEG2 = 1

---

## Interrupt Mapping

**Interrupt Controller:** ICU (Interrupt Control Unit)

| Event | ICU IRQ | Priority | Handler |
|-------|---------|----------|---------|
| CAN0 RX | 212 | 4 | `rzv_canfd_rx_isr(CAN0)` |
| CAN0 TX | 213 | 4 | `rzv_canfd_tx_isr(CAN0)` |
| CAN0 Error | 214 | 3 | `rzv_canfd_err_isr(CAN0)` |
| CAN1 RX | 215 | 4 | `rzv_canfd_rx_isr(CAN1)` |
| CAN1 TX | 216 | 4 | `rzv_canfd_tx_isr(CAN1)` |
| CAN1 Error | 217 | 3 | `rzv_canfd_err_isr(CAN1)` |

(IRQ numbers from UM section Interrupt Controller; verify against `rzv_irq.h`.)

---

## DMAC Channel Assignment

**If DMA-accelerated RX/TX enabled:**

| Channel | Direction | Peripheral | Example |
|---------|-----------|------------|---------|
| 4 | CAN0 RX → RAM | CAN0 RX buffer | Linked descriptor chain |
| 5 | RAM → CAN0 TX | CAN0 TX buffer | Linked descriptor chain |

*Note:* Standard polling also supported; DMA optional for high-throughput scenarios.

---

## FSP Reference

Use the core-matched `can_fd` EVK project described in
[reference-source-map.md](../reference-source-map.md):

- **Project:** `refs/rzv2h_evk/can_fd/can_fd_rzv2h_evk_<core>_ep/e2studio/`
- **Driver:** `rzv/fsp/src/r_canfd/r_canfd.c`
- **Configuration:** `configuration.xml`, `rzv_cfg/fsp_cfg/r_canfd_cfg.h`
- **Generated integration:** `rzv_gen/{hal_data,vector_data,pin_data}.*`
- **Datasheet:** Cross-reference register definitions with the Renesas CAN-FD section.

Select `<core>` as `cm33`, `cr8_0`, or `cr8_1`; generated vectors and
configuration are core-specific evidence.

---

## NuttX Driver

**File:** `arch/arm/src/rzv/rzv_canfd.c`  
**Header:** `arch/arm/src/rzv/hardware/rzv_canfd.h`

**Initialization:**
```c
canfd_initialize(CAN0);  /* Register /dev/can0 */
canfd_initialize(CAN1);  /* Register /dev/can1 */
```

**Sample Configuration:**
- `configs/canfd/defconfig` — Single CAN0 enabled.
- `configs/canfd-dual/defconfig` — Both CAN0 and CAN1 enabled.

---

## Register Map

**Base Addresses (from UM):**
- CAN0: 0x110A0000
- CAN1: 0x110B0000

**Key Registers:**
- **MCR** (Mode Control Register): Set CAN mode (init, test, listen-only).
- **CTLR** (Control Register): Enable TX, RX, interrupts.
- **TXFIFOCR** (TX FIFO Control): Manage TX queue depth.
- **RXFIFOCR** (RX FIFO Control): Manage RX queue depth.
- **GAFLECTR** (Global Acceptance Filter List Entry Control): Message filtering.
- **CFCCR** (CAN-FD Composite Frame Config Control): FD-specific (data rate phase).

**Cache Coherency:** If using DMA, flush TX buffer before enabling TX DMA; invalidate RX buffer after DMA complete (ARM dcache operations).

---

## Driver Validation

**Checklist:** [Validation Checklist](../validation-checklist.md)

**Key Tests:**
- Loopback: CAN0 TXD → RXD (internal); send frame, verify RX callback.
- Dual-channel: Send CAN0 frame, verify isolated from CAN1 RX.
- Bitrate sweep: 250k, 500k, 1M baud rates; measure timing with CAN analyzer.
- Stress: 10k frames at 1 Mbps without drop.

**Test Fixture:** `configs/canfd/` and `configs/canfd-dual/` board configs + loopback cable.

---

## Related Docs

- [Port Status Matrix](../port-status-nuttx.md) — CAN-FD driver row.
- [System Architecture](../../system-architecture.md) — CAN role in flight control loop.
