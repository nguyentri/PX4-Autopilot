# RZ/V2H RDK Hardware Guide for PX4 NuttX Development

**Board:** Renesas RDK-RZ/V2H
**Target software stack:** PX4 on NuttX
**Primary development target:** CR8-0
**Date:** 2026-10-11
**Status:** Consolidated development reference

This document consolidates the hardware notes for the RZ/V2H RDK board into a single PX4/NuttX-focused reference. It is intended for board bring-up, driver development, boot/debug configuration, and hardware-software validation.

For sensor assignments use [profile-specific pin ownership](./pinmap.md#sensor-wiring-profiles).
The current FreeRTOS reference is `refs/rzv2h_drone_px4-dev/`: its selected
`RDK` XML and `docs/HARDWARE.md` describe three ICM-45686 IMUs on SPI0,
BMM150/BMP390L/INA228 on SCI7 I2C, and the existing serial/PWM connections.
The native extension profile is opt-in and configurable; existing native
MPU9250/BMP280, ICM20948/GY912 and SIH profiles retain their own contracts.
[Native board pinout](../../boards/renesas/rdk-rzv2h/src/pinout.md) describes
legacy bench wiring; it is not the new extension BOM.

Missing generated FSP pin data and the matching extension schematic do not
block source integration, host tests or builds. Use the selected reference
configuration provisionally, then confirm fitted parts, connector nets and
waveforms during target validation. A successful build does not qualify the
physical sensor array. See [reference provenance and limits](./reference-source-map.md#current-rdk-reference-availability).

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

The RDK uses the Renesas R9A09G057H. Core responsibilities and software
boundaries belong in [system architecture](../system-architecture.md).
CR8-0 owns primary board bring-up; optional peers require explicit peripheral,
interrupt and shared-memory ownership before being enabled.

Core frequencies depend on boot-switch and loader configuration. Record the
live clock state for timing evidence rather than assuming the nominal loader
settings.

---

## 3. Clock System: CPG

The **CPG**, or Clock Pulse Generator, controls frequency and power for processor and peripheral blocks.

### Clock authority

Use the [clock driver](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_clock.c)
and its selected BSP inputs for clock sources, module gates and divider
calculations. GPT uses P4CLK and GTM uses P1CLK; their nominal frequencies do
not prove the live loader state.

The CR8 private timer behind the NuttX tick counts at I6CLK / 4 (200 MHz with
I6CLK at 800 MHz), set by `CONFIG_RZV_CR8_PERIPHCLK_DIV`. The ratio comes
from the SoC integration, not the Cortex-R8 core: assuming CPU / 2 ran the
tick at half rate. On 2026-10-13 the corrected tick (load `0x30d3f` for
1 kHz) matched the GTM-based HRT on both CR8 cores.

Audit clock setup against selected XML and core-matched FSP/BSP sources.
Corroborate with generated output and live measurements for target timing
acceptance. Validate clocks before investigating baud, bus-rate, PWM or HRT
errors; missing generated output does not block source work or a build.

---

## 4. Memory Map: Single-Core CR8-0

The [multicore memory map](multicore-memory-map.md) owns private TCM, SRAM,
DDR, shared windows and loader aliases for every core. Compare the exact
image against the selected
[linker script](../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/scripts/rdk-rzv2h_cr8_0.ld).

Keep MMIO uncached. Reserve shared memory deliberately and state cacheability
and coherency policy before assigning a secondary core or DMA consumer.

---

## 5. Interrupt System: GIC and ICU

### 5.1 GIC: Generic Interrupt Controller

The GIC handles core interrupts from peripherals.

- **Type:** GIC-600 using the GICv2-compatible register interface.
- **Base address:** `0x12C10100`, CR8-0 physical view.
- **Interrupt count:** Read from `GICD_TYPER`/`ICDICTR` at runtime and capped
  at 1020 by the driver; do not assume a 96-SPI topology.
- **PPI interrupts:** 16 per-core local interrupts.
- **SGI interrupts:** 16 software-generated inter-processor interrupts.
- **SPI interrupts:** Remaining implemented IDs above 31, as reported by the
  controller at runtime.

Key register groups:

- `GICD_*`: Distributor, central routing.
- `GICC_*`: GICv2-compatible CPU interface and prioritization.

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_irq.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_intc_gic.h`

### 5.2 ICU: Interrupt Control Unit

The ICU routes GPIO and external interrupt pins to the GIC.

- **Type:** ICU with edge/level triggering.
- **Base address:** `0x10400000`.
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

- **Type:** RZ/V2H GPIO/PFC lower half.
- **Base address:** `0x10410020`, CR8-0 view.
- **Features:** Input, output, pull-up, pull-down, alternate functions, interrupt wiring.

### 6.2 Port Layout

- NuttX ports 0-11 map to hardware registers P20-P2B.
- Bonded pins per port: 8, 6, 2, 8, 8, 8, 8, 8, 8, 8, 8, 6.
- Total exposed by the current lower half: 86 bonded pins.

### 6.3 Alternate Functions

Each pin has alternate function options for peripherals such as UART, SPI, I2C, PWM, and other functions.

**Sources:**

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_pinmap.h`

### 6.4 Onboard CAN1 and CAN2

| RDK port | Controller channel | TX / RX (PSEL 5) | Standby GPIO | Connector |
|----------|--------------------|-----------------|--------------|-----------|
| CAN1 | HW0 | P80 / P81 | PA2 / STB1 | J2 |
| CAN2 | HW3 | P86 / P87 | PA3 / STB2 | J3 |

The supplied [RDK CAN schematic](rzv2h-rdk-canfd.png) shows a dual
TCAN1046VDMTRQ1 transceiver and split termination (two 60.4 Ω resistors per
port). Each connector uses pin 1 CANH, pin 2 CANL and pin 3 GND. For the
connected test, join J2.1↔J3.1, J2.2↔J3.2 and J2.3↔J3.3. Verify the fitted
board revision and termination before adding any external terminators.
See the [official RDK communication guide](https://renesas-rdk.github.io/rzv2h_rdk_documentation/latest/chapter-2/common_interfaces/communication_interface.html).

PA2/PA3 high selects standby; low selects normal mode. Board initialization
sets both owned standby pins high before configuring CAN pins. The driver
lowers a pin only after successful external-mode first-open setup, then
allows the 20 µs mode transition interval from the [TI datasheet](https://www.ti.com/lit/ds/symlink/tcan1046v-q1.pdf).
Loopback, failed setup, cancellation and last-close keep standby high.
Physical levels and connected-bus behavior remain target qualification gates.
P82/P83 are optional HW1 expansion pads shared with SCI9, separate from CAN2.
The driver supports all six hardware channels. Optional HW2 uses P84/P85,
HW4 P42/P43 and HW5 P46/P47 (TX/RX, PSEL5), from native SoC pin definitions.
These require external transceivers and board routing/pad ownership checks;
they are not additional onboard CAN connectors.

The dedicated connected command remains scoped to the onboard HW0/HW3 pair;
all-six support adds opt-in lower-half and board registrations without adding
a shipping all-six command profile.

Build modes and the bounded two-port command are documented in
[CAN-FD peripheral notes](peripherals/canfd.md).

### PX4/NuttX Development Notes

- Treat `pinmap.md` as the software assignment matrix. Confirm external wiring
  against the board pinout/schematic and target measurements.
- Validate pinmux configuration early for console UART, debug UART, sensor buses, PWM outputs, and external interrupts.
- Use a board-level pinout document to avoid conflicts between PX4 sensor, telemetry, RC, GPS, and actuator functions.

---

## 7. DMA Controller: DMAC-B

DMAC-B provides high-bandwidth DMA for bulk transfers.

- **Type:** Renesas DMAC-B.
- **Topology:** Five units, two groups per unit, eight channels per group;
  80 global channels numbered 0-79.
- **Unit bases:** `0x11400000`, `0x14830000`, `0x14840000`,
  `0x12000000`, and `0x12010000`.

Features:

- 32-bit, 16-bit, and 8-bit transfer modes.
- Software-triggered one-shot memory copies.
- INTC-routed, hardware-triggered one-shot memory-to-peripheral transfers.
- CPU-address conversion for the CR8-0 ITCM/DTCM bus aliases.

Configuration:

- Channels are assigned per consumer in Kconfig; there is no dynamic allocator.
- Setup is handled in `rzv_dmac.c`; current consumers include serial and the
  opt-in DShot and SPI0 DMA paths. Read consumer Kconfig/defconfig channel
  selections before allocating a channel; do not reuse historical allocations.
- Completion is polling-only. Callbacks and linked-list mode are unsupported.
- `rzv_dmac_config_s.src_prot` and `dst_prot` select the read/write AXI
  protection attributes in CHEXT (three bits each). Zero preserves secure,
  unprivileged data access. The legacy `priority` field must be zero;
  nonzero priorities are unsupported, rather than changing access protection.
  SYS master overrides and slave security controls remain board policy.
- With `CONFIG_DEBUG_DMA_ERROR`, the first enable/stop failure per channel
  configuration dumps unit/group/channel identity, descriptor/current addresses,
  byte counts, CHSTAT/DSTAT_ER, CHCFG/CHEXT and DCTRL before reset. Retained
  rearm does not repeat the dump; release/configure permits a fresh report.
  Keep this error hook within the initialized DMAC unit: SYS/security reads
  caused a target abort. Inspect global registers separately with the debugger;
  `0xaaaaaaaa` is not a valid policy measurement.
- New configuration rejects enabled/bus-active hardware and resets stale status
  only on an inactive channel. Software transfers clear their channel's old
  activation route. Hardware transfers disable route auto-clear, restore the
  selected source before each arm and verify writes; a rejected route returns
  `-EIO`. Neighboring channel selections are preserved.
- Shared PX4 `nsh` assigns DShot to DMAC3 channels 56–59, separate from SPI0's
  48/49 allocation. The named [CR8-0 repair run](evidence/dshot-dmac-cr8-0-validation-261020.md)
  completes four DShot600 motor-stop frames, including module restart, with
  128 bytes consumed per channel. The same driver passes 26 memory-copy
  comparisons across both groups of all five units. These are bounded runs;
  electrical waveforms, nonzero throttle and ESC response remain unqualified.
- DShot latches its HAL output state off after a frame/start failure until
  explicit recovery. It logs the first complete frame once per initialization.
  Flight arming is separate from this HAL state.

Renesas's [public hardware manual](https://www.renesas.com/en/document/mah/rzv2h-group-users-manual-hardware),
R01UH1032EJ0140, defines CHEXT protection in §4.7.5.2.14 and ICU_BEISR0–3
at offsets `0x70..0x7c` in §4.6.1.2.2(15). Table 1.7-1 lists GPT access
from all five DMAC units. A DMAC0 GPT write-bus error and the older SPI
observations do not establish a universal bus-topology restriction.
§4.6.1.2.2(32) defines request selection/CLRON and prohibits duplicate event
assignments. When changing DMA units between RAM images, release the old
image's owned routes first; stopping outputs retains its DMA configuration.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.c`

### PX4/NuttX Development Notes

- Use DMA for high-throughput or low-latency sensor, storage, and communication paths only after polling/interrupt bring-up is stable.
- Verify buffer alignment, cache maintenance, descriptor ownership, and completion interrupts.
- Avoid silent channel conflicts by keeping Kconfig channel allocation explicit.

---

## 8. Inter-Core Communication: MHU and IPCC

MHU signals an event; the payload lives in shared memory. The
[IPC architecture](ipc-architecture.md) owns transport separation, protocol
sources and peer qualification. The [memory map](multicore-memory-map.md)
owns per-core aliases. Sensor-profile changes do not alter that contract.

A standalone raw-link result cannot qualify the PX4 bridge, CM33, or the
reference CA55 RPMsg/RPC service. Define peer reset/recovery and buffer
ownership for each selected profile.

---

## 9. Timers

### 9.1 GPT: General PWM Timer

- **Type:** 32-bit PWM timers.
- **Count:** 16 logical channels, GPT0-GPT15.
- **Register mapping:** logical GPT0-GPT7 map to physical R_GPT0-R_GPT7;
  logical GPT8-GPT15 map to physical R_GPT10-R_GPT17.
- **Modes:** PWM, input capture, compare match.
- **Clock:** runtime P4CLK; nominal 200 MHz on the checked-in CR8_0 setup.
- **Duty precision:** 32-bit period/compare registers.
- **PX4 use:** ESC motor-control PWM output.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c`

### 9.2 GTM: General Timer Module

- **Type:** 32-bit free-running counter.
- **HRT instance:** one GTM per PX4 core, chosen by the NuttX Kconfig choice
  `RZV_HRT_GTM6`/`RZV_HRT_GTM7`. GTM channels are shared by all cores. CR8-0 uses
  GTM7 at `0x12C03000` (the default), and the CR8-1 IO image uses GTM6 at
  `0x12C02000`.
- **Clock:** runtime P1CLK; 100 MHz nominal in the checked-in CR8-0 setup.
- **Counter:** 32-bit, nominal full wrap approximately 42.9 seconds at 100 MHz;
  the HRT shim uses bounded comparisons and a software epoch.
- **PX4 use:** High-resolution timer, HRT, for scheduling.
- **Interrupt:** the fixed compare IRQ of the selected GTM (`RZV_IRQ_GTM7` or
  `RZV_IRQ_GTM6`).

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

The [pin ownership matrix](pinmap.md#serial-policy) owns console and payload
assignments, device names and wiring. The
[deployment guide](../deployment-guide.md) owns console connection procedures.
SCI-B and SCIF/SCIFA are different controllers; select the matching
[reference source](reference-source-map.md#uart-distinction).

Validate the selected profile's console first, then payload UARTs. Check the
CPG clock when baud is wrong and retain the board's physical SCI numbering.

---

## 11. SPI and I2C

Use [sensor wiring profiles](pinmap.md#sensor-wiring-profiles) for buses,
addresses and chip selects. RSPI is distinct from the EVK SPI-B controller;
SCI7 simple-I2C is distinct from native RIIC. The
[reference map](reference-source-map.md#known-reference-gaps) records which
inputs can establish each controller's behavior.

- SPI: validate mode, clock, chip-select timing and signal integrity with the
  fitted sensor. Internal loopback cannot establish external wiring.
- I2C: confirm pull-ups, voltage, strapped address, repeated START and timeout
  recovery. Preserve each standalone sample's timing and address choices.
- DMA and hardware chip select are separately selected paths; source/build
  checks do not prove their electrical timing.

Per-device procedures are linked from the [validation index](README.md).

---

## 12. Boot Flow: SPL to PX4 Firmware

```text
Hardware Reset, cold start
  |
  v
External boot stage / loader (exact production route not yet proven)
  - Consume the Renesas image load descriptors
  - Place ITCM, SRAM, and DDR segments at their linked addresses
  - Transfer control to local ITCM address 0x00000000
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
  |
  v
PX4 flight stack
  - uORB initialization
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

POEG provides an optional hardware safety interlock for PWM outputs. It is not
required by the current GPT/PWM driver scope.

- Used for fail-safe GPIO drive.
- Triggered by watchdog or external signal.
- Used for motor kill-switch behavior.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_poeg.c`

### 13.2 WDT: Watchdog Timer

- **Type:** 16-bit counter.
- Requires periodic reset to prevent reboot.

**Source:** `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_wdt.c`

### PX4/NuttX Development Notes

- Validate reset, boot, disarm, process-failure, and inactive-output behavior
  before actuator tests. Add POEG only if the product safety design requires a
  hardware fault interlock.
- The checked-in drone reference has no active WDT driver. Keep PX4 WDT integration post-G9/non-gating; validate the standalone sample separately.
- For first-run PX4 actuator testing, confirm safe default output state during reset, boot, crash, disarm, and emergency kill.

---

## 14. PX4/NuttX Bring-Up Checklist

Use the [validation checklist](validation/validation-checklist.md) for source, build,
interrupt, DMA, concurrency and target-evidence gates. Select a device-specific
procedure from the [port index](README.md) for actual measurements.

Isolate board failures in this order: switch/mode pins, reset, boot source,
image placement, vectors, clocks, memory, console, scheduler, then PX4 startup.
Exact-image boot provenance and safe inactive actuator outputs remain required.

## 15. Key Source Files

The [codebase map](../codebase-summary.md) owns source navigation; the
[NuttX status matrix](port-status-nuttx.md) owns per-driver source and evidence.
Use their links instead of a second driver inventory.

---

## 16. Related Documentation

- [Native bench pinout](../../boards/renesas/rdk-rzv2h/src/pinout.md) - legacy wiring.
- [Pin ownership](./pinmap.md) - native and opt-in extension profiles, physical header drawing.
- [System architecture](../system-architecture.md) - software boundaries.

---

## 17. High-Risk Validation Points

- **Clock correctness:** Cross-check selected FSP/BSP configuration and live clocks.
  Generated output is corroboration for target timing, not a software-build gate.
- **Memory layout:** Shared DRAM at `0x40000000` must account for IPC buffers and secondary-core firmware if used.
- **Interrupt routing:** GIC/ICU wiring must be cross-checked against FSP configuration and board pinout.
- **Register view:** Register addresses assume CR8-0 view. CR8-1 and CM33 may have offset views depending on the memory map.
- **Boot mode:** DSW1 and mode pin configuration must match the intended boot/debug path.
- **PX4 timing:** GTM/HRT correctness must be proven before relying on scheduler, work queues, sensor timing, or actuator timing.
- **PWM safety:** GPT reset/boot/disarm/failure behavior must be validated
  before connecting real actuators; validate POEG/watchdog only when selected
  by the product safety design.
