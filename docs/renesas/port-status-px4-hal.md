# PX4 HAL Port Status Matrix

**Date:** 2026-08-09
**Branch:** gitlab-migration
**Scope:** PX4 Hardware Abstraction Layer (HAL) surfaces for RDK-RZ/V2H; cross-referenced to NuttX driver dependencies.

---

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **build-clean**: HAL adapter implemented and wired into its named board target; compiles/links. No on-target hardware validation yet.
- **deferred**: HAL adapter present but the feature is intentionally disabled in the default build pending hardware enablement (documented in board defconfig).
- **validated**: On-target integration tests pass; used in application code.

> Evidence note: the standalone CR8-0 `nsh-rtt` sample has on-target SCI4
> shell/IRQ and RTT diagnostic evidence. The integrated PX4 target remains
> unvalidated: no PX4 HAL surface has reached **validated** on target.
> `build-clean` is therefore the strongest integrated-HAL tier currently
> supported. The 2026-07-26 software checkpoint is source-backed rather than
> target-backed and remains build-clean only; no target-boot claim is made.
> Board defaults now set `SYS_AUTOSTART=4014`/`4014_s500`,
> `SENS_TFMINI_CFG=401`, `SER_EXT2_BAUD=115200`, `BAT1_SOURCE=-1`, and
> `DSHOT_START` controls the shared DShot startup split. The RDK payload
> images (`renesas_rdk-rzv2h_default` and `renesas_rdk-rzv2h_dshot`) omit the
> `tone_alarm` module/command; `rc.board_defaults.cmds` sets
> `TONE_ALARM_START=no` before the common guarded call in `rcS`, while other
> boards keep the common `yes` default. `battery_status` remains source-gated
> on BAT1/BAT2 power-module sources.

> The 2026-08-02 payload-image rebuilds also close deterministic startup
> command and MAVLink-shell defects. Required `mft`/`bsondump` commands are
> linked; absent RGBLED/PX4IO probes are disabled by board capability flags;
> `CONFIG_PIPES=y` selects NuttX `lib_pipe.o` instead of a board `ENOSYS`
> stub. An automatic post-build contract verifies both default and DShot
> label/nsh/CR8-0 resolution, linker, builtins, pipe object, undefined-symbol
> set, split image, `.px4` payload, reset configuration, and reset symbols.
> Every board build also runs the focused GPIO, GPT/PWM, GTM, SCI/SPI,
> OneShot/DShot, and SIH source contracts. Current ELF SHA-256 values are
> default `6394a28f2c628737add5cf5ef4a195160aec34e0cdd2bd9559ee6f52f375e923`,
> DShot `6d81d2548b726ee79d58b9a0e8fb21c6e95c7aaf4db5c6281f3183b88e89a222`,
> SIH `214c0898b23680468cb9cff7710928be501f83c951817415e9fb17d608ab6248`,
> and core-only `bea463585efc0f68a11800dec6d53aab5b10a2b6ccebcc2873e7166b5f609302`.
> `board_reset()` is now wired through NuttX `up_systemreset()` to the CR8
> WDT2/WDT3 reset route, and `board_on_reset()` disconnects all four motor
> pins before a normal reset. All four ELFs contain the complete reset symbol
> chain. Exact-image cold boot, reset occurrence, post-reset startup, and
> inactive motor-pin scope proof remain target gates.

SIH note: `renesas_rdk-rzv2h_sih` now has bounded on-target evidence for its
simulation-only contract. It is a CR8-0 FC-SIH demo image, not a physical
hardware proof image. Startup loads
`sensors start -h`, `simulator_sih`, `sensor_baro_sim`, `sensor_mag_sim`,
`sensor_gps_sim`, and `pwm_out_sim start -m hil`; `control_allocator` is
linked for metadata but is not started. The image reports simulated
accel/gyro/baro/mag/GPS data, keeps physical payload/sensor buses and GPT/PWM
drivers off, and leaves queue count timing-dependent. The July 30 transcript
self-reports the current PX4/NuttX revisions, reaches an interactive NSH shell,
passes one `system_time hrt-test`, shows expected queues and simulated topics,
and reports the HIL endpoint running. It records no artifact hash, so it is not
attributed to the fresh SIH ELF
`214c0898b23680468cb9cff7710928be501f83c951817415e9fb17d608ab6248`.
Fresh SIH builds run the source and artifact contracts automatically
(11/11 + 12/12), and mandatory startup failures now terminate `rcS` instead
of falling through to a misleading success path. Exact load/cold-cycle provenance, SCI4 transport capture,
physical pin-safety measurements, transcript coverage gaps, and the 10-minute
resource/rate soak remain pending. See the
[archived target transcript](px4_nuttx_rzv2h_sil.txt); its historical
filename says `sil`, but the image/runtime variant is SIH. The goal-plan
evidence audit records the detailed provenance limits for the next authorized
target session.

Core-only note: `renesas_rdk-rzv2h_core_only` is build-clean from
`core_only.px4board`, `nuttx-config/core_only/defconfig`, and the generated
`ROMFS/rdk-rzv2h-core-only` tree. It retains RTT/HRT/params/uORB and the
diagnostic commands used to inspect failures, auto-starts `pwm_out`, and keeps
output disabled until an explicit actuator command is issued. The image
excludes payload lower-halves, sensors, flight-module startup, serial consumers,
and `serial_status`. `control_allocator` remains linked only because the
actuator metadata generator needs the mixer schema. Work queues are lazy:
PWMOut starts on `wq:hp_default` and can migrate its motor subscription to
`wq:rate_ctrl`, so immediate and settled listings can differ. Neither should
match RA8P1's larger sensor/controller/serial queue footprint. No hardware
proof is claimed for that image.

SIH demo shell contract:

```text
ver all
ps
top once
work_queue status
system_time hrt-test
listener sensor_accel -n 5
listener sensor_gyro -n 5
listener sensor_baro -n 5
listener sensor_mag -n 5
listener sensor_gps -n 5
pwm_out_sim status
free
perf
```

Use the commands above to finish the SIH startup and queue evidence. The
current transcript is a bounded runtime pass, not completion of the cold-cycle,
pin-safety, or soak gates, and it gives no evidence for physical sensors,
payload links, flight readiness, or GPT/PWM output.

The execution authority is the
[RDK-RZV2H PX4 NuttX Port Goal Plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md).
CR8-0 is the only critical path. CR8-1, CM33, OpenAMP, and remoteproc are final
milestone work.

Reference provenance follows the
[RZ/V2H Reference Source Map](reference-source-map.md). In particular,
SCI-B serial is distinct from SCIF/SCIFA, and Ethernet has no per-core EVK
FSP example.

---

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `micro_hal/micro_hal.cpp` (`px4_spibus_initialize`) | `rzv_spi.c` + board IOPORT/PFC mux + GPIO CS | boards/renesas/rdk-rzv2h/src/spi.cpp | build-clean; target pending | `CONFIG_RZV_SPI=y`. `board_app_initialize()` now calls `board_spi_initialize()` before sensor startup, which muxes P90/P91/P92 and configures P93 as active-low GPIO CS. The board select hook keys on the SPI0 lower-half instance, so PX4 sensor IDs and standalone NuttX test IDs share the same CS path. Initialization and standalone registration retry state are serialized/published safely. [Software checkpoint](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/pm-260727-0701-rzv2h-integrated-spi-closure.md). DRDY is P50. On-target WHOAMI/data/DRDY proof pending. |
| 2 | I2C | `micro_hal/micro_hal.cpp` (`px4_i2cbus_initialize`) | rzv_sci_i2c.c (`rzv_sci_i2c_initialize`, SCI-mode) | boards/renesas/rdk-rzv2h/src/i2c.cpp | build-clean | BMP280 baro on SCI7 simple-I2C P76/P77. `CONFIG_RZV_SCI7_I2C=y`; bus 7 dispatches explicitly to `rzv_sci_i2c_initialize(7)`, never RIIC, and maps safely to its dense PX4 clock slot. Fresh standalone HIL and integrated PX4 builds pass; BMP280 probe/read/recovery remains unvalidated on target. |
| 3 | UART/Serial | NuttX serial (native) | `rzv_serial.c` SCI-B lower halves; SCIF is separate sample-only path | boards/renesas/rdk-rzv2h/ | in-progress | Core-matched `rzv2h_evk/sci_b_uart` projects are the SCI-B reference. Explicit policy: standalone CR8-0 NuttX = SCI4 shell + RTT diagnostics; target CR8-1 = SCI5 shell + RTT diagnostics; target CM33 = SCI9 shell + RTT diagnostics. Integrated PX4 RTT0 `/dev/console` is build-clean and bypasses SCI low-setup. SCI4/5/6/9 retain payload ownership in the full image. SCIF/SCIFA has no EVK application example and remains sample-only/blocked. |
| 4 | GPIO | `include/px4_arch/micro_hal.h` (macros → `rzv_gpio*`) | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | build-clean | Port I/O + IRQ/edge via rzv_gpiosetevent. On-target IRQ latency pending |
| 5 | PWM/ESC | `io_pins/io_timer.c` + `pwm_servo.c` | direct GPT MMIO; standalone `rzv_gpt.c` lower-half is mutually exclusive | boards/renesas/rdk-rzv2h/src/timer_config.cpp | build-clean | FSP logical mapping: GPT6A/7B/9A/10B on PA4/PA7/P96/P53; logical 9/10 resolve to physical R_GPT11/R_GPT12. Live rate/duty changes use GPT buffers, stopped/disabled paths clear the counter, first setup performs the GTUDDTYC UDF latch, compare values use counts−1, and partial timer/GPIO initialization unwinds. The board-scoped PX4 path disables motor GTIOC on `stop_motors`, validates allocation ownership, and safely reallocates after module restart without stealing DShot ownership. Before a normal reset, `board_on_reset()` unconfigures PA4/PA7/P96/P53 and waits 6 ms; the WDT-backed reset chain is build-verified in all four board ELFs. The default PX4 board path exposes analog PWM only and rejects `PWM_MAIN_TIMx=-1`; internal OneShot ownership plumbing has no board trigger path. Standalone NuttX finite pulse-count PWM is separate. The core-only demo auto-starts `pwm_out`, prints `work_queue status`, and uses `actuator_test set -m 1 -v 0 -t 5` for a bounded 1100 µs Motor 1 bench waveform. Integrated and standalone PWM builds plus source-contract regressions pass. Waveform, inactive-level, transition, reset, and failsafe scope proof pending. |
| 5b | DShot (GPT+DMA) | `dshot/dshot.c` + `dshot/dshot_telemetry.c` | rzv_dmac.c (HW-trigger) + rzv_gpt.c | boards/renesas/rdk-rzv2h/dshot.px4board | build-clean (opt-in) | TX-only target `renesas_rdk-rzv2h_dshot` builds and links; default remains PWM and excludes DShot. The DShot image includes `pwm_out` as the standard provider of shared `PWM_MAIN` parameters, but runtime `PWM_MAIN_TIM0..3=-3` leaves every group to DShot and the DShot build omits the analog-only complete-init requirement. Shared board defaults set `DSHOT_START` from the silent `DSHOT_MIN` probe, so common startup only calls `dshot start` for the opt-in image. Checked-in CMSIS/FSP sources verify DMkSEL offsets, unit mapping, and GPT-overflow DMAC activation IDs. GPT buffered compare + one-shot DMA path is not hardware-validated. BDShot capture/telemetry returns `-ENOTSUP`; the pure GCR/eRPM decoder is not a functional telemetry path. Waveform, transfer ordering, repeated trigger/re-arm, and ESC tests remain pending. |
| 6 | ADC | `adc/adc.cpp` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | deferred/non-gating | Core-matched `rzv2h_evk/adc_e` projects provide FSP driver/config evidence, but the integrated drone reference still has no active ADC consumer. The NuttX byte-width defect and target conversion/pin proof remain open; post-G9. |
| 7 | Timer/HRT | `hrt/hrt.c` (queue mgr) → `rzv_hrt_*` | rzv_hrt.c (GTM7 free-run) | boards/renesas/rdk-rzv2h/src/ | build-clean; target pending | `CONFIG_RZV_HRT=y`; GTM7 ownership is clean and stale GTM0/120 MHz declarations are removed. A bounded free-run compare maintains the 64-bit epoch; cancel/rearm preserves elapsed ticks; long deadlines use intermediate wakeups; mandatory initialization/arm failures fail visibly; periodic self-delay/self-cancel matches the PX4 contract. Integrated build and source review pass. Runtime P1CLK, wrap monotonicity, jitter, and soak proof remain target gates. |
| 8 | CAN | `src/drivers/can/` | rzv_canfd.c | boards/renesas/rdk-rzv2h/src/ | planned | CAN0/CAN1; baud rate; SLCAN over UART alt |
| 9 | Ether/MAVLink UDP | `src/modules/mavlink/` + network stack | rzv_ether.c + rzv_ether_phy.c | boards/renesas/rdk-rzv2h/src/ | planned | No per-core EVK FSP example. Legacy CA55 GBETH/PHY sources are secondary evidence only; descriptor, clock, pinmux, IRQ, link, MDIO, and traffic gates remain. |
| 10 | xSPI/LittleFS | PX4 parameter backend + NuttX LittleFS | `rzv2h_xspi_paramfs.c` board MTD/mount path | boards/renesas/rdk-rzv2h/src/ | blocked; volatile fallback build-clean | Default mounts TMPFS at `/fs` and uses `/fs/params` without touching flash. Experimental xSPI is disabled: controller init, flash/partition manifest, MPU/cache handling, erase/program/readback, reboot persistence, and power-loss recovery remain unproven. Keep separate from SDHI `/dev/mmcsd0` ULog storage. |
| 11 | Board identity | `board_get_uuid()` / `board_get_px4_guid()` | board identity provider | boards/renesas/rdk-rzv2h/src/ | blocked for multi-device deployment | `BOARD_OVERRIDE_UUID` is fixed to `RZV2H0000000000`, and the RZ/V2H GUID provider is derived from fixed architecture/board text. The checked-in FSP evidence says unique-ID support is unavailable. This is acceptable only for a declared single-prototype workflow; fleet use, identity-sensitive pairing, and per-device calibration require an approved provisioning source and persistence design. |

---

## Detailed Migration Notes by Peripheral

### SPI (Line 1)

**NuttX Foundation:** `rzv_spi.c` (RSPI native) + `rzv_sci_spi.c` (SCI as SPI fallback).

**PX4 HAL Interface:**
- `board_spi_initialize()` configures the SPI0 IOPORT/PFC mux and P93 GPIO CS, then
  initializes the RZ/V2H lower-half before payload startup.
- Later `px4_spibus_initialize()` calls from PX4 sensor drivers reuse the
  idempotent `rzv_spibus_initialize()` result (`CONFIG_RZV_SPI=y`).
- Bus/device table in `boards/renesas/rdk-rzv2h/src/spi.cpp` (`px4_spi_buses`).
- CS control: the NuttX board select hook drives the SSLA0-capable P93 pin as
  an active-low GPIO. It identifies the physical SPI0 instance rather than
  matching a single upper-half device-ID encoding.

**Validation:** Loopback test (configs/spi-loopback) before sensor attachment.

---

### I2C (Line 2)

**NuttX Foundation:** `rzv_sci_i2c.c` (`rzv_sci_i2c_initialize`, SCI-mode simple-I2C — the BMP280 path) + `rzv_i2c.c` (RIIC native, unused on this board).

**Status — build-clean:** The BMP280 barometer is wired to SCI7 simple-I2C
(P76/P77). The default board enables `CONFIG_RZV_SCI_I2C` and
`CONFIG_RZV_SCI7_I2C`; `px4_i2cbus_initialize(7)` dispatches explicitly to
`rzv_sci_i2c_initialize(7)`. The lower-half and BMP280 consumer link in the
integrated image. No on-target transaction or recovery evidence exists yet.

**PX4 HAL Interface:**
- `px4_i2cbus_initialize(bus)` → `rzv_sci_i2c_initialize(channel)` for SCI-I2C buses.
- Bus/device table in `boards/renesas/rdk-rzv2h/src/i2c.cpp` (BMP280 @ 0x76, `PX4_I2C_BUS_EXPANSION=7`).

**Validation:** `i2cdetect`/BMP280 probe on bus 7, chip ID and calibration
reads, repeated samples, SCL/SDA capture, NACK/timeout injection, and bus
recovery.

---

### UART/Serial (Line 3)

**NuttX Foundation:** `rzv_serial.c` dispatches the SCI-B lower halves used by
the active serial policy. `rzv_scif.c` is a separate SCIFA sample driver, not
the implementation behind SCI4/5/6/9. The SCIF path is currently blocked (see
[port-status-nuttx.md](port-status-nuttx.md)). Board policy is mode-specific:
standalone CR8-0 NuttX uses SCI4 shell + RTT diagnostics; CR8-1 target shell
is SCI5; CM33 target shell is SCI9. Integrated PX4 CR8-0 registers
`/dev/console` on RTT0 for text input/output, bypasses SCI low-setup, and
routes SCI4/5/6/9 to LiDAR, MAVLink/QGC, RC, and GPS respectively. This RTT
path is build-clean; target shell I/O remains unvalidated.

Integrated serial generation maps SCI4 to `EXT2` (ID 401). Board defaults set
`SENS_TFMINI_CFG=401`, so `rc.serial` starts TFmini on `/dev/ttyS4`; this does
not affect the separate standalone NuttX image where SCI4 is the shell.

**PX4 HAL Interface:**
- Register `struct uart_dev_s` (NuttX native).
- Flow control (RTS/CTS) if available on board.
- MAVLink telemetry stream over /dev/ttyS5 for QGroundControl.
- Interactive RTT0 console on integrated PX4; SCI4 remains the standalone
  CR8-0 shell.

**Validation:** MAVLink heartbeat reception; baud rate stability (115200, 230400, 460800).

---

### GPIO (Line 4)

**NuttX Foundation:** `rzv_gpio.c` (Port 0–12).

**PX4 HAL Interface:**
- GPIO control via `px4_arch_gpioread()`, `px4_arch_gpiowrite()`.
- IRQ attachment via `px4_arch_gpioirq()` + callback.
- LED control (status, error, heartbeat LEDs on rdk-rzv2h).

**Validation:** LED blink test (configs/nsh-leds); button IRQ latency is measured and compared against the board-specific acceptance criterion.

---

### PWM/ESC (Line 5)

**NuttX Foundation:** RZ/V2H GPT direct-register output path in
`io_timer.c`, backed by NuttX clock and GPT module control.

**PX4 HAL Interface:**
- Four direct outputs through `PWMOut` and `pwm_servo.c`.
- Board policy forces all selected GTIOC outputs inactive when the mixer
  asserts `stop_motors`.
- Restart-safe timer-channel allocation; DShot ownership remains exclusive.
- The default board path rejects `PWM_MAIN_TIMx=-1` and exposes 50-500 Hz
  analog PWM. Internal OneShot ownership plumbing has no board trigger path;
  NuttX lower-half pulse-count mode is separate.

**Validation:** Scope boot, arm, disarm, lockdown, actuator test, process stop,
and restart. Then verify frequency, width, mapping, and skew on all four pins.

### DShot (Line 5b)

**NuttX Foundation:** `rzv_gpt.c` buffered compare output + `rzv_dmac.c` hardware-triggered, one-shot memory-to-peripheral transfers.

**PX4 HAL Interface:**
- `renesas_rdk-rzv2h_dshot` is an opt-in TX-only build through `dshot.px4board`.
- `renesas_rdk-rzv2h_default` continues to link and start PWM output; it excludes DShot.
- The DShot image also links `pwm_out` to generate the shared `PWM_MAIN`
  parameter schema. Board defaults select DShot600 (`-3`) for all four timer
  groups, so `pwm_out` has an empty runtime mask and does not claim them.
- Bidirectional capture is intentionally unavailable and reports `-ENOTSUP`. The decoder is retained for future capture-front-end work only.

**Validation:** Host build and artifact separation pass. Logic-analyzer waveform/ordering, repeated trigger and re-arm, multi-channel launch, cleanup paths, and ESC response remain on-target gates. See the [QA report](../../plans/reports/tester-260720-rzv2h-dshot-runtime-fixes.md) and [code review](../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md).

---

### ADC (Line 6)

**NuttX Foundation:** `rzv_adc.c` (12-bit SAR).

**PX4 HAL Interface:**
- Register ADC channels via `adc_register()`.
- Sensor calibration (baro offset, airspeed scale).
- Sample rate: min 1 kHz (for vibration filtering).

**Validation:** Noise floor <1 LSB; thermal drift <0.1%/°C.

---

### Timer/HRT (Line 7)

**NuttX Foundation:** `rzv_hrt.c` owns dedicated GTM7. GPT6/7/9/10 remain
separate PWM resources. The checked-in reference supports a 100 MHz P1CLK,
but live loader-owned clock divergence is not yet detected.

**PX4 HAL Interface:**
- `px4_clock_gettime()` for µs-precision timestamps.
- Work-queue scheduling backed by HRT expiry.
- Flight-control loop clock source.

**Software status:** The arch layer keeps GTM7 in bounded free-running
comparison mode and advances a 64-bit epoch before every restart. The PX4
queue chains long deadlines through intermediate wakeups, handles periodic
self-delay/self-cancel, and treats initialization or arm failure as fatal.
Integrated build, target-object inspection, debugger review, and tester review
pass. See the
[GTM7 HRT review](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/reviewer-260727-rzv2h-hrt-gtm7.md).

**Target validation:** confirm runtime P1CLK and monotonicity across a real or
accelerated counter wrap; then measure jitter and uptime against the
board-specific acceptance criterion under queue load.

---

### CAN (Line 8)

**NuttX Foundation:** `rzv_canfd.c` (CAN-FD controller; supports classical CAN 2.0B).

**PX4 HAL Interface:**
- CAN device driver (standard: `struct can_dev_s`).
- Bitrate config (250k, 500k, 1M typical for UAV).
- Telemetry (TBD: SLCAN over UART as fallback).

**Validation:** CAN frame RX/TX with known CAN analyzer; arbitration stress.

---

### Ether/MAVLink UDP (Line 9)

**NuttX Foundation:** `rzv_ether.c` (MAC) + `rzv_ether_phy.c` (PHY).

**PX4 HAL Interface:**
- Network driver registration (NuttX netdev).
- DHCP or static IP config.
- UDP MAVLink listener on port 14550.

**Validation:** Ping response; MAVLink GCS connection; latency <100 ms.

---

### xSPI/LittleFS (Line 10)

**NuttX Foundation:** the default image links
`rzv2h_volatile_paramfs.c`, mounts TMPFS at `/fs` from the active PX4
`board_app_initialize()` path, and logs that parameters reset on reboot.
`rzv2h_xspi_paramfs.c` is experimental and disabled. Its prior NuttX
`board_bringup()` call was not part of the custom PX4 board startup path.

**PX4 HAL Interface:**
- Current pre-G9 fallback: volatile `/fs/params`.
- Parameter storage uses the xSPI partition only after boundary and power-cycle proof.
- ULog uses a separate SDHI-backed mount when SDHI is validated.

**Validation:** Partition-boundary audit, mount, parameter save/reboot/load,
controlled power-loss recovery, and proof that no executable/boot region is
erased.

---

## CR8-0 Goal Reconciliation

- Required first-drone HAL gates: SPI0 IMU, SCI7 I2C barometer, SCI4/5/6/9
  serial, GPS SCI9 115200 8N1, RC SCI6 100000 8E2 plus inversion, GPIO/IRQ,
  GTM7 HRT, GPT PWM, and parameter persistence.
- Post-G9/non-gating: ADC, WDT integration, and SDHI/ULog. These are not active
  in the checked-in drone reference.
- Optional: CAN, Ethernet/UDP, DShot.
- Default integrated PX4 must not fail because OpenAMP, IPCC, CR8-1, CM33, or a
  CA55 endpoint is absent.
- The integrated image uses RTT0 for text console/debug and SCI5 for binary
  MAVLink/QGroundControl traffic.
- `renesas_rdk-rzv2h_core_only` is a diagnostics-only rollback image; use it
  for RTT/HRT/work-queue/parameter/uORB inspection, not for hardware proof.
- The fixed board UUID/GUID prevents multi-device deployment until a
  provisioned per-device identity source and persistent storage contract are
  approved. Do not infer uniqueness from the current values.
- Software checkpoint: `system_time hrt-test` and `work_queue status` are the
  exact HRT/work-queue checks; the default image now keys `dshot start` off
  `DSHOT_START` instead of invoking the absent DShot path unconditionally.
  The automatic payload artifact contract also rejects missing startup
  utilities, board-enabled absent hardware probes, a non-NuttX `pipe()`, split
  image/package mismatch, or undefined ELF symbols.

---

## Roadmap Link

Detailed implementation order and dependency chain: see [Project Roadmap](../project-roadmap.md).

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — driver-level completeness.
- [Code Standards](../code-standards.md) — PX4 API conventions.
- [System Architecture](../system-architecture.md) — HAL role in CR8-0/CR8-1/CM33 topology.
