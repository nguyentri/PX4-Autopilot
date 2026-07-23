# RZ/V2H Hardware Overview

**Date:** 2026-07-11
**Status:** Foundational (Phase 1)
**RDK-RZ/V2H Board Pinout:** [boards/renesas/rdk-rzv2h/src/pinout.md](../../boards/renesas/rdk-rzv2h/src/pinout.md)

This document summarizes key hardware blocks. For board BOM, header assignments, and wiring, see the board pinout above.

---
## DSW1 Setting

| DSW1 | RZ/V2H pin | Default setting | Operation |
|------|------------|-----------------|-----------|
| 1 | BTSEL (BOOSTSELCPU) | ON = High:1 | Select the coldboot CPU.
• High: CA55 *default*
• Low: CM33 |
| 2 | BOOTLLCA_1 | — | See DSW1 switch 3 |
| 3 | BOOTPLLCA_0 | ON = High:1 | Input the CA55 frequency at the CA55 coldboot.
BOOT_PLLCA[1..0]:
• Low/Low: 1.1 GHz
• Low/High: 1.5 GHz (0.9 V)
• High/Low: 1.6 GHz (0.9 V)
• High/High: 1.7 GHz (0.9 V) *default* |
| 4 | — | — | Reserved / no assign |
| 5 | MD_BOOT1 / MD_BOOT0 | ON = Low:0 / OFF = Low:0 | Input the boot mode select signal.
MD_BOOT[1..0]:
• Low/Low: SD *default*
• Low/High: eMMC
• High/Low: xSPI
• High/High: SCIF download |
| 6 | MD_BOOT3 | OFF = Low:0 | Select JTAG debug mode.
• Low: normal mode *default*
• High: JTAG |

> Note: Enable CA55 coldboot only.
Additional Pin Settings
•	MD_CLKS
o	Select SSCG OFF or ON
o	Low: OFF
o	High: ON (default)
•	MD_BOOT4
o	Fix the pin to the low level
•	MD_BOOT2
o	Select the boot device IO voltage, High: 1.8 V
o	Note: Enabled in boot mode 1 and boot mode 2 only





## 1. System Overview

**SoC:** Renesas R9A09G057H (RZ/V2H family)
**Process:** 40 nm
**Temperature Range:** 0–70°C (commercial)

### Core Complex

| Core | Type | Frequency | Cache | TCM |
|------|------|-----------|-------|-----|
| CR8-0 | Cortex-R8 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | 256 KB (I+D) |
| CR8-1 | Cortex-R8 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | 256 KB (I+D) |
| CA55 | Cortex-A55 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | None |
| CM33 | Cortex-M33 | 200 MHz | 32 KB I-cache, 32 KB D-cache | 64 KB |

**Current Port:** CR8-0 primary; CR8-1/CM33 as optional IO co-processors.

---

## 2. Clock System (CPG)

**CPG:** Clock Pulse Generator — controls frequency and power for all blocks.

### Main Clock Tree

```
External Oscillator (24 MHz typical)
  │
  ├─ Main PLL → PLLCLK → /dividers → CPU core (1.5 GHz)
  ├─ Sub  PLL → PLLSCLK → /dividers → SPI, I2C, UART
  ├─ Audio PLL (optional)
  └─ XTAL → RTC clock (32.768 kHz)
```

### Key Frequency Dividers

| Clock | Source | Typical Freq | Function |
|-------|--------|--------------|----------|
| `cpu_clk` | Main PLL | 1.5 GHz | CR8-0/1 core |
| `periphclk` | Sub PLL | varies | Peripheral bus |
| `uart_clk` | Sub PLL | 48 MHz | UART baud generator |
| `spi_clk` | Sub PLL | 100 MHz | SPI transfer clock |
| `rtc_clk` | XTAL | 32.768 kHz | Real-time clock |
| `gpt_clk` | Sub PLL | 48 MHz | GPT PWM |
| `gtm_clk` | Sub PLL | 200 MHz | GTM timer (HRT) |

**Validation:** Clock frequencies must be verified against FSP register truth in `refs/.../rzv_gen/` output. Hardcoded divider values in `rzv_clock.c` are critical; mismatch breaks all bus timing.

### CPG Register Base

- **Address:** 0x41010000 (CR8-0 accessible)
- **Key Registers:** CLKON (enable), CLKDIV (divider), PLL settings
- **Source:** [rzv_clock.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c)

---

## 3. Memory Map (Single-Core CR8-0)

| Region | Start | Size | Type | Cache | Purpose |
|--------|-------|------|------|-------|---------|
| **SRAM** | 0x00000000 | 1 MB | SRAM | Cached | Vector table, kernel stack, boot |
| **TCM (Instruction)** | 0x0C000000 | 128 KB | SRAM | — | Tight instruction coupling |
| **TCM (Data)** | 0x0D000000 | 128 KB | SRAM | — | Tight data coupling |
| **Code Flash** | 0x20000000 | 8 MB | NOR | Cached | NuttX kernel + PX4 code |
| **XSPI Flash** | 0x60000000 | 8 MB | QSPI | Cached | File system (LittleFS) |
| **Shared DRAM** | 0x40000000 | 2 MB | DRAM | Cached | IPC buffers, CR8-1/CM33 firmware |
| **Peripheral I/O** | 0x41000000+ | — | Registers | Uncached | GIC, ICU, GPIO, UART, SPI, etc. |

**Reset Vector:** 0x00000000 (SRAM)
**Linker Script:** [rdk-rzv2h_cr8_0.ld](../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld)

---

## 4. Interrupt Controller (GIC & ICU)

### GIC (Generic Interrupt Controller)

Handles core interrupts from peripherals.

- **Type:** GICv3 (simplified, RZ/V2H variant)
- **Base:** 0x41800000 (CR8-0 view)
- **SPI Interrupts:** 96 (ID 32–127)
- **PPI Interrupts:** 16 (per-core local)
- **SGI Interrupts:** 16 (software-generated inter-processor)

**Registers:**
- `GICD_*` — Distributor (central routing)
- `GICR_*` — Redistributor (per-core enable/priority)
- `ICC_*` — CPU Interface (CPU-side prioritization)

**Source:** [rzv_gic.h](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gic.h) (register definitions)

### ICU (Interrupt Control Unit)

Routes GPIO and external interrupt pins to GIC.

- **Type:** ICU with edge/level triggering
- **Base:** 0x41050000
- **Inputs:** GPIO ports (96 pins), external TINT, sensor IRQs
- **Outputs:** GIC SPI lines

**Features:**
- Edge/level detect per input
- Routing multiplexer (one GPIO pin → multiple GIC lines possible)
- Interrupt clear register

**Source:** [rzv_icu.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_icu.c)

---

## 5. GPIO & Port I/O

**GPIO Controller:**
- **Type:** 5-port (96 pins) + mixed-mode pins
- **Base:** 0x41010400
- **Features:** input/output, pull-up/pull-down, alternate functions, interrupt wiring

**Port Layout:**
- **Port 0–4:** Standard I/O (16 pins each = 80 total)
- **Port 5–6:** Mixed (8 pins each = 16 additional)
- Total: 96 GPIO + special function pins

**Alternate Functions (AF):** Each pin has 0–7 AF options (UART, SPI, I2C, PWM, etc.)

**Source:** [rzv_gpio.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c), [rzv_pinmap.h](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_pinmap.h)

---

## 6. DMA Controller (DMAC-B)

**DMAC-B:** High-bandwidth DMA for bulk transfers (SPI, I2C, Ethernet, storage).

- **Type:** DMAC-B (Renesas specific)
- **Channels:** 8 independent channels
- **Base:** 0x41410000
- **Features:**
  - 32-bit / 16-bit / 8-bit transfer modes
  - Linked-list descriptor chains
  - Hardware flow control (peripheral-initiated)
  - Interrupt on completion / error

**Config:**
- Per-peripheral, one or more channels reserved in Kconfig
- Setup in `rzv_dmac.c` and peripheral-specific drivers (SPI, I2C, Ethernet)

**Source:** [rzv_dmac.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.c)

---

## 7. Message Handling Unit (MHU) & IPCC

**MHU:** Hardware doorbell for inter-core signaling.

- **Type:** ARM MHU (Message Handling Unit)
- **Base:** 0x41490000 (CR8-0 view)
- **Features:**
  - 1-to-1 core signaling (CR8-0 ↔ CR8-1, CR8-0 ↔ CM33)
  - Edge-triggered interrupts
  - Lightweight (no payload, just doorbell)

**IPCC (Inter-Processor Communication Controller):**

NuttX IPCC driver wraps MHU and provides:
- Shared memory ring buffers (in DRAM)
- Message framing (ID, seq, len, CRC)
- Error handling & sequence validation

**Driver:**
- [rzv_mhu_core.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_mhu_core.c) — low-level MHU
- [rzv_ipc_ipcc.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_ipcc.c) — NuttX IPCC device

**References:**
- Commit 289f3203ec6 (IPC refactor)
- [../../boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp](../../boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp)

---

## 8. Timers

### GPT (General PWM Timer)

- **Type:** 16-bit PWM timers
- **Count:** 10 channels (GPT0–9)
- **Base (GPT0):** 0x41410000 (offset per channel)
- **Modes:** PWM, input capture, compare match
- **Freq Range:** 48 MHz clock / divider → 1 kHz–48 MHz
- **Duty:** 16-bit precision (0–65535 counts)
- **Use in PX4:** ESC motor control PWM output

**Source:** [rzv_gpt.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c)

### GTM (General Timer Module)

- **Type:** 32-bit free-running counter
- **Base:** 0x41500000
- **Clock:** 200 MHz (typical)
- **Counter:** 32-bit (wrap ~21 seconds)
- **Use in PX4:** High-resolution timer (HRT) for scheduling
- **Interrupt:** On counter overflow

**Source:** [rzv_gtm.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gtm.c), [rzv_hrt.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_hrt.c)

---

## 9. Serial & UART

**Serial Interfaces:**
- **SCI (Serial Communication Interface):** UART mode, 8 instances (SCI0–7)
- **SCIF (Serial with FIFO):** UART with 16-byte RX/TX buffers
- **Baud Rates:** 9600–921600 bps (configurable per instance)

**PX4 Assignment (Typical):**
- `/dev/ttyS0` → Console (SCI0)
- `/dev/ttyS1` → Debug/shell (SCI1 or SCI4)
- `/dev/ttyS4` → Altitude sensor (TFmini)
- `/dev/ttyS5` → Telemetry modem (Sik)
- `/dev/ttyS6` → RC input (fs-a8s SBUS)
- `/dev/ttyS9` → GPS (u-blox M10)

**Source:** [rzv_serial.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c), [rzv_lowputc.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_lowputc.c) (early bootstrap)

---

## 10. SPI & I2C

### RSPI (Renesas SPI)

- **Type:** SPI master/slave
- **Count:** 2 instances (RSPI0, RSPI1)
- **Speed:** up to 25 MHz
- **Use:** IMU (MPU9250), barometer, flashmemory access
- **DMA:** Integrated with DMAC-B

**Source:** [rzv_spi.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_spi.c)

### RIIC (Renesas I2C)

- **Type:** I2C master/slave
- **Count:** 3 instances (I2C0, I2C1, I2C7)
- **Speed:** Standard (100 kHz), Fast (400 kHz), Fast+ (1 MHz)
- **Use:** Barometer (BMP280), sensor probing

**Source:** [rzv_i2c.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_i2c.c), [rzv_sci_i2c.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_sci_i2c.c) (alternative SCI-based I2C)

---

## 11. Boot Flow (SPL to Firmware)

```
┌──────────────────────┐
│  Hardware Reset      │
│  (cold start)        │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  SPL (ROM loader)    │
│  @ 0x00000000        │
│  - Check XSPI for    │
│    signed image      │
│  - Copy to SRAM      │
│  - Jump to 0x0000    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  NuttX Bootloader    │
│  (rzv_start.c)       │
│  - CPU init (VBAR)   │
│  - Clock setup       │
│  - Memory setup      │
│  - Jump to NuttX OS  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  NuttX Kernel        │
│  - Task scheduler    │
│  - Driver init       │
│  - uORB init         │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  PX4 Flight Stack    │
│  - Modules started   │
│  - Sensors probed    │
│  - MAVLink active    │
└──────────────────────┘
```

**Linker Script:** [rdk-rzv2h_cr8_0.ld](../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld)
**Key Files:**
- [rzv_start.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_start.c) — CPU init, VBAR setup
- [rzv_clock.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c) — CPG initialization

---

## 12. Safety & Watchdog

**POEG (Port Output Enable for GPT):**
- Safety interlock for PWM outputs (fail-safe GPIO drive)
- Triggered by watchdog or external signal
- Used for motor kill-switch

**WDT (Watchdog Timer):**
- 16-bit counter
- Periodic reset required to prevent reboot

**Source:** [rzv_poeg.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_poeg.c), [rzv_wdt.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_wdt.c)

---

## 13. Related Documentation

- **Pinmap Authority:** [pinmap.md](./pinmap.md)
- **System Architecture:** [../system-architecture.md](../system-architecture.md)
- **Board Pinout and Wiring:** [../../boards/renesas/rdk-rzv2h/src/pinout.md](../../boards/renesas/rdk-rzv2h/src/pinout.md)

---

## Notes

- Clock frequencies (CPG dividers) are critical; mismatch breaks all bus timing.
- Memory layout must account for IPC buffers in shared DRAM (0x40000000).
- GIC/ICU wiring is complex; always cross-check against FSP configuration.
- All register addresses assume CR8-0 view; CR8-1/CM33 have offset views per memory map.
