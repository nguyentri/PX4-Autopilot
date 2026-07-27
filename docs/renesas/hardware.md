# RZ/V2H RDK Hardware Guide for PX4 NuttX Development

**Board:** Renesas RDK-RZ/V2H
**Target software stack:** PX4 on NuttX
**Primary development target:** CR8-0
**Date:** 2026-07-26
**Status:** Consolidated development reference

This document consolidates the hardware notes for the RZ/V2H RDK board into a single PX4/NuttX-focused reference. It is intended for board bring-up, driver development, boot/debug configuration, and hardware-software validation.

For detailed board BOM, connector/header assignments, and external wiring, use the board pinout as the authority:

- `boards/renesas/rdk-rzv2h/src/pinout.md`
- `boards/renesas/rdk-rzv2h/src/pinout.md` is referenced from the original hardware notes as the RDK-RZ/V2H board pinout.

---

## 1. Boot Switches and Mode Pins

### 1.1 DSW1 Settings

| DSW1 | RZ/V2H pin | Default setting | Operation |
|---|---|---|---|
| 1 | BTSEL / BOOSTSELCPU | ON = High: 1 | Selects cold-boot CPU. High: CA55 default. Low: CM33. |
| 2 | BOOTPLLCA_1 | - | Used with DSW1 switch 3 for CA55 PLL frequency selection. |
| 3 | BOOTPLLCA_0 | ON = High: 1 | Selects CA55 frequency at CA55 cold boot. BOOT_PLLCA[1:0]: Low/Low = 1.1 GHz, Low/High = 1.5 GHz at 0.9 V, High/Low = 1.6 GHz at 0.9 V, High/High = 1.7 GHz at 0.9 V default. |
| 4 | - | - | Reserved / no assignment. |
| 5 | MD_BOOT1 / MD_BOOT0 | ON = Low: 0 / OFF = Low: 0 | Selects boot mode. MD_BOOT[1:0]: Low/Low = SD default, Low/High = eMMC, High/Low = xSPI, High/High = SCIF download. |
| 6 | MD_BOOT3 | OFF = Low: 0 | Selects JTAG debug mode. Low: normal mode default. High: JTAG. |

**Important:** Enable CA55 cold boot only.

### 1.2 Additional Mode Pin Settings

- **MD_CLKS**
  - Selects SSCG OFF or ON.
  - Low: OFF.
  - High: ON default.
- **MD_BOOT4**
  - Fixed to low level.
- **MD_BOOT2**
  - Selects boot-device I/O voltage.
  - High: 1.8 V.
  - Enabled only in boot mode 1 and boot mode 2.

### PX4/NuttX Development Notes

- Use DSW1 settings to confirm whether the board is in normal boot, JTAG, SD, eMMC, xSPI, or SCIF download mode before debugging boot failures.
- For early PX4/NuttX bring-up, keep the boot source and debug mode stable and record the exact switch positions in test logs.
- If JTAG attach fails, confirm DSW1-6 and reset-mode hardware before assuming a software issue.

---

## 2. System Overview

### 2.1 SoC

- **SoC:** Renesas R9A09G057H, RZ/V2H family.
- **Process:** 40 nm.
- **Temperature range:** 0-70 deg C commercial.

### 2.2 Core Complex

| Core | Type | Frequency | Cache | TCM |
|---|---|---:|---|---|
| CR8-0 | Cortex-R8 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | 256 KB I+D |
| CR8-1 | Cortex-R8 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | 256 KB I+D |
| CA55 | Cortex-A55 | 1.5 GHz | 32 KB I-cache, 32 KB D-cache | None |
| CM33 | Cortex-M33 | 200 MHz | 32 KB I-cache, 32 KB D-cache | 64 KB |

**Current PX4/NuttX port assumption:** CR8-0 is the primary execution core. CR8-1 and CM33 are optional I/O co-processors.

### PX4/NuttX Development Notes

- Treat CR8-0 as the owner of board initialization, scheduler startup, PX4 module execution, and primary peripheral bring-up unless the architecture is explicitly changed.
- If CR8-1 or CM33 is enabled later, define deterministic ownership for peripherals, shared memory, interrupts, and IPC before adding runtime logic.
- Keep single-core CR8-0 boot stable before introducing multi-core features.

---

## 3. Clock System: CPG

The **CPG**, or Clock Pulse Generator, controls frequency and power for processor and peripheral blocks.

### 3.1 Main Clock Tree

```text
External Oscillator, typically 24 MHz
  |
  |-- Main PLL  -> PLLCLK  -> dividers -> CPU core, 1.5 GHz
  |-- Sub PLL   -> PLLSCLK -> dividers -> SPI, I2C, UART
  |-- Audio PLL -> optional audio clocking
  `-- XTAL      -> RTC clock, 32.768 kHz
```

### 3.2 Key Frequency Dividers

| Clock | Source | Typical frequency | Function |
|---|---|---:|---|
| cpu_clk | Main PLL | 1.5 GHz | CR8-0 / CR8-1 core clock |
| periphclk | Sub PLL | Varies | Peripheral bus clock |
| uart_clk | Sub PLL | 48 MHz | UART baud generator |
| spi_clk | Sub PLL | 100 MHz | SPI transfer clock |
| rtc_clk | XTAL | 32.768 kHz | Real-time clock |
| gpt_clk | Sub PLL | 48 MHz | GPT PWM clock |
| gtm_clk | Sub PLL | 200 MHz | GTM / HRT timer clock |

### 3.3 CPG Register Base

- **Base address:** `0x41010000`, CR8-0 accessible.
- **Key registers:** `CLKON`, `CLKDIV`, PLL settings.
- **Driver source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c`

### PX4/NuttX Development Notes

- Clock frequencies must be verified against the FSP-generated register truth under `refs/.../rzv_gen/`.
- Hardcoded divider values in `rzv_clock.c` are critical. A mismatch can break UART baud rate, SPI timing, I2C timing, PWM frequency, HRT scheduling, and driver timeout behavior.
- During bring-up, validate clocks before debugging higher-level PX4 sensor or actuator issues.

---

## 4. Memory Map: Single-Core CR8-0

| Region | Start | Size | Type | Cache | Purpose |
|---|---:|---:|---|---|---|
| SRAM | `0x00000000` | 1 MB | SRAM | Cached | Vector table, kernel stack, boot |
| TCM Instruction | `0x0C000000` | 128 KB | SRAM | - | Tight instruction coupling |
| TCM Data | `0x0D000000` | 128 KB | SRAM | - | Tight data coupling |
| Code Flash | `0x20000000` | 8 MB | NOR | Cached | NuttX kernel and PX4 code |
| XSPI Flash | `0x60000000` | 8 MB | QSPI | Cached | File system, LittleFS |
| Shared DRAM | `0x40000000` | 2 MB | DRAM | Cached | IPC buffers, CR8-1 / CM33 firmware |
| Peripheral I/O | `0x41000000+` | - | Registers | Uncached | GIC, ICU, GPIO, UART, SPI, etc. |

- **Reset vector:** `0x00000000`, SRAM.
- **Linker script:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld`

### PX4/NuttX Development Notes

- Confirm that the linker script matches the actual boot flow and memory map.
- Reserve shared DRAM intentionally if IPC, secondary-core firmware, PX4IO-style bridge logic, or shared logging is used.
- Keep peripheral I/O mappings uncached.
- For multi-core expansion, define cacheability and coherency policy for every shared memory region.

---

## 5. Interrupt System: GIC and ICU

### 5.1 GIC: Generic Interrupt Controller

The GIC handles core interrupts from peripherals.

- **Type:** GICv3, simplified RZ/V2H variant.
- **Base address:** `0x41800000`, CR8-0 view.
- **SPI interrupts:** 96, interrupt ID 32-127.
- **PPI interrupts:** 16 per-core local interrupts.
- **SGI interrupts:** 16 software-generated inter-processor interrupts.

Key register groups:

- `GICD_*`: Distributor, central routing.
- `GICR_*`: Redistributor, per-core enable and priority.
- `ICC_*`: CPU interface, CPU-side prioritization.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gic.h`

### 5.2 ICU: Interrupt Control Unit

The ICU routes GPIO and external interrupt pins to the GIC.

- **Type:** ICU with edge/level triggering.
- **Base address:** `0x41050000`.
- **Inputs:** GPIO ports, external TINT, sensor IRQs.
- **Outputs:** GIC SPI lines.

Features:

- Edge/level detection per input.
- Routing multiplexer.
- Interrupt clear register.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_icu.c`

### PX4/NuttX Development Notes

- Validate interrupt routing before driver-level debugging.
- Sensor IRQ issues may originate from GPIO pin configuration, ICU routing, GIC enable/priority, or driver ISR registration.
- For future multi-core support, explicitly define interrupt target CPU and redistributor setup.

---

## 6. GPIO and Port I/O

### 6.1 GPIO Controller

- **Type:** 5-port GPIO plus mixed-mode pins.
- **Base address:** `0x41010400`.
- **Features:** Input, output, pull-up, pull-down, alternate functions, interrupt wiring.

### 6.2 Port Layout

- Port 0-4: Standard I/O, 16 pins each, 80 total.
- Port 5-6: Mixed-mode pins, 8 pins each, 16 additional pins.
- Total: 96 GPIO plus special-function pins.

### 6.3 Alternate Functions

Each pin has alternate function options for peripherals such as UART, SPI, I2C, PWM, and other functions.

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_pinmap.h`

### PX4/NuttX Development Notes

- Treat the pinmap as the source of truth for PX4 board wiring.
- Validate pinmux configuration early for console UART, debug UART, sensor buses, PWM outputs, and external interrupts.
- Use a board-level pinout document to avoid conflicts between PX4 sensor, telemetry, RC, GPS, and actuator functions.

---

## 7. DMA Controller: DMAC-B

DMAC-B provides high-bandwidth DMA for bulk transfers.

- **Type:** Renesas DMAC-B.
- **Channels:** 8 independent channels.
- **Base address:** `0x41410000`.

Features:

- 32-bit, 16-bit, and 8-bit transfer modes.
- Linked-list descriptor chains.
- Hardware flow control for peripheral-initiated transfers.
- Interrupt on completion or error.

Configuration:

- Channels are reserved per peripheral in Kconfig.
- Setup is handled in `rzv_dmac.c` and peripheral-specific drivers such as SPI, I2C, Ethernet, and storage.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.c`

### PX4/NuttX Development Notes

- Use DMA for high-throughput or low-latency sensor, storage, and communication paths only after polling/interrupt bring-up is stable.
- Verify buffer alignment, cache maintenance, descriptor ownership, and completion interrupts.
- Avoid silent channel conflicts by keeping Kconfig channel allocation explicit.

---

## 8. Inter-Core Communication: MHU and IPCC

### 8.1 MHU: Message Handling Unit

The MHU is a hardware doorbell for inter-core signaling.

- **Type:** ARM MHU.
- **Base address:** `0x41490000`, CR8-0 view.

Features:

- One-to-one core signaling.
- CR8-0 <-> CR8-1.
- CR8-0 <-> CM33.
- Edge-triggered interrupts.
- Lightweight doorbell behavior with no payload.

### 8.2 IPCC: Inter-Processor Communication Controller

The NuttX IPCC driver wraps MHU and provides:

- Shared-memory ring buffers in DRAM.
- Message framing with ID, sequence, length, and CRC.
- Error handling and sequence validation.

Drivers:

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_mhu_core.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_ipcc.c`

References:

- Commit `289f3203ec6`, IPC refactor.
- `boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp`

### PX4/NuttX Development Notes

- Keep the first PX4/NuttX target simple: CR8-0 primary, other cores disabled or treated as future co-processors.
- For future PX4IO-like partitioning, define shared-memory layout, ring-buffer ownership, interrupt ownership, sequence handling, and failure recovery.
- MHU only signals. Payload must live in shared memory.

---

## 9. Timers

### 9.1 GPT: General PWM Timer

- **Type:** 16-bit PWM timers.
- **Count:** 10 channels, GPT0-GPT9.
- **Base address for GPT0:** `0x41410000`, with per-channel offsets.
- **Modes:** PWM, input capture, compare match.
- **Frequency range:** 48 MHz clock divided down to application frequency.
- **Duty precision:** 16-bit, 0-65535 counts.
- **PX4 use:** ESC motor-control PWM output.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c`

### 9.2 GTM: General Timer Module

- **Type:** 32-bit free-running counter.
- **Base address:** `0x41500000`.
- **Clock:** 200 MHz typical.
- **Counter:** 32-bit, wraps in approximately 21 seconds at 200 MHz.
- **PX4 use:** High-resolution timer, HRT, for scheduling.
- **Interrupt:** Counter overflow.

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gtm.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_hrt.c`

### PX4/NuttX Development Notes

- HRT correctness is foundational for PX4 scheduling, work queues, sensor timing, and actuator timing.
- Validate GTM frequency, counter read behavior, overflow handling, and interrupt latency.
- Validate GPT PWM frequency and duty accuracy with scope capture before motor or actuator integration.

---

## 10. Serial and UART

### 10.1 Serial Interfaces

- **SCI:** Serial Communication Interface, UART mode, 10 instances SCI0-SCI9.
- **SCIF:** Serial with FIFO, 16-byte RX/TX buffers.
- **Baud rates:** 9600-921600 bps, configurable per instance.

### 10.1.1 RDK-RZV2H Serial Policy

| Mode | Console / Debug | Active serial links |
|---|---|---|
| Standalone CR8-0 NuttX | SCI4 shell + RTT diagnostics | SCI4 for the shell, RTT for boot/syslog/debug |
| Standalone CR8-1 target | SCI5 shell + RTT diagnostics | SCI5 intended for the IO target shell; not yet hardware validated |
| Standalone CM33 target | SCI9 shell + RTT diagnostics | SCI9 intended for the IO target shell; not yet hardware validated |
| Integrated PX4 CR8-0 | RTT0 console/debug | SCI4 LiDAR, SCI5 MAVLink/QGroundControl, SCI6 RC 100000 8E2 + inversion, SCI9 GPS 115200 8N1 |

SCI3 is not an active console on the RDK-RZV2H board.

### 10.2 Typical PX4 Device Assignment

| Device | Typical assignment |
|---|---|
| `/dev/ttyS4` | TFmini rangefinder |
| `/dev/ttyS5` | Sik telemetry, MAVLink to QGroundControl |
| `/dev/ttyS6` | RC input, FS-A8S SBUS, 100000 8E2; termios path build-clean; fixed external NPN inversion and frames require target proof |
| `/dev/ttyS9` | GPS, u-blox M10, 115200 8N1 |

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_lowputc.c`

### PX4/NuttX Development Notes

- Validate the selected mode's console/debug route first, then its
  telemetry/GPS/RC/sensor UARTs.
- If baud rate is wrong, check CPG clock configuration before changing UART driver logic.
- Keep `/dev/ttyS*` mapping consistent with PX4 board configuration and startup scripts.

---

## 11. SPI and I2C

### 11.1 SPI-B: Renesas SPI

- **Type:** SPI master/slave.
- **SoC count:** Three SPI-B instances, SPI0 through SPI2.
- **RDK-RZ/V2H routing:** SPI0 is the only board-routed instance identified
  by the current source and pinmap. Schematic and target proof remain pending.
  SPI1 has no external pinmux or chip-select contract; SPI2 has no NuttX
  lower-half implementation.
- **Use:** Current board configuration assigns SPI0 to the MPU9250 path.
  Internal controller loopback is used for bring-up tests and does not
  validate external routing or the sensor.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_spi.c`

### 11.2 RIIC: Renesas I2C

- **Type:** I2C master/slave.
- **Count:** 3 instances, I2C0, I2C1, I2C7.
- **Speed:** Standard 100 kHz, Fast 400 kHz, Fast+ 1 MHz.
- **Use:** Barometer, BMP280, sensor probing.

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_i2c.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_sci_i2c.c`

### PX4/NuttX Development Notes

- Validate pinmux, clock, reset, chip select, bus speed, and interrupt/DMA configuration separately.
- For SPI sensors, confirm mode, frequency, chip-select timing, and MISO/MOSI signal integrity with a logic analyzer.
- For I2C sensors, confirm bus pull-ups, voltage level, address, clock rate, and timeout handling.

---

## 12. Boot Flow: SPL to PX4 Firmware

```text
Hardware Reset, cold start
  |
  v
SPL / ROM loader @ 0x00000000
  - Check XSPI for signed image
  - Copy image to SRAM
  - Jump to 0x0000
  |
  v
NuttX bootloader, rzv_start.c
  - CPU initialization and VBAR setup
  - Clock setup
  - Memory setup
  - Jump to NuttX OS
  |
  v
NuttX kernel
  - Task scheduler
  - Driver initialization
  - uORB initialization
  |
  v
PX4 flight stack
  - PX4 modules start
  - Sensors are probed
  - MAVLink becomes active
```

**Linker script:**

- `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld`

**Key files:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_start.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c`

### PX4/NuttX Development Notes

- Boot issues should be isolated in this order: switch/mode pins, reset state, boot source, image placement, vector table, clock setup, memory setup, console output, NuttX scheduler, PX4 startup.
- Keep early boot logs minimal and deterministic.
- Validate reset vector and linker placement before investigating application-level PX4 issues.

---

## 13. Safety and Watchdog

### 13.1 POEG: Port Output Enable for GPT

POEG provides a safety interlock for PWM outputs.

- Used for fail-safe GPIO drive.
- Triggered by watchdog or external signal.
- Used for motor kill-switch behavior.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_poeg.c`

### 13.2 WDT: Watchdog Timer

- **Type:** 16-bit counter.
- Requires periodic reset to prevent reboot.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_wdt.c`

### PX4/NuttX Development Notes

- Do not enable destructive PWM or actuator output paths until POEG and required reset/boot/disarm/process-failure behavior is understood.
- The checked-in drone reference has no active WDT driver. Keep PX4 WDT integration post-G9/non-gating; validate the standalone sample separately.
- For first-run PX4 actuator testing, confirm safe default output state during reset, boot, crash, disarm, and emergency kill.

---

## 14. PX4/NuttX Bring-Up Checklist

Use this checklist as a practical board-port validation flow.

### 14.1 Board Mode and Boot

- [ ] Confirm DSW1 switch positions.
- [ ] Confirm boot source: SD, eMMC, xSPI, or SCIF download.
- [ ] Confirm normal/JTAG mode.
- [ ] Confirm reset pin and reset release behavior.
- [ ] Confirm boot image placement and reset vector.

### 14.2 Early NuttX

- [ ] Confirm `rzv_start.c` is reached.
- [ ] Confirm VBAR setup.
- [ ] Confirm CPG initialization.
- [ ] Confirm linker script memory placement.
- [ ] Confirm console UART output.

### 14.3 Kernel and Timing

- [ ] Confirm NuttX scheduler starts.
- [ ] Confirm GTM/HRT initialization.
- [ ] Confirm timer interrupt behavior.
- [ ] Confirm work queue timing.

### 14.4 Peripheral Bring-Up

- [ ] GPIO pinmux and direction.
- [ ] ICU and GIC routing.
- [ ] UART console/debug/telemetry/GPS/RC mapping.
- [ ] SPI sensor bus and chip select timing.
- [ ] I2C sensor bus and pull-up/address validation.
- [ ] DMA channel allocation and cache maintenance.

### 14.5 PX4 Integration

- [ ] uORB initialization.
- [ ] PX4 module startup.
- [ ] Sensor probing.
- [ ] MAVLink startup.
- [ ] PWM output using GPT.
- [ ] Required safety path using POEG and safe GPT states.
- [ ] Optional post-G9 WDT integration.

---

## 15. Key Source Files

| Area | File |
|---|---|
| Clock / CPG | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c` |
| Boot / CPU init | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_start.c` |
| Linker script | `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld` |
| GIC register definitions | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gic.h` |
| ICU | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_icu.c` |
| GPIO | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c` |
| Pinmap | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_pinmap.h` |
| DMAC-B | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.c` |
| MHU low-level driver | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_mhu_core.c` |
| IPCC driver | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ipc_ipcc.c` |
| PX4IO bridge reference | `boards/renesas/rdk-rzv2h/px4io_cr8_0/uorb_bridge.cpp` |
| GPT | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c` |
| GTM | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gtm.c` |
| HRT | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_hrt.c` |
| Serial | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c` |
| Early serial | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_lowputc.c` |
| SPI | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_spi.c` |
| I2C | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_i2c.c` |
| SCI-based I2C | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_sci_i2c.c` |
| POEG | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_poeg.c` |
| Watchdog | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_wdt.c` |

---

## 16. Related Documentation

- `boards/renesas/rdk-rzv2h/src/pinout.md` - board pinout and wiring authority.
- `pinmap.md` - pinmap authority.
- `../system-architecture.md` - system architecture.

---

## 17. High-Risk Validation Points

- **Clock correctness:** CPG dividers must match FSP-generated values. Incorrect clocks can break all bus timing.
- **Memory layout:** Shared DRAM at `0x40000000` must account for IPC buffers and secondary-core firmware if used.
- **Interrupt routing:** GIC/ICU wiring must be cross-checked against FSP configuration and board pinout.
- **Register view:** Register addresses assume CR8-0 view. CR8-1 and CM33 may have offset views depending on the memory map.
- **Boot mode:** DSW1 and mode pin configuration must match the intended boot/debug path.
- **PX4 timing:** GTM/HRT correctness must be proven before relying on scheduler, work queues, sensor timing, or actuator timing.
- **PWM safety:** GPT/POEG/watchdog behavior must be validated before connecting real actuators.
