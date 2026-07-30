# RDK-RZ/V2H Port Roadmap

**Date:** 2026-07-30

**Scope:** RDK-RZV2H PX4-on-NuttX, CR8-0 first
**Canonical plan:** [RDK-RZV2H PX4 NuttX Port Goal Plan](../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)

This file is the roadmap summary. The canonical plan owns detailed phases,
matrices, commands, exit criteria, risks, and evidence requirements.

## Goal

Run PX4 drone software on RDK-RZV2H CR8-0 under NuttX with the FSP-backed
pinmap, required HAL, sensors, actuators, MAVLink, parameters, and logs.
CR8-1 and CM33 stay deferred until CR8-0 is stable.

## Milestone Overview

| ID | Status | Deliverable | Hard gate |
|---|---|---|---|
| G0 | Partial | Baseline authority and evidence vocabulary frozen | Cold/debugger boot authority and board revision remain open |
| G1 | Static audit complete; authority pending | Pinmap and all 23 sample configs audited | P52/P97/PA6 schematic ownership remains open |
| G2 | Build-clean | NuttX samples corrected and classified | Required config builds and runtime procedures |
| G3 | Pending | Required blocked drivers closed or accepted fallback | SCI7, GTM7 HRT, SPI0, GPIO/IRQ, GPT PWM |
| G4 | Pending | PX4 HAL dependency closure | Matching NuttX sample proof per required HAL |
| G5 | Build-clean | CR8-0-only PX4 board image | No fatal CR8-1/CM33/CA55/OpenAMP dependency |
| G6 | Pending | PX4 boot, RTT shell, HRT, work queues, uORB | Stable local CR8-0 core |
| G7 | Pending | IMU, barometer, GPS, LiDAR, MAVLink | GPS SCI9 115200 8N1, topics update, QGC heartbeat |
| G8 | Pending | RC, four PWM outputs, arming/disarming, failsafe | RC SCI6 100000 8E2 + inversion, scope, safe inactive state |
| G9 | Pending | CR8-0 drone-equivalent bench run | GPS/RC remain clean under load; params persist; estimator/control bench path |
| G10 | Pending | Reliability and stress validation | Boot/timing/failsafe/memory/long-run evidence |
| G11 | Deferred | Optional CR8-1/CM33 multicore expansion | G9 plus required G10 subset |

Current on-target evidence is narrower than the roadmap: standalone CR8-0
`nsh-rtt` reaches a working SCI4 shell with RX/TX interrupts and RTT
diagnostics. The bounded SIH transcript adds interactive shell use, one
GTM7-backed HRT callback test, work-queue execution, and simulated PX4 topics.
That evidence does not promote physical payload/sensor buses or the integrated
PX4 HAL.

## Engineering Evidence Loop

Every RZ/V2H roadmap slice uses the same skill sequence:

1. `$audit-rzv2h-px4-nuttx-port <subsystem> <CR8_0|CR8_1|CM33>` establishes FSP/CMSIS, NuttX, board, PX4, and consumer scope.
2. `$ck:debug <symptom>` proves root cause for a build or runtime failure.
3. `$gdb-jlink-debug` captures source, MMIO, and exception evidence on target when static tracing is insufficient; reset/load/write actions require authorization.
4. Implement and run the narrowest relevant build or on-target validation.
5. `$ck:code-review --pending` checks the diff against the audited trace before the status matrix advances.

The local skill definitions are [audit](../.claude/skills/audit-rzv2h-px4-nuttx-port/SKILL.md),
[J-Link debug](../.claude/skills/gdb-jlink-debug/SKILL.md),
[debug](../.claude/skills/ck-debug/SKILL.md), and
[code review](../.claude/skills/ck-code-review/SKILL.md).

## CR8-0 Critical Path

### Source and sample truth

- FSP `pin_data.c` and generated peripheral config define reference-used pins
  and instances.
- Standalone CR8-0 samples use SCI4 shell + RTT diagnostics or RTT-only HIL.
- SCI3 is not an active RDK console.
- Board Make/CMake source-selection parity must be fixed.
- CR8-1 SCI5 and CM33 SCI9 standalone configs may be statically corrected, but
  runtime multicore work remains G11.

### Required NuttX foundations

| Area | Required first-drone proof |
|---|---|
| Startup/MPU/CPG | Repeatable boot, accessible peripheral MMIO, no pre-SCI UART logging |
| Serial | SCI4/5/6/9 RX/TX/error handling; GPS SCI9 115200 8N1; RC SCI6 100000 8E2 plus inversion proof |
| GPIO/IRQ | P50 DRDY event, bounded latency, clean re-enable |
| SPI | SPI0 loopback plus MPU9250 WHOAMI/burst/DRDY |
| I2C | SCI7 simple-I2C on P76/P77 plus BMP280 repeated reads/recovery |
| HRT | GTM7 runtime P1CLK, monotonicity, callbacks, jitter/drift |
| PWM | GPT6A/7B/9A/10B on PA4/PA7/P96/P53; safe inactive state |
| Parameters | Proven xSPI partition/mount/save/reboot/load |

### Conditional and optional paths

| Area | Roadmap decision |
|---|---|
| ADC | Post-G9/non-gating. Disabled in the first image; no active driver in the checked-in drone reference. |
| WDT | Post-G9/non-gating. Automatic NuttX sample only; no first-run command-registration requirement. |
| SDHI | Post-G9/non-gating. ULog disabled; separate from required xSPI parameter storage. |
| CAN-FD | Optional for first drone run. Needs board transceiver/pin/analyzer proof. |
| Ethernet/PHY | Optional. SCI5 MAVLink is the first QGroundControl path. |
| DMAC | PIO accepted where it meets first-run timing; DMA needs coherency/request proof. |
| DShot | Opt-in only; standard PWM is the first actuator path. |
| SCIF/SCI-SPI | Sample-only; not a shipping-console or sensor blocker. |
| OpenAMP/IPCC | G11 only; absent or non-fatal in the default CR8-0 image. |

## Integrated PX4 Ownership

| Function | Assignment |
|---|---|
| Console/debug | RTT0 |
| LiDAR | SCI4 `/dev/ttyS4` |
| MAVLink/QGroundControl | SCI5 `/dev/ttyS5` |
| RC/SBUS | SCI6 `/dev/ttyS6` |
| GPS | SCI9 `/dev/ttyS9` |
| IMU | SPI0 P90/P91/P92/P93, DRDY P50 |
| Barometer | SCI7 simple-I2C P76/P77 |
| HRT | GTM7 |
| PWM1-4 | GPT6/7/9/10 on PA4/PA7/P96/P53 |

## Dependency Graph

```text
G0 authority
 -> G1 pin/config audit
 -> G2 sample correction
 -> G3 required NuttX driver proof
 -> G4 required PX4 HAL proof
 -> G5 CR8-0 board image
 -> G6 PX4 core boot
 -> G7 sensors + MAVLink
 -> G8 actuator + safety
 -> G9 drone-equivalent bench run
 -> G10 reliability/stress
 -> G11 optional CR8-1/CM33
```

Optional drivers may proceed when resources allow, but cannot replace a missing
hard-gate proof or move multicore work ahead of G9/G10.

## Status Tracking

Use evidence tiers from the canonical plan:

1. configured;
2. build-clean;
3. hardware-ready;
4. on-target functional;
5. PX4-integrated;
6. stress-validated.

Update weekly during active work:

- [NuttX Port Status](renesas/port-status-nuttx.md)
- [PX4 HAL Port Status](renesas/port-status-px4-hal.md)
- milestone evidence under the canonical plan's `reports/` directory

Missing target evidence is **needs on-target validation**, not done.

## Key Risks

| Risk | Mitigation milestone |
|---|---|
| Boot/debugger state masks missing startup setup | G0-G2 boot-mode matrix |
| Pin or serial ownership conflict | G0-G2 source freeze and config audit |
| SCI7 routed through RIIC or absent | G3-G4 SCI7 hard gate |
| GTM0/GTM7 or hard-coded clock drift | G3-G4 GTM7/runtime P1CLK |
| Unsafe PWM state | G4-G8 scope boot/disarm/reset/process failure |
| Parameter/log storage conflation | G4-G10 require xSPI params; keep SDHI/ULog disabled |
| Optional IPC blocks CR8-0 | G5-G6 no fatal OpenAMP dependency |
| Multicore complexity starts early | G11 hard dependency on G9/G10 |

## Related Docs

- [Canonical Goal Plan](../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
- [RZ/V2H Documentation Index](renesas/README.md)
- [Pin Ownership](renesas/pinmap.md)
- [Validation Checklist](renesas/validation-checklist.md)
- [System Architecture](system-architecture.md)
- [Deployment Guide](deployment-guide.md)
