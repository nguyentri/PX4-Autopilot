# PX4 HAL Port Status Matrix

**Scope:** RDK-RZ/V2H PX4 integration; NuttX lower-half evidence is maintained
separately in [driver status](port-status-nuttx.md). A standalone sample result
does not qualify an integrated physical HAL.

## Status Legend

- **planned**: HAL surface identified; NuttX driver ready; implementation pending.
- **in-progress**: Skeleton drafted; driver integration underway.
- **bounded on-target**: A named image/run demonstrates the stated behavior; fixture, timing and physical qualification limits remain explicit.
- **build-clean**: HAL adapter implemented and wired into its named board target; compiles/links. No on-target hardware validation yet.
- **deferred**: HAL adapter present but the feature is intentionally disabled in the default build pending hardware enablement (documented in board defconfig).
- **validated**: On-target integration tests pass; used in application code.

No physical PX4 HAL surface is claimed validated. SIH has bounded evidence for
simulation and HRT only; its [transcript](evidence/px4-nuttx-rzv2h-sih-transcript.txt)
does not validate physical payload buses or motor outputs. Historical build
hashes, reset-symbol checks, SIH provenance limits and DShot host results are
kept in [software checkpoints](evidence/px4-hal-software-checkpoints.md).

The legacy v2 CR8-0 `px4io_bridge`/`uorb_bridge` path has a real PX4 uORB to
raw-IPC transport and publishes `px4io_status` for Commander's I/O-processor
arming check. Its source loop sleeps 2.5 ms (400 Hz); the named 2026-10-13
disarmed bench observation measured the historical CR8-1 relay worker at about
404 Hz and its control loop at about 370 Hz. That observation also recorded the
CR8-1 image autostarting from ROMFS and streaming 20 consecutive CRC-valid
heartbeat/fault frames to a CR8-0 `ipcc-raw` reader. It is bounded historical
evidence for the then-staged v2 image; armed and SafeFault paths were
host-tested only. CM33 has no PWM backend and remains optional and low
priority.

The current v3 path is separate. Canonical `dualcr8` links the
`rzv2h_outputs` producer with PX4 mixer/uORB and the Commander I/O-status gate,
but deliberately has no local PWM/DShot driver or legacy bridge. The CR8-1
`pwm` image is a compiled v3 supervisor candidate with a 400 Hz worker and a
separate status reporter. The worker uses a 50 ms logical lease and inhibits
stale output; its hardware identity, output rate, output mask and hardware
contract are all zero, so it remains unconfigured/inhibited. The current
software receipt records the exact builds, host checks and review repairs
without promoting either image to a hardware-qualified actuator pair:
[dual-CR8 software validation](evidence/dualcr8-software-validation-261021.md).

The PX4 `demo` pair is a separate heartbeat-only path: CR8-0 `renesas_rdk-rzv2h_demo` (raw IPC initiator) and CR8-1 `renesas_rdk-rzv2h-io-cr8_1_demo` (responder, RTT NSH) both run `rzv2h_heartbeat`: CR8-0 sends one v3 heartbeat every 100 ms, CR8-1 replies to each one it accepts (a raw write blocks until the peer reads, so the cores never write at once), and each side reports the peer lost after 500 ms. It publishes no uORB topic (never `px4io_status`), so it cannot gate arming, and it sends no actuator frames. Status: **bounded on-target** (2026-11-09): paired exchange, loss while CR8-1 is held halted, recovery, and standalone CR8-0 with a baseline `commander check`, proven in `docs/renesas/evidence/px4-demo-dual-cr8-heartbeat-261109.md`. Host tests: `test/rzv2h-ipc-heartbeat-test.py`. A 6-minute steady-state soak (3226 exchanges, no new session, timeout or bad header) passed; a multi-hour soak is still open.

The `src/apps/gateway.*` advisory validator is a host-tested component contract.
Its A55 transport, deployment, uORB handoff and Commander fallback remain
future integration work; it does not change the compiled CR8-0 v3 status path.

### Canonical dual-CR8 sensor preparation

`renesas_rdk-rzv2h_dualcr8` is **build-clean for sensor bring-up only**:
one polled ICM-45686/P93, BMM150, BMP390, M10 and TFmini startup routes.
Host tests execute the selected SPI descriptors/CS dispatch, initialization
failure/retry, remote-owner reset/timer exclusion, first-status arming failure
and final TFmini 115200 8N1 application. The linked image contains no local
PWM/DShot driver or legacy bridge. It cannot arm normally without I/O status.
The [dual-CR8 software validation receipt](evidence/dualcr8-software-validation-261021.md)
records the current build hashes, host checks and evidence boundary. Earlier
execution and consolidation records contain historical pre-merge hashes and
remain stateful records rather than current release proof.
The v3 `rzv2h_outputs` producer and CR8-1 `pwm` supervisor now have source,
host and build evidence. CR8-1 separates controller, worker and reporter;
worker faults and stale control/status cannot remain arm-ready. Default-off
delayed bench hooks and candidate ELF/ROMFS/package checks are described in
the [candidate validation procedure](validation/dualcr8-sensor-actuator-demo.md).
The compiled hardware identity remains unconfigured (zero output profiles,
rate, mask and contract), so physical output resources remain unclaimed.
Selected ESC, battery/storage/command hardware, accepted pair identity and all
physical qualification remain open.

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

The separate [sensor-free RTT validation record](evidence/sensor-free-rtt-validation-261024.md)
and [machine matrix](evidence/sensor-free-rtt-matrix-261024.json) account for
128 native NuttX entries: 92 PASS, 2 NOT-PASS, 6 BLOCKED and 28 OUT-OF-SCOPE.
Their register, ISR-delivery and internal-function scope does not promote any
PX4 HAL row to physical or production qualification. No sensors or PWM
waveforms were exercised. Both GBETH units remain supported; matching-core I/O
headers take precedence where present.

## HAL Inventory

| # | Peripheral | PX4 HAL File | NuttX Driver Dep | PX4 Board Dir | Status | Migration Notes |
|---|------------|--------------|------------------|---------------|--------|-----------------|
| 1 | SPI | `micro_hal/micro_hal.cpp` (`px4_spibus_initialize`) | `rzv_spi.c` + board IOPORT/PFC mux + GPIO CS | boards/renesas/rdk-rzv2h/src/spi.cpp | build-clean; target pending | `CONFIG_RZV_SPI=y`. `board_app_initialize()` now calls `board_spi_initialize()` before sensor startup, which muxes P90/P91/P92 and configures P93 as active-low GPIO CS. The board select hook keys on the SPI0 lower-half instance, so PX4 sensor IDs and standalone NuttX test IDs share the same CS path. Initialization and standalone registration retry state are serialized/published safely. [Software checkpoint](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/reports/pm-260727-0701-rzv2h-integrated-spi-closure.md). The native simple profile selects one ICM20948 with P94 DRDY; default/DShot retain MPU9250. On-target identity/data/FIFO/DRDY proof pending. The opt-in drone profile uses three strict descriptor IDs and polled GPIO CS; its host/build checks pass, with target qualification open. The latest CR8-0 campaign records `i2c_spi_cli` passing while MPU9250 instances and accel/gyro topics remained absent; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 2 | I2C | `micro_hal/micro_hal.cpp` (`px4_i2cbus_initialize`) | `rzv_sci_i2c.c`; opt-in native `rzv_i2c.c` through board admission | boards/renesas/rdk-rzv2h/src/i2c.cpp | build-clean | Native BMP280 baro on SCI7 simple-I2C P76/P77. The compile-time validator covers RIIC0–8 plus the existing SCI7 bus7 owner, rejecting overlapping bus7 claims. Opt-in native buses use `board_i2c_initialize()` and its pin admission/cache; PX4 borrows board-lifetime native/SCI owners, so teardown does not invalidate the cache. Expanded routes have host checks and no physical qualification; the board bus list is unchanged. `CONFIG_RZV_SCI7_I2C=y`; bus 7 dispatches explicitly to `rzv_sci_i2c_initialize(7)`, never RIIC, and maps safely to its dense PX4 clock slot. Fresh standalone HIL and integrated PX4 builds pass; BMP280 probe/read/recovery remains unvalidated on target. The drone profile links and starts BMM150 0x10, BMP390L/bmp388 0x76 (SDO to GND) and INA228 0x45; its host/build integration passes, with target identity/data/recovery proof open. The latest CR8-0 campaign found no BMP280 instance and no barometer publication; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 3 | UART/Serial | NuttX serial (native) | `rzv_serial.c` SCI-B lower halves; SCIF is separate sample-only path | boards/renesas/rdk-rzv2h/ | in-progress | Core-matched `rzv2h_evk/sci_b_uart` projects are the SCI-B reference. Explicit policy: standalone CR8-0 NuttX = SCI5 serial shell + RTT diagnostics (SCI5 doubles as PX4 telemetry); target CR8-1 = SCI5 shell + RTT diagnostics; target CM33 = SCI9 shell + RTT diagnostics. Integrated PX4 RTT0 `/dev/console` is build-clean and bypasses SCI low-setup. SCI4/5/6/9 retain payload ownership in the full image. SCIF/SCIFA has no EVK application example and remains outside the PX4 payload path. Its native internal loopback/reopen now has bounded evidence in the [sensor-free campaign](evidence/sensor-free-rtt-validation-261024.md); external pinmux and peer traffic remain unqualified. The latest CR8-0 campaign saw TX progress but zero RX on the four inspected serial ports, with no GPS fix, RC frame, or payload response; see [hardware evidence](evidence/px4-hardware-tests-cr8-0-261021.md). |
| 4 | GPIO | `include/px4_arch/micro_hal.h` (macros → `rzv_gpio*`) | rzv_gpio.c | boards/renesas/rdk-rzv2h/src/ | build-clean | Port I/O + IRQ/edge via rzv_gpiosetevent. On-target IRQ latency pending |
| 5 | PWM/ESC | `io_pins/io_timer.c` + `pwm_servo.c` | direct GPT MMIO; standalone `rzv_gpt.c` lower-half is mutually exclusive | boards/renesas/rdk-rzv2h/src/timer_config.cpp | build-clean | FSP logical mapping: GPT6A/7B/9A/10B on PA4/PA7/P96/P53; logical 9/10 resolve to physical R_GPT11/R_GPT12. Live rate/duty changes use GPT buffers, stopped/disabled paths clear the counter, first setup performs the GTUDDTYC UDF latch, compare values use counts−1, and partial timer/GPIO initialization unwinds. The board-scoped PX4 path disables motor GTIOC on `stop_motors`, validates allocation ownership, and safely reallocates after module restart without stealing DShot ownership. Before a normal reset, `board_on_reset()` unconfigures PA4/PA7/P96/P53 and waits 6 ms; the WDT-backed reset chain is build-verified in all four historical August 2 board ELFs. The default PX4 board path exposes analog PWM only and rejects `PWM_MAIN_TIMx=-1`; internal OneShot ownership plumbing has no board trigger path. Standalone NuttX finite pulse-count PWM is separate. The historical core-only demo auto-started `pwm_out`, prints `work_queue status`, and uses `actuator_test set -m 1 -v 0 -t 5` for a bounded 1100 µs Motor 1 bench waveform. Integrated and standalone PWM builds plus source-contract regressions pass. Waveform, inactive-level, transition, reset, and failsafe scope proof pending. |
| 5b | DShot (GPT+DMA) | `dshot/dshot.c` + `dshot/dshot_telemetry.c` | direct GPT MMIO + `rzv_dmac.c` (HW compare-trigger) | boards/renesas/rdk-rzv2h/dshot.px4board | bounded on-target (motor-stop TX) | TX-only target `renesas_rdk-rzv2h_dshot`; default remains PWM and excludes DShot. The DShot image includes `pwm_out` for shared `PWM_MAIN` parameters, while `PWM_MAIN_TIM0..3=-3` leaves every group to DShot. `DSHOT_START` selects the opt-in startup. The 2026-10-02 remediation replaces overflow/buffered pacing with selected active GPT compare events, absolute edge timestamps, and bounded fail cleanup. [Runtime model regressions](../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dshot-runtime-after.log) pass 23/23; the [2026-10-12 software checkpoint](../../plans/261012-1525-renesas-coding-standards/reports/implementation-progress.md) records successful DShot/default builds. The [2026-10-20 CR8-0 run](evidence/dshot-dmac-cr8-0-validation-261020.md) verifies repaired NSH startup, automatic DShot600 mask `0xf`, disarmed state, HRT and register-level stop cleanup; its DMAC0 frame fails with `-EIO`. The [resumed CR8-0 repair](evidence/dshot-dmac-cr8-0-validation-261020.md) uses explicit DMAC3 channels 56–59 and repaired route/state handling: four DShot600 motor-stop transfers reach TC, consume 128 bytes each, and pass a second module start/stop cycle; final GPT gates are disabled and commander is disarmed. Nonzero throttle and electrical/ESC qualification remain open. BDShot capture/telemetry returns `-ENOTSUP`. Physical edge latency, four-pin waveforms, and ESC response remain unvalidated. The [2026-10-21 CR8-0 campaign](evidence/px4-hardware-tests-cr8-0-261021.md) repeats explicit four-channel zero-throttle completion on boot and restart, 128 bytes each, with register and host cleanup. |
| 6 | ADC | `adc/adc.cpp` | rzv_adc.c | boards/renesas/rdk-rzv2h/src/ | deferred/non-gating | Core-matched `rzv2h_evk/adc_e` projects provide FSP driver/config evidence, but the integrated drone reference still has no active ADC consumer. The native NuttX ADELCCR byte-width defect is fixed in source. The optional PX4 adapter matches the public two-argument sample API and supplies the architecture ADC header. Each sample request discards old results, triggers a native single scan and polls completion with a 1 ms delay budget; failure returns `UINT32_MAX`. The actual adapter and board ADC consumer compile and resolve their ADC symbols; [software remediation](../../plans/261013-0002-rzv2h-audit-remediation/plan.md) retains target conversion/pin and work-queue timing proof as open; post-G9. |
| 7 | Timer/HRT | `hrt/hrt.c` (queue mgr) → `rzv_hrt_*` | rzv_hrt.c (selected GTM free-run) | boards/renesas/rdk-rzv2h/src/ | bounded on-target (CR8-0 detached check) | `CONFIG_RZV_HRT=y`; CR8-0 selects GTM7, CR8-1 IO selects GTM6, and CM33 IO reserves GTM5 with its core-matched register alias and fixed NVIC input (IO images build-clean, target pending). GTM7 ownership is clean and stale GTM0/120 MHz declarations are removed. A bounded free-run compare maintains the 64-bit epoch; cancel/rearm preserves elapsed ticks; long deadlines use intermediate wakeups; mandatory initialization/arm failures fail visibly; periodic self-delay/self-cancel matches the PX4 contract. Integrated build and source review pass. Runtime P1CLK, wrap monotonicity, jitter, and soak proof remain target gates. The [2026-10-21 CR8-0 check](evidence/px4-hardware-tests-cr8-0-261021.md) measured 11,041 us sleep and 4 us callback latency with the probe detached. The RTT-attached comparison failed at 133,603 us; this bounded result does not promote CR8-1/CM33 or qualify long-run timing. Since 2026-11-09 the arch shim keeps the GTM free-running and moves only its compare; the [2026-11-09 demo run](evidence/rtt-hil-demo-hardware-run-261109.md) ran sensors and `pwm_out` on it with gaps only around RTT reconnects, and `reboot` reset the SoC. |
| 8 | CAN | `src/drivers/can/` | rzv_canfd.c | boards/renesas/rdk-rzv2h/src/ | planned | CAN0/CAN1; baud rate; SLCAN over UART alt |
| 9 | Ether/MAVLink UDP | `src/modules/mavlink/` + network stack | rzv_ether.c + rzv_ether_phy.c | boards/renesas/rdk-rzv2h/src/ | planned | No per-core EVK FSP example. Legacy CA55 GBETH/PHY sources are secondary evidence only; descriptor, clock, pinmux, IRQ, link, MDIO, and traffic gates remain. |
| 10 | xSPI/LittleFS | PX4 parameter backend + NuttX LittleFS | `rzv2h_xspi_paramfs.c` board policy/mount path over the `rzv_xspi.c` arch MTD driver | boards/renesas/rdk-rzv2h/src/ | blocked; volatile fallback build-clean | Default mounts TMPFS at `/fs` and uses `/fs/params` without touching flash. Experimental xSPI remains disabled: signed/overflow bounds, flash-relative erase addresses, no-access authority checks, non-formatting mount failure paths and the FSP-derived controller command/Open/64-byte program sequence are host tested against the production arch driver. Fitted flash part/opcodes, a writable MPU mapping of the window, approved partition/cache ownership, target readback, reboot and power-loss proof remain open. Keep separate from SDHI `/dev/mmcsd0` ULog storage. |
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
