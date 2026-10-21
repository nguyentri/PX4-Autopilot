# RDK-RZ/V2H System Architecture

**Status:** Source-backed reference; CR8-0 active, multicore opt-in

This document records the current boundaries and durable decisions for the
RZ/V2H PX4/NuttX port. Source, board manifests, status tables, and the
deployment guide own implementation details, evidence, and run procedures.

## 1. Architecture Stack

```text
PX4 modules
  -> PX4 HAL / board startup
  -> NuttX RTOS
  -> RZ/V2H board and driver layer
  -> RZ/V2H hardware
```

The CR8-0 board path is the active PX4 target. CR8-1 and CM33 remain deferred
multicore targets; their standalone images are available for separate IPC
work. The default CR8-0 image remains independent of CA55/Linux, CR8-1, CM33,
OpenAMP, and IPCC.

The project outcome is a source-backed PX4 flight path on CR8-0 under NuttX,
with the board pinmap, HAL, sensors, actuators, telemetry, parameters, and
logs qualified in the evidence tiers used by the port status documents. The
opt-in `renesas_rdk-rzv2h_drone` profile carries the recovered RDK sensor
extension; default, simple, SIH, DShot, and standalone NuttX profiles remain
separate compatibility surfaces.

CA55/Linux integration, RPMsg/OpenAMP as a default dependency, wireless and
video features, and production flash/cold-boot claims are outside the current
CR8-0 contract. ADC, SDHI/ULog, CAN-FD, Ethernet, WDT, and DShot remain
optional or post-drone qualification paths according to the active plans and
status tables.

## 2. Core Roles

| Core | Current role | Evidence state |
|---|---|---|
| CR8-0 | Primary flight stack, board bring-up, diagnostics | Active target |
| CR8-1 | I/O co-processor / PX4IO-style expansion | Deferred |
| CM33 | Alternate I/O or safety companion | Deferred |

## 3. Canonical Addressing

Use [multicore-memory-map.md](./renesas/multicore-memory-map.md) for the exact CR8-0,
CR8-1, and CM33 aliases. That document is the single source of truth for:

- CR8 private TCM views.
- DDR aliases per core.
- Shared DDR carveouts.
- CM33 secure / non-secure addressing.
- Loader and boot parameter placement.

This summary only keeps the high-level contract: shared-memory and boot-address
details are not duplicated here.

## 4. IPC and Multicore Contract

IPC is opt-in. The default PX4, simple, SIH, and drone images keep OpenAMP and
IPCC disabled; standalone CR8-1/CM33 images and NuttX IPC configurations are
separate validation surfaces. A raw NuttX IPC transcript therefore does not
promote PX4 multicore integration.

The [IPC architecture](./renesas/ipc-architecture.md) owns transport and
application-protocol boundaries. Shared dual-core application logic (wire codecs, lease enforcement, atomic snapshots, output workers, battery translation, and intent gateway) is implemented in [`src/apps/`](../src/apps/) under the `rzv2h_demo` library. Helper symbols and linker carveouts do not
establish an enabled runtime link.

## 5. PX4 Board Layout

The [board root](../boards/renesas/rdk-rzv2h/) owns named `.px4board`
manifests, NuttX configurations and startup selection. Use the
[codebase map](codebase-summary.md) for implementation boundaries and
`./build.sh --list` for active targets. Retired core-only resources are
historical; `simple` is the compact PWM/ICM20948 bench profile.

## 6. Build Flow

PX4 and standalone NuttX builds share the same NuttX tree, so profile builds
must run sequentially. The [deployment guide](deployment-guide.md) owns
configuration, artifact and target-operation procedures. A clean build does
not qualify cold boot, persistence or multicore traffic.

## 7. Related Documentation

- [Hardware](./renesas/hardware.md)
- [NuttX Port Status](./renesas/port-status-nuttx.md)
- [PX4 HAL Port Status](./renesas/port-status-px4-hal.md)
- [IPC Architecture](./renesas/ipc-architecture.md)
- [Multicore Memory Map](./renesas/multicore-memory-map.md)
- [NuttX Porting Playbook](./renesas/porting-playbook.md)
- [Active reference-port plan](../plans/261011-2017-rzv2h-drone-reference-port/plan.md)
- [Broader port goal plan](../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)

## 8. Qualification boundary

Driver and HAL status tables own demonstrated readiness. Intended customer
architecture in [marketing/](renesas/marketing/README.md) has a different
scope: its CM33 exclusion does not remove the repository's optional CM33
sample. No production or flight qualification is implied by either design.
