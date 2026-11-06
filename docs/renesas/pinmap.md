# RZ/V2H Pin Ownership Matrix

**Date:** 2026-10-21
**Status:** Profile-specific software mapping; extension target validation pending
**Reference software source:** [selected RDK configuration](../../refs/rzv2h_drone_px4-dev/configuration.xml), [reference hardware guide](../../refs/rzv2h_drone_px4-dev/docs/HARDWARE.md)

Use the selected profile's source, not a single universal sensor assignment.
Software changes, host checks and builds can proceed from the reference XML and
board sources. Generated FSP output, fitted-board identification and electrical
measurements remain target-validation tasks; see [reference sources](./reference-source-map.md).

## Sensor Wiring Profiles

| Connection | Existing native bench/default | Opt-in `drone` extension | Canonical `dualcr8` sensor profile |
|---|---|---|---|
| SPI0 P90/P91/P92 | MOSI/MISO/SCK, single MPU9250 or ICM20948 | Shared MOSI/MISO/SCK, three ICM-45686 | MOSI/MISO/SCK, one ICM-45686 |
| P93 | Single sensor CS; GPIO or hardware SSLA0 by configuration | IMU #1 CS (reference SSLA0) | Single GPIO CS, polled sensor |
| P94 | DRDY/TINT for MPU9250/GY912/simple, or exclusive button demo | IMU #2 CS (reference SSLA1); no DRDY | No sensor ownership |
| P95 | No sensor ownership in existing bench profile | IMU #3 CS (reference SSLA2); no DRDY | No sensor ownership |
| SCI7 P76/P77 | BMP280 at 0x76 or standalone BMM150 at configured address | BMM150 0x10, BMP390L via `bmp388` 0x76, INA228 0x45 | BMM150 0x10, BMP390 via `bmp388` 0x76; battery hardware unselected |

The `dualcr8` and `demo` profiles select `CONFIG_RZV2H_SPI0_SINGLE_IMU`
exclusively with the other SPI sensor layouts. `demo` uses the same SPI0/P93
wiring as `dualcr8` and the default BMP280 at 0x76 on SCI7. Its source/host contracts and firmware build
pass; fitted wiring, orientation and electrical behavior remain unqualified.

The `drone` profile selects default-off
`CONFIG_RZV2H_DRONE_SENSOR_EXTENSION`. Its native GPIO CS dispatch uses the
three actual PX4 descriptor IDs; unknown IDs deassert all CS lines, and startup
does not configure P94 as DRDY. Host routing/startup tests and the firmware
build pass; physical qualification remains open. Legacy profiles retain their
existing pin policies. Reference
`-c 1/2/3` values are logical SSL indices, not native GPIO pin selectors;
use native SPI descriptors/CLI semantics. Native polling does not require the
reference's `-P` option. Keep P94 DRDY/button images exclusive with extension
CS1 wiring.

### Physical Header Drawing

![RDK physical 40-pin connector](./rzv2h-rdk-40_pin_header_pin.png)

This retained RDK connector drawing maps SoC pads to header positions, not
sensors or firmware profiles. It labels P93 at pin 24, P94 at pin 26 and P95
at pin 12; P76/P77 at pins 3/5, with R181/R180 2.2 kΩ pull-ups to D3.3V
(see [hardware.md §6.5](./hardware.md#65-40-pin-header-i2c-sci7-p76p77)). Its Raspberry Pi alternate-function labels
(for example PCM_CLK on P95) do not override selected RZ/V2H pinmux. Verify
extension-board nets and populated revision separately before target use.

## Serial Policy

The RDK-RZV2H board does not use SCI3 as an active console. Current and target
serial roles are split by mode:

- Standalone CR8-0 NuttX: SCI5 serial shell + RTT diagnostics (SCI5 is the telemetry UART; the shell uses it only when telemetry is absent).
- Standalone CR8-1 target: SCI5 shell + RTT diagnostics, not yet hardware validated.
- Standalone CM33 target: SCI9 shell + RTT diagnostics, not yet hardware validated.
- Integrated PX4 CR8-0: RTT0 console/debug, SCI4 LiDAR, SCI5 MAVLink/QGroundControl, SCI6 RC, SCI9 GPS.

---

## Pin Numbering Convention

**Format:** `P<port><bit>` where:
- `<port>` = 0–11; hexadecimal-style aliases use `PA` and `PB` for ports 10
  and 11
- `<bit>` = 0–7 (bit position within port)

**Example:** P70 = Port 7, bit 0

**Current lower-half total:** 86 bonded pins across P0-PB, plus multiplexed
special-function selections.

---

## Active Pin Assignments (RDK-RZV2H)

Subset of pins actively used by PX4 + NuttX drivers:

| Pin | Port.Bit | Alt-Func | Peripheral | Mode | Pull | Drive | Owner File | FSP Ref |
|-----|----------|----------|-----------|------|------|-------|------------|---------|
| **P42** | 4.2 | AF=5 | CANFD CTX4 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW4, `/dev/can4`, external transceiver required |
| **P43** | 4.3 | AF=5 | CANFD CRX4 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW4 |
| **P46** | 4.6 | AF=5 | CANFD CTX5 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW5, `/dev/can5`, external transceiver required |
| **P47** | 4.7 | AF=5 | CANFD CRX5 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW5 |
| **P50** | 5.0 | AF=1 | RSCI0 TXD / SDA (I2C) | Bidirectional | External pull-up required | B01 | board.h / rzv_sci_i2c.c | Header Pin 22; ADC-I2C (SDA), potential dedicated for BMS monitor |
| **P51** | 5.1 | AF=1 | RSCI0 RXD / SCL (I2C) | Bidirectional | External pull-up required | B01 | board.h / rzv_sci_i2c.c | Header Pin 36; ADC-I2C (SCL), potential dedicated for BMS monitor |
| **P52** | 5.2 | Profile-dependent | Safety candidate not established | — | — | — | board safety (planned) | Selected reference XML uses RSCI1 TX; do not infer safety input from old labels |
| **P53** | 5.3 | AF=11 | GPT10B (PWM4) | Output | None | B01 | rzv_gpt.c | PWM |
| **P70** | 7.0 | AF=1 | RSCI4 TXD | Output | None | B01 | rzv_serial.c | TFmini TX |
| **P71** | 7.1 | AF=1 | RSCI4 RXD | Input | None | B01 | rzv_serial.c | TFmini RX |
| **P72** | 7.2 | AF=1 | RSCI5 TXD | Output | None | B01 | rzv_serial.c | Telemetry TX |
| **P73** | 7.3 | AF=1 | RSCI5 RXD | Input | None | B01 | rzv_serial.c | Telemetry RX |
| **P75** | 7.5 | AF=1 | RSCI6 RXD | Input | Noise-filter | B01 | rzv_serial.c | RC RX |
| **P76** | 7.6 | AF=1 | RSCI7 SDA (I2C) | Bidirectional | External pull-up; noise filter on | B01 | rzv_sci_i2c.c | Header Pin 3; sensors selected by profile above |
| **P77** | 7.7 | AF=1 | RSCI7 SCL (I2C) | Bidirectional | External pull-up; noise filter on | B01 | rzv_sci_i2c.c | Header Pin 5; sensors selected by profile above |
| **P80** | 8.0 | AF=5 | CAN1 CTX0 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Onboard CAN1, HW0, `/dev/can0` |
| **P81** | 8.1 | AF=5 | CAN1 CRX0 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Onboard CAN1, HW0 |
| **P82** | 8.2 | AF=6 | RSCI9 TXD | Output | None | B01 | rzv_serial.c | GPS TX; optional HW1 CTX1 (AF=5) when `CONFIG_RZV_CANFD1` (exclusive with SCI9) |
| **P83** | 8.3 | AF=6 | RSCI9 RXD | Input | None | B01 | rzv_serial.c | GPS RX; optional HW1 CRX1 (AF=5) when `CONFIG_RZV_CANFD1` (exclusive with SCI9) |
| **P84** | 8.4 | AF=5 | CANFD CTX2 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW2, `/dev/can2`, external transceiver required |
| **P85** | 8.5 | AF=5 | CANFD CRX2 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Optional HW2 |
| **P86** | 8.6 | AF=5 | CAN2 CTX3 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Onboard CAN2, HW3, `/dev/can1` |
| **P87** | 8.7 | AF=5 | CAN2 CRX3 | Peripheral | None | B01 | board.h / rzv2h_canfd.c | Onboard CAN2, HW3 |
| **P90** | 9.0 | AF=1 | RSPI0 MOSI | Output | None | B11 | rzv_spi.c | Shared sensor bus |
| **P91** | 9.1 | AF=1 | RSPI0 MISO | Input | None | B11 | rzv_spi.c | Shared sensor bus |
| **P92** | 9.2 | AF=1 | RSPI0 SCK | Output | None | B11 | rzv_spi.c | Shared sensor bus |
| **P93** | 9.3 | GPIO or SSLA0 mode 1 | SPI0 CS | Output, initially high | None | B11 | rzv2h_spi.c / PX4 SPI table | `CONFIG_RZV2H_SPI0_HARDWARE_SSL` selects hardware SSL in compatible samples |
| **P94** | 9.4 | Profile-dependent | DRDY/button or extension CS1 | Input or output by profile | Profile-dependent | B11 | board GPIO/SPI table | Mutually exclusive roles; selected reference XML uses SSLA1 |
| **P95** | 9.5 | Profile-dependent | Extension CS2 | Output in extension profile | None | B11 | opt-in board SPI table | Selected reference XML uses SSLA2; inactive IMDT P36 does not apply |
| **P96** | 9.6 | AF=9 | GPT9A (PWM3) | Output | None | B01 | rzv_gpt.c | PWM |
| **P97** | 9.7 | GPIO | GPS buzzer | Output low | None | B01 | board GPIO (planned) | GPS buzzer |
| **PA2** | A.2 | GPIO | CAN1 STB1 | Output, initially high | None | B01 | board.h / rzv2h_canfd.c | High isolates, low normal |
| **PA3** | A.3 | GPIO | CAN2 STB2 | Output, initially high | None | B01 | board.h / rzv2h_canfd.c | High isolates, low normal |
| **PA4 / P10_04** | A.4 | AF=11 | GPT6A (PWM1) | Output | None | B01 | rzv_gpt.c | PWM |
| **PA6 / P10_06** | A.6 | GPIO | Safety LED | Output low | None | B01 | board GPIO (planned) | GPS safety LED |
| **PA7 / P10_07** | A.7 | AF=11 | GPT7B (PWM2) | Output | None | B01 | rzv_gpt.c | PWM |
| **PB4 / P11_04** | B.4 | GPIO | User LED0 | Output, active-high | None | B01 | board.h / led.c | Board silk LED0 (Status, GPIO_LED_1) |
| **PB5 / P11_05** | B.5 | GPIO | User LED1 | Output, active-high | None | B01 | board.h / led.c | Board silk LED1 (Armed, GPIO_LED_2) |

---

## Pin Ownership by Peripheral

### UART / Serial Communication

| SCI Channel | Pin TX | Pin RX | Pin Flow | Device | Function |
|-------------|--------|--------|----------|--------|----------|
| RSCI4 | P70 | P71 | None | TFminiPlus | LiDAR rangefinder (/dev/ttyS4) |
| RSCI5 | P72 | P73 | None | Sik Telemetry | MAVLink / QGroundControl (/dev/ttyS5) |
| RSCI6 | — | P75 | None | fs-a8s | RC input (`/dev/ttyS6`, 100000 8E2; inversion path requires target proof) |
| RSCI9 | P82 | P83 | None | u-blox M10 | GPS (`/dev/ttyS9`, 115200 8N1) |

**Limitations:** No hardware flow control (RTS/CTS) currently implemented.
Reference startup selects telemetry 115200; native default and reference hardware
guide use 57600. Configure the fitted radio explicitly without changing working
profiles. GPS remains 115200 8N1; SBUS requires the external inverter.

### SPI Bus (RSPI0)

**Speed:** Driver default 1 MHz; target ceiling unverified.
**Transfer backend:** PIO and opt-in SPI0 DMA exist in the native lower half.
Read the selected defconfig and [SPI source](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_spi.c)
for current channel allocation; neither host checks nor a build prove external
DMA transfers or CS waveforms. New multi-CS routing starts with PIO.

### I2C Buses

#### Sensor I2C (RSCI7 SCI-mode I2C)

**Pins:** P76 (SDA) / P77 (SCL) on 40-pin Header Pins 3 / 5.
**Pull-ups:** Board-level R181 / R180 2.2 kΩ pull-ups to D3.3V populated on RDK.
**Address:** BMP280 0x76 (SDO low; `bmp280` sample default, `-a 0x77` for
SDO high); BMM150 sample defaults to 0x10 with address configuration.
Extension addresses are in the profile table above. The bench GY-912 and
BMP280 modules tie SDO to GND, so every profile starts the barometer at 0x76
(the reference runtime `rcS` used 0x77 for an SDO-high module).
**Speed:** 100 kHz request (BMP280 HIL and `bmp280` sample; 97,656 Hz nominal);
400 kHz default for the BMM150 sample. Neither validated on target: the
2026-11-01 `bmp280` run got no ACK at 0x76/0x77 with pads verified.
**Module power:** Pin 1 3V3, Pin 6 GND. See [bmp280-i2c-validation.md](./validation/bmp280-i2c-validation.md)
and [bmm150-i2c-validation.md](./validation/bmm150-i2c-validation.md).
**DMA:** Disabled (PIO mode).

#### ADC-I2C / BMS Monitor Bus (RSCI0 SCI-mode I2C)

**Pins:** P50 (TXD0 Mode 1 -> SDA) / P51 (RXD0 Mode 1 -> SCL) on 40-pin Header Pins 22 / 36.
**Pull-ups:** **No** onboard pull-up resistors on RDK; external module or carrier must supply pull-ups to 3.3V.
**Device path:** Registered as `/dev/i2c10` (SCI bus offset 10).
**Role:** Used for external ADC-I2C (e.g. ADS1115 via standalone `ads1115` defconfig) and potential dedicated interface for BMS monitor (Battery Management System / battery voltage & current sensing).
**DMA:** Disabled (PIO mode).

### PWM / GPT Outputs (ESC Control)

| PX4 Channel (0-based) | GPIO / AF | GPT Timer | Output | Motor / ESC (1-based) | Header Pin |
|-----------------------|-----------|-----------|--------|-----------------------|------------|
| PWM0 (CH0) | PA4 / P10_04 | GPT6A  | GTIOC6A  | Motor 1 / ESC1 (front-right) | Pin 32 (GPIO12/PWM0) |
| PWM1 (CH1) | PA7 / P10_07 | GPT7B  | GTIOC7B  | Motor 2 / ESC2 (rear-left)   | Pin 33 (GPIO13/PWM1) |
| PWM2 (CH2) | P96 / P9_06  | GPT9A  | GTIOC9A  | Motor 3 / ESC3 (front-left)  | Pin 35 (GPIO19)      |
| PWM3 (CH3) | P53 / P5_03  | GPT10B | GTIOC10B | Motor 4 / ESC4 (rear-right)  | Pin 31 (GPIO06)      |

**Frequency:** Configurable (typically 400 Hz for ESC).
**Duty Cycle:** 1000–2000 µs (1–2 ms pulse width).
**Source:** [rzv_gpt.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c), [timer_config.cpp](../../boards/renesas/rdk-rzv2h/src/timer_config.cpp)

### GPIO / Interrupts

Use the active assignment table for P94's exclusive roles and the unqualified
P52/P97/PA6 safety and indication candidates.

**Pull-ups/Pull-downs:** P76/P77 require external I2C pull-ups; confirm the populated board value before timing validation.

---

## Additional Ownership

Do not infer availability from absence in the sensor table. Check bonded-pad
definitions, selected native board configuration, reference XML and any CA55
device tree before adding an owner. Reference SPI comments retire the former
P50/PA0/P74 DRDY pads and identify debug-UART/SDHI uses; they are not spare
interrupt inputs. P80/P81 are onboard CAN1/HW0 and P86/P87 are onboard CAN2/HW3, with
PA2/PA3 standby control. P82/P83 are exclusive SCI9 GPS or optional CANFD
HW1 expansion selections. HW3 retains `/dev/can1`/FIFO1; HW1 uses `/dev/can3`/FIFO3 when HW3 is
selected, otherwise its legacy `/dev/can1`/FIFO1. HW2/P84-P85, HW4/P42-P43
and HW5/P46-P47 are opt-in expansion pad selections with external
transceiver ownership. All six may coexist when their pads are available;
these mux definitions do not prove physical connector access. See
[CAN-FD notes](peripherals/canfd.md).

---

## Cross-Check Recipe

**Verify source-backed ownership contracts:**

```bash
python3 test/rzv2h_board_gpio_contract_test.py

rg -n 'pincfg|active="true"|selected="true"' \
  refs/rzv2h_drone_px4-dev/configuration.xml

rg -n "P42|P43|P46|P47|P50|P51|P52|P53|P70|P71|P72|P73|P75|P76|P77|P80|P81|P82|P83|P84|P85|P86|P87|P90|P91|P92|P93|P94|P96|P97|PA2|PA3|PA4|PA6|PA7|PB4|PB5" \
  boards/renesas/rdk-rzv2h \
  platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h
```

Defconfigs select peripheral instances, not a complete pin list, so a
defconfig-only pin diff is not authoritative. The contract test checks the
board-owned GPIO invariants; source scans support human reconciliation. Read
only the XML's selected `RDK` set rather than merging inactive profiles.
None proves drive strength, signal integrity, connector routing, or board
population.

## Related Files

- **Hardware Guide:** [hardware.md](./hardware.md)
- **Board Config (PX4):** [../../boards/renesas/rdk-rzv2h/src/board_config.h](../../boards/renesas/rdk-rzv2h/src/board_config.h)
- **NuttX Pin Map Header:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_pinmap.h](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_pinmap.h)
- **GPIO Driver:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpio.c)
- **Reference SPI descriptors:** [reference spi.cpp](../../refs/rzv2h_drone_px4-dev/px4/boards/renesas/rzv/src/hal/spi.cpp)
- **Reference startup:** [reference rcS](../../refs/rzv2h_drone_px4-dev/px4/boards/renesas/rzv/init/rcS)

---

## Maintenance Notes

- **Per-PR Rule:** Update this table when adding new peripheral drivers or changing pin assignments.
- **Verification:** Run the cross-check recipe whenever pin or peripheral
  ownership changes.
- **Conflicts:** Reserved pins are marked with owner file; confirm in Kconfig before reassignment.

---

## Remaining Target Validation

1. No internal pull-up/pull-down contract is established in `rzv_gpio.c`; SCI7 I2C requires board-level external pull-ups.
2. SPI0 DMA is opt-in; fitted-sensor transfers and electrical timing require exact-image evidence.
3. UART flow control (RTS/CTS) not wired.
4. Secondary SPI/I2C buses not active; only RSPI0, RSCI7 in use.
5. Multiplexed pins (e.g., P50 as GPIO vs. TINT) require Kconfig guards; conflicts possible in dynamic reconfiguration.
6. Safety/button, P97 buzzer and PA6 LED ownership need generated-symbol and
   electrical confirmation. Active XML does not establish P52 as a safety input.

---
