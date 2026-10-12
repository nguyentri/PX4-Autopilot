# PX4 HAL Port Status Matrix

**Scope:** RDK-RZ/V2H PX4 integration; NuttX lower-half evidence is maintained
separately in [driver status](port-status-nuttx.md). A standalone sample result
does not qualify an integrated physical HAL.

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **build-clean**: HAL adapter implemented and wired into its named board target; compiles/links. No on-target hardware validation yet.
- **deferred**: HAL adapter present but the feature is intentionally disabled in the default build pending hardware enablement (documented in board defconfig).
- **validated**: On-target integration tests pass; used in application code.

No physical PX4 HAL surface is claimed validated. SIH has bounded evidence for
simulation and HRT only; its [transcript](evidence/px4-nuttx-rzv2h-sih-transcript.txt)
does not validate physical payload buses or motor outputs. Historical build
hashes, reset-symbol checks, SIH provenance limits and DShot host results are
kept in [software checkpoints](evidence/px4-hal-software-checkpoints.md).

### Reference extension boundary

The opt-in `renesas_rdk-rzv2h_drone` profile is build-clean with host/artifact
checks. [Pin ownership](pinmap.md#sensor-wiring-profiles) owns the sensor
layout; [execution progress](../../plans/261011-2017-rzv2h-drone-reference-port/reports/goal-progress.md)
owns the implementation checkpoint. The profile uses polled GPIO chip selects
and PIO; legacy default/simple/SIH/DShot and NuttX samples retain their own
contracts. Physical sensor rates, wiring and recovery remain unqualified.

Parameters remain volatile. Atomic export/recovery software checks do not
prove persistence or power-loss tolerance; the experimental xSPI backend
requires explicit board authority and qualified partition/geometry ownership.
It must not automatically format corrupt media. Prototype identity is not a
per-unit identity source.

The [simple bench procedure](validation/simple-pwm-icm20948-validation.md) owns the
compact PWM/ICM20948 profile, which replaces active core-only use. Fresh P93,
FIFO/P94 and PWM physical measurements remain separate target gates.

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `micro_hal/micro_hal.cpp` (`px4_spibus_initialize`) | `rzv_spi.c` + board IOPORT/PFC mux + GPIO CS | boards/renesas/rdk-rzv2h/src/spi.cpp | build-clean; target pending | `CONFIG_RZV_SPI=y`. `board_app_initialize()` now calls `board_spi_initialize()` before sensor startup, which muxes P90/P91/P92 and configures P93 as active-low GPIO CS. The board select hook keys on the SPI0 lower-half instance, so PX4 sensor IDs and standalone NuttX test IDs share the same CS path. Initialization and standalone registration retry state are serialized/published safely. [Software checkpoint](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/pm-260727-0701-rzv2h-integrated-spi-closure.md). The native simple profile selects one ICM20948 with P94 DRDY; default/DShot retain MPU9250. On-target identity/data/FIFO/DRDY proof pending. The opt-in drone profile uses three strict descriptor IDs and polled GPIO CS; its host/build checks pass, with target qualification open. |
| 2 | I2C | `micro_hal/micro_hal.cpp` (`px4_i2cbus_initialize`) | rzv_sci_i2c.c (`rzv_sci_i2c_initialize`, SCI-mode) | boards/renesas/rdk-rzv2h/src/i2c.cpp | build-clean | Native BMP280 baro on SCI7 simple-I2C P76/P77. `CONFIG_RZV_SCI7_I2C=y`; bus 7 dispatches explicitly to `rzv_sci_i2c_initialize(7)`, never RIIC, and maps safely to its dense PX4 clock slot. Fresh standalone HIL and integrated PX4 builds pass; BMP280 probe/read/recovery remains unvalidated on target. The drone profile links and starts BMM150 0x10, BMP390L/bmp388 0x77 and INA228 0x45; its host/build integration passes, with target identity/data/recovery proof open. |
| 3 | UART/Serial | NuttX serial (native) | `rzv_serial.c` SCI-B lower halves; SCIF is separate sample-only path | boards/renesas/rdk-rzv2h/ | in-progress | Core-matched `rzv2h_evk/sci_b_uart` projects are the SCI-B reference. Explicit policy: standalone CR8-0 NuttX = SCI4 shell + RTT diagnostics; target CR8-1 = SCI5 shell + RTT diagnostics; target CM33 = SCI9 shell + RTT diagnostics. Integrated PX4 RTT0 `/dev/console` is build-clean and bypasses SCI low-setup. SCI4/5/6/9 retain payload ownership in the full image. SCIF/SCIFA has no EVK application example and remains sample-only/blocked. |
| 4 | GPIO | `include/px4_arch/micro_hal.h` (macros → `rzv_gpio*`) | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | build-clean | Port I/O + IRQ/edge via rzv_gpiosetevent. On-target IRQ latency pending |
| 5 | PWM/ESC | `io_pins/io_timer.c` + `pwm_servo.c` | direct GPT MMIO; standalone `rzv_gpt.c` lower-half is mutually exclusive | boards/renesas/rdk-rzv2h/src/timer_config.cpp | build-clean | FSP logical mapping: GPT6A/7B/9A/10B on PA4/PA7/P96/P53; logical 9/10 resolve to physical R_GPT11/R_GPT12. Live rate/duty changes use GPT buffers, stopped/disabled paths clear the counter, first setup performs the GTUDDTYC UDF latch, compare values use counts−1, and partial timer/GPIO initialization unwinds. The board-scoped PX4 path disables motor GTIOC on `stop_motors`, validates allocation ownership, and safely reallocates after module restart without stealing DShot ownership. Before a normal reset, `board_on_reset()` unconfigures PA4/PA7/P96/P53 and waits 6 ms; the WDT-backed reset chain is build-verified in all four historical August 2 board ELFs. The default PX4 board path exposes analog PWM only and rejects `PWM_MAIN_TIMx=-1`; internal OneShot ownership plumbing has no board trigger path. Standalone NuttX finite pulse-count PWM is separate. The historical core-only demo auto-started `pwm_out`, prints `work_queue status`, and uses `actuator_test set -m 1 -v 0 -t 5` for a bounded 1100 µs Motor 1 bench waveform. Integrated and standalone PWM builds plus source-contract regressions pass. Waveform, inactive-level, transition, reset, and failsafe scope proof pending. |
| 5b | DShot (GPT+DMA) | `dshot/dshot.c` + `dshot/dshot_telemetry.c` | direct GPT MMIO + `rzv_dmac.c` (HW compare-trigger) | boards/renesas/rdk-rzv2h/dshot.px4board | build-clean (opt-in; historical build) | TX-only target `renesas_rdk-rzv2h_dshot`; default remains PWM and excludes DShot. The DShot image includes `pwm_out` for shared `PWM_MAIN` parameters, while `PWM_MAIN_TIM0..3=-3` leaves every group to DShot. `DSHOT_START` selects the opt-in startup. The 2026-10-02 remediation replaces overflow/buffered pacing with selected active GPT compare events, absolute edge timestamps, and bounded fail cleanup. [Runtime model regressions](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dshot-runtime-after.log) pass 23/23; fresh DShot/default builds are pending. BDShot capture/telemetry returns `-ENOTSUP`. Physical edge latency, four-pin waveforms, and ESC response remain unvalidated. |
| 6 | ADC | `adc/adc.cpp` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | deferred/non-gating | Core-matched `rzv2h_evk/adc_e` projects provide FSP driver/config evidence, but the integrated drone reference still has no active ADC consumer. The NuttX byte-width defect and target conversion/pin proof remain open; post-G9. |
| 7 | Timer/HRT | `hrt/hrt.c` (queue mgr) → `rzv_hrt_*` | rzv_hrt.c (selected GTM free-run) | boards/renesas/rdk-rzv2h/src/ | build-clean; target pending | `CONFIG_RZV_HRT=y`; CR8-0 selects GTM7 and the CR8-1 IO image selects GTM6 (build-clean, target pending). GTM7 ownership is clean and stale GTM0/120 MHz declarations are removed. A bounded free-run compare maintains the 64-bit epoch; cancel/rearm preserves elapsed ticks; long deadlines use intermediate wakeups; mandatory initialization/arm failures fail visibly; periodic self-delay/self-cancel matches the PX4 contract. Integrated build and source review pass. Runtime P1CLK, wrap monotonicity, jitter, and soak proof remain target gates. |
| 8 | CAN | `src/drivers/can/` | rzv_canfd.c | boards/renesas/rdk-rzv2h/src/ | planned | CAN0/CAN1; baud rate; SLCAN over UART alt |
| 9 | Ether/MAVLink UDP | `src/modules/mavlink/` + network stack | rzv_ether.c + rzv_ether_phy.c | boards/renesas/rdk-rzv2h/src/ | planned | No per-core EVK FSP example. Legacy CA55 GBETH/PHY sources are secondary evidence only; descriptor, clock, pinmux, IRQ, link, MDIO, and traffic gates remain. |
| 10 | xSPI/LittleFS | PX4 parameter backend + NuttX LittleFS | `rzv2h_xspi_paramfs.c` board MTD/mount path | boards/renesas/rdk-rzv2h/src/ | blocked; volatile fallback build-clean | Default mounts TMPFS at `/fs` and uses `/fs/params` without touching flash. Experimental xSPI remains disabled: signed/overflow bounds, flash-relative erase addresses, no-access authority checks and non-formatting mount failure paths are host tested. Controller initialization, approved partition/geometry/cache ownership, target readback, reboot and power-loss proof remain open. Keep separate from SDHI `/dev/mmcsd0` ULog storage. |
| 11 | Board identity | `board_get_uuid()` / `board_get_px4_guid()` | board identity provider | boards/renesas/rdk-rzv2h/src/ | blocked for multi-device deployment | `BOARD_OVERRIDE_UUID` is fixed to `RZV2H0000000000`, and the RZ/V2H GUID provider is derived from fixed architecture/board text. The checked-in FSP evidence says unique-ID support is unavailable. This is acceptable only for a declared single-prototype workflow; fleet use, identity-sensitive pairing, and per-device calibration require an approved provisioning source and persistence design. |

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
- `renesas_rdk-rzv2h_simple` is the compact legacy PWM + one-device ICM20948
  bench image; raw topics, FIFO, P94 callbacks and PWM measurements are
  separate hardware gates. The three-ICM45686/polled extension is the
  separate build-clean drone profile, with physical qualification pending. Retired core-only artifacts remain historical
  evidence.
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

Implementation dependencies and acceptance gates belong to the
[CR8-0 goal plan](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
and [reference-port plan](../../plans/261011-2017-rzv2h-drone-reference-port/plan.md).

## Related Docs

- [NuttX port status](port-status-nuttx.md) — lower-half qualification.
- [Code standards](../code-standards.md) — contribution constraints.
- [System architecture](../system-architecture.md) — integration boundaries.
- [Reference source map](reference-source-map.md) — evidence precedence.
- [GTM7 HRT review](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/reviewer-260727-rzv2h-hrt-gtm7.md) — source review and remaining timing gates.
