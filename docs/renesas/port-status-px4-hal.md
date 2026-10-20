# PX4 HAL Port Status Matrix

**Scope:** RDK-RZ/V2H PX4 integration; NuttX lower-half evidence is maintained
separately in [driver status](port-status-nuttx.md). A standalone sample result
does not qualify an integrated physical HAL.

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **bounded on-target**: A named image/run demonstrates the stated behavior; fixture, timing and physical qualification limits remain explicit.
- **build-clean**: HAL adapter implemented and wired into its named board target; compiles/links. No on-target hardware validation yet.
- **bounded on-target**: A named CR8-0 evidence record verifies a limited integration path; physical behavior and untested profiles remain open.
- **deferred**: HAL adapter present but the feature is intentionally disabled in the default build pending hardware enablement (documented in board defconfig).
- **validated**: On-target integration tests pass; used in application code.

No physical PX4 HAL surface is claimed validated. SIH has bounded evidence for
simulation and HRT only; its [transcript](evidence/px4-nuttx-rzv2h-sih-transcript.txt)
does not validate physical payload buses or motor outputs. Historical build
hashes, reset-symbol checks, SIH provenance limits and DShot host results are
kept in [software checkpoints](evidence/px4-hal-software-checkpoints.md).

CR8-1 and CM33 PX4IO startup now checks transport initialization before
publishing the module instance; failure is reported and releases the instance.
The [expanded remediation record](../../plans/261013-0624-rzv2h-expanded-remediation/reports/remediation.md)
tracks verification. The staged demo ramp and echo are replaced: CR8-1 relays
the CR8-0 bridge's actuator commands to CM33, and both peers drive commanded
values only while frames stay fresh, then output `0` after the 50 ms output lease; CR8-1 gates outputs through a Safe/Ready/Armed/SafeFault lease and reports from a separate thread (see the
[IPC architecture](ipc-architecture.md#current-application-and-ca55-integration-gaps)).
The return path is CR8-1 heartbeat and fault status at 10 Hz; the CR8-0
bridge tracks CR8-1 liveness with a 500 ms timeout. On 2026-10-13 the CR8-1 IO
image autostarted from ROMFS on the board and streamed 20 consecutive
CRC-valid heartbeat/fault frames to a CR8-0 `ipcc-raw` reader (bounded
on-target for the CR8-1 side only). The `renesas_rdk-rzv2h_dualcr8` CR8-0
profile (the `drone` profile plus the bridge and the raw `/dev/ipcc1`
initiator) runs the full CR8-0 → CR8-1 command path on the disarmed bench:
CR8-1 holds a 404 Hz ESC worker and a 370 Hz control loop, the CR8-1 lease
also requires a fresh CR8-0 heartbeat, and the bridge publishes
`px4io_status`, on which commander's I/O-processor check blocks arming when
CR8-1 is silent, in SafeFault or not receiving FMU outputs (bounded
on-target, 2026-10-13; armed and SafeFault paths host-tested only). CM33 has
no PWM backend and is optional and low priority; the single-core CR8-0 drone
demo comes first, dual CR8 later.

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

The latest [CR8-0 PX4 hardware campaign](evidence/px4-hardware-tests-cr8-0-261021.md)
records 21/32 native test entries passed and 11 blocked. It adds bounded
zero-throttle DShot600 transfer/restart completion and detached HRT timing, while
retaining the RTT-attached HRT failure and the absent sensor, RX-fixture,
waveform, persistence, cold-cycle, soak, other-profile, and IO-core limits.

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `micro_hal/micro_hal.cpp` (`px4_spibus_initialize`) | `rzv_spi.c` + board IOPORT/PFC mux + GPIO CS | boards/renesas/rdk-rzv2h/src/spi.cpp | build-clean; target pending | `CONFIG_RZV_SPI=y`. `board_app_initialize()` now calls `board_spi_initialize()` before sensor startup, which muxes P90/P91/P92 and configures P93 as active-low GPIO CS. The board select hook keys on the SPI0 lower-half instance, so PX4 sensor IDs and standalone NuttX test IDs share the same CS path. Initialization and standalone registration retry state are serialized/published safely. [Software checkpoint](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/pm-260727-0701-rzv2h-integrated-spi-closure.md). The native simple profile selects one ICM20948 with P94 DRDY; default/DShot retain MPU9250. On-target identity/data/FIFO/DRDY proof pending. The opt-in drone profile uses three strict descriptor IDs and polled GPIO CS; its host/build checks pass, with target qualification open. The latest CR8-0 campaign records `i2c_spi_cli` passing while MPU9250 instances and accel/gyro topics remained absent; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 2 | I2C | `micro_hal/micro_hal.cpp` (`px4_i2cbus_initialize`) | rzv_sci_i2c.c (`rzv_sci_i2c_initialize`, SCI-mode) | boards/renesas/rdk-rzv2h/src/i2c.cpp | build-clean | Native BMP280 baro on SCI7 simple-I2C P76/P77. `CONFIG_RZV_SCI7_I2C=y`; bus 7 dispatches explicitly to `rzv_sci_i2c_initialize(7)`, never RIIC, and maps safely to its dense PX4 clock slot. Fresh standalone HIL and integrated PX4 builds pass; BMP280 probe/read/recovery remains unvalidated on target. The drone profile links and starts BMM150 0x10, BMP390L/bmp388 0x77 and INA228 0x45; its host/build integration passes, with target identity/data/recovery proof open. The latest CR8-0 campaign found no BMP280 instance and no barometer publication; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 3 | UART/Serial | NuttX serial (native) | `rzv_serial.c` SCI-B lower halves; SCIF is separate sample-only path | boards/renesas/rdk-rzv2h/ | in-progress | Core-matched `rzv2h_evk/sci_b_uart` projects are the SCI-B reference. Explicit policy: standalone CR8-0 NuttX = SCI4 shell + RTT diagnostics; target CR8-1 = SCI5 shell + RTT diagnostics; target CM33 = SCI9 shell + RTT diagnostics. Integrated PX4 RTT0 `/dev/console` is build-clean and bypasses SCI low-setup. SCI4/5/6/9 retain payload ownership in the full image. SCIF/SCIFA has no EVK application example and remains sample-only/blocked. The latest CR8-0 campaign saw TX progress but zero RX on the four inspected serial ports, with no GPS fix, RC frame, or payload response; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 4 | GPIO | `include/px4_arch/micro_hal.h` (macros → `rzv_gpio*`) | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | build-clean | Port I/O + IRQ/edge via rzv_gpiosetevent. On-target IRQ latency pending |
| 5 | PWM/ESC | `io_pins/io_timer.c` + `pwm_servo.c` | direct GPT MMIO; standalone `rzv_gpt.c` lower-half is mutually exclusive | boards/renesas/rdk-rzv2h/src/timer_config.cpp | build-clean | FSP logical mapping: GPT6A/7B/9A/10B on PA4/PA7/P96/P53; logical 9/10 resolve to physical R_GPT11/R_GPT12. Live rate/duty changes use GPT buffers, stopped/disabled paths clear the counter, first setup performs the GTUDDTYC UDF latch, compare values use counts−1, and partial timer/GPIO initialization unwinds. The board-scoped PX4 path disables motor GTIOC on `stop_motors`, validates allocation ownership, and safely reallocates after module restart without stealing DShot ownership. Before a normal reset, `board_on_reset()` unconfigures PA4/PA7/P96/P53 and waits 6 ms; the WDT-backed reset chain is build-verified in all four historical August 2 board ELFs. The default PX4 board path exposes analog PWM only and rejects `PWM_MAIN_TIMx=-1`; internal OneShot ownership plumbing has no board trigger path. Standalone NuttX finite pulse-count PWM is separate. The historical core-only demo auto-started `pwm_out`, prints `work_queue status`, and uses `actuator_test set -m 1 -v 0 -t 5` for a bounded 1100 µs Motor 1 bench waveform. Integrated and standalone PWM builds plus source-contract regressions pass. Waveform, inactive-level, transition, reset, and failsafe scope proof pending. |
| 5b | DShot (GPT+DMA) | `dshot/dshot.c` + `dshot/dshot_telemetry.c` | direct GPT MMIO + `rzv_dmac.c` (HW compare-trigger) | boards/renesas/rdk-rzv2h/dshot.px4board | bounded on-target (motor-stop TX) | TX-only target `renesas_rdk-rzv2h_dshot`; default remains PWM and excludes DShot. The DShot image includes `pwm_out` for shared `PWM_MAIN` parameters, while `PWM_MAIN_TIM0..3=-3` leaves every group to DShot. `DSHOT_START` selects the opt-in startup. The 2026-10-02 remediation replaces overflow/buffered pacing with selected active GPT compare events, absolute edge timestamps, and bounded fail cleanup. [Runtime model regressions](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dshot-runtime-after.log) pass 23/23; the [2026-10-12 software checkpoint](../../plans/261012-1525-renesas-coding-standards/reports/implementation-progress.md) records successful DShot/default builds. The [2026-10-20 CR8-0 run](evidence/dshot-dmac-cr8-0-validation-261020.md) verifies repaired NSH startup, automatic DShot600 mask `0xf`, disarmed state, HRT and register-level stop cleanup; its DMAC0 frame fails with `-EIO`. The [resumed CR8-0 repair](evidence/dshot-dmac-cr8-0-validation-261020.md) uses explicit DMAC3 channels 56–59 and repaired route/state handling: four DShot600 motor-stop transfers reach TC, consume 128 bytes each, and pass a second module start/stop cycle; final GPT gates are disabled and commander is disarmed. Nonzero throttle and electrical/ESC qualification remain open. BDShot capture/telemetry returns `-ENOTSUP`. Physical edge latency, four-pin waveforms, and ESC response remain unvalidated. The [2026-10-21 CR8-0 campaign](evidence/px4-hardware-tests-cr8-0-261021.md) repeats explicit four-channel zero-throttle completion on boot and restart, 128 bytes each, with register and host cleanup. |
| 6 | ADC | `adc/adc.cpp` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | deferred/non-gating | Core-matched `rzv2h_evk/adc_e` projects provide FSP driver/config evidence, but the integrated drone reference still has no active ADC consumer. The native NuttX ADELCCR byte-width defect is fixed in source. The optional PX4 adapter matches the public two-argument sample API and supplies the architecture ADC header. Each sample request discards old results, triggers a native single scan and polls completion with a 1 ms delay budget; failure returns `UINT32_MAX`. The actual adapter and board ADC consumer compile and resolve their ADC symbols; [software remediation](../../plans/261013-0002-rzv2h-audit-remediation/plan.md) retains target conversion/pin and work-queue timing proof as open; post-G9. |
| 7 | Timer/HRT | `hrt/hrt.c` (queue mgr) → `rzv_hrt_*` | rzv_hrt.c (selected GTM free-run) | boards/renesas/rdk-rzv2h/src/ | bounded on-target (CR8-0 detached check) | `CONFIG_RZV_HRT=y`; CR8-0 selects GTM7, CR8-1 IO selects GTM6, and CM33 IO reserves GTM5 with its core-matched register alias and fixed NVIC input (IO images build-clean, target pending). GTM7 ownership is clean and stale GTM0/120 MHz declarations are removed. A bounded free-run compare maintains the 64-bit epoch; cancel/rearm preserves elapsed ticks; long deadlines use intermediate wakeups; mandatory initialization/arm failures fail visibly; periodic self-delay/self-cancel matches the PX4 contract. Integrated build and source review pass. Runtime P1CLK, wrap monotonicity, jitter, and soak proof remain target gates. The [2026-10-21 CR8-0 check](evidence/px4-hardware-tests-cr8-0-261021.md) measured 11,041 us sleep and 4 us callback latency with the probe detached. The RTT-attached comparison failed at 133,603 us; this bounded result does not promote CR8-1/CM33 or qualify long-run timing. |
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

### Open decisions (2026-10-13)

These need an owner decision; none blocks the single-core CR8-0 demo build.
Dual-CR8 questions live in
[IPC architecture: open dual-CR8 decisions](ipc-architecture.md#open-dual-cr8-decisions).

1. **`CONFIG_DEBUG_INFO=y`** is set in all six rdk-rzv2h profiles, so every
   `*info` line reaches the RTT console. The SCI clock line no longer repeats
   on each `rc_input` reconfigure (NuttX `1c39b91c59`). Board check
   2026-10-13 (drone and dualcr8 at PX4 `c07a3c19eec`): 10 s of idle RTT
   showed no `SCI6 clocks` line. `SCI9 clocks disabled/enabled` pairs remain
   (7-8 lines per 10 s); they are real gate changes from the GPS driver
   closing and reopening `/dev/ttyS9` while no GPS answers. Keep
   `DEBUG_INFO` for bring-up, or turn it off for demo images.
2. **Board Kconfig `BOARD_RDK_RZV2H_HAS_{BARO,IMU,MAG}`** are default-on,
   unused, and their help text names MPU9250/AK8963 sensors this board does
   not carry. Remove them, or rewrite them for the real sensors.
3. **Runtime warnings seen on the dualcr8 bench:** low free stack on
   `wq:ttyS6` (232 B) and `navigator` (280 B), five `param 65535` warnings,
   `battery_status: command not found`, "Too many arming check events
   (14>14)", and boot-time `recover_failures` reaching 16. Decide which are
   in scope for the demo.
4. **NSH startup budgets (repaired 2026-10-20).** Default/DShot use the
   shared [nsh config](../../boards/renesas/rdk-rzv2h/nuttx-config/nsh/defconfig),
   which now reserves the same full-startup parser/stack budgets as drone and
   dualcr8. The [startup regression](../../test/rzv2h-drone-profile-contract-test.py)
   covers the shared config; specialized simple/SIH profiles retain their own
   configuration. The named DShot run above verifies parser errors are gone.
5. **`boards/renesas/evk-ra8p1/Kconfig`** writes its prompts with escaped
   quotes (`bool \"...\"`), which Kconfig rejects if that file is ever
   sourced. The RZ/V2H build sources only its own board Kconfig, so this RA8
   file is left untouched as out of scope.

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
