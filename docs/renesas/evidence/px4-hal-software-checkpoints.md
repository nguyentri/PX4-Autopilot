# PX4 HAL Software and SIH Evidence Checkpoints

Historical evidence retained from the HAL status record. Dates below belong to
the original observations, not this documentation reorganization. Use the
[HAL status](../port-status-px4-hal.md) for current assessment. These captures
do not establish cold boot, physical actuator safety, or flight readiness.

## Payload builds and reset symbols

> The 2026-08-02 payload-image rebuilds also close deterministic startup
> command and MAVLink-shell defects. Required `mft`/`bsondump` commands are
> linked; absent RGBLED/PX4IO probes are disabled by board capability flags;
> `CONFIG_PIPES=y` selects NuttX `lib_pipe.o` instead of a board `ENOSYS`
> stub. An automatic post-build contract verifies both default and DShot
> label/nsh/CR8-0 resolution, linker, builtins, pipe object, undefined-symbol
> set, split image, `.px4` payload, reset configuration, and reset symbols.
> Every board build also runs the focused GPIO, GPT/PWM, GTM, SCI/SPI,
> OneShot/DShot, and SIH source contracts. Historical 2026-08-02 ELF SHA-256 values are
> default `6394a28f2c628737add5cf5ef4a195160aec34e0cdd2bd9559ee6f52f375e923`,
> DShot `6d81d2548b726ee79d58b9a0e8fb21c6e95c7aaf4db5c6281f3183b88e89a222`,
> SIH `214c0898b23680468cb9cff7710928be501f83c951817415e9fb17d608ab6248`,
> and core-only `bea463585efc0f68a11800dec6d53aab5b10a2b6ccebcc2873e7166b5f609302`.
> `board_reset()` is now wired through NuttX `up_systemreset()` to the CR8
> WDT2/WDT3 reset route, and `board_on_reset()` disconnects all four motor
> pins before a normal reset. All four historical ELFs contain the complete reset symbol
> chain. Exact-image cold boot, reset occurrence, post-reset startup, and
> inactive motor-pin scope proof remain target gates.

## SIH bounded runtime evidence

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
attributed to the historical 2026-08-02 SIH ELF
`214c0898b23680468cb9cff7710928be501f83c951817415e9fb17d608ab6248`.
Fresh SIH builds run the source and artifact contracts automatically
(11/11 + 12/12), and mandatory startup failures now terminate `rcS` instead
of falling through to a misleading success path. Exact load/cold-cycle provenance, SCI4 transport capture,
physical pin-safety measurements, transcript coverage gaps, and the 10-minute
resource/rate soak remain pending. See the
[archived target transcript](px4-nuttx-rzv2h-sih-transcript.txt). The goal-plan
evidence audit records the detailed provenance limits for the next authorized
target session.

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

## Retired core-only profile

Historical core-only note: the retired `renesas_rdk-rzv2h_core_only` was build-clean from
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

## DShot remediation evidence

**Validation:** The [remediation plan](../../../plans/261002-2129-rzv2h-dshot-runtime-remediation/plan.md)
links the source findings. Executed real-driver host tests model MMIO/cache
boundaries: [DMAC runner](../../../test/rzv2h-dmac-runtime-test.py) failed six of
11 tests before the fixes and now passes 11/11;
[DShot runner](../../../test/rzv2h-dshot-runtime-test.py) failed 21 of 23 tests
against the saved pre-fix driver and now passes 23/23.
[DShot red log](../../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dshot-runtime-before.log)
records the expanded-suite baseline (the initial 20-case suite failed 18).
[DMAC green log](../../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dmac-final-green.log)
and [DShot green log](../../../plans/261002-2129-rzv2h-dshot-runtime-remediation/reports/dshot-runtime-after.log)
record host model evidence, not physical timing proof. At the remediation checkpoint, the four August 2 builds were historical and
fresh DShot/default builds were pending. Consult the HAL status for later
software checkpoints. Logic-analyzer captures must still prove GPT-to-DMAC edge latency
under load, pulse widths, multi-channel launch skew, inactive outputs during
failures, repeated rearm, and ESC response. Cold boot also remains a target
gate. The [July 20 QA](../../../plans/reports/tester-260720-rzv2h-dshot-runtime-fixes.md)
and [review](../../../plans/reports/reviewer-260720-rzv2h-dshot-runtime-fixes.md)
are historical evidence and do not cover this remediation.
