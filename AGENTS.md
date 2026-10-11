# AGENTS.md — RZ/V2H PX4 + NuttX Port

Tool-neutral guide for AI agents (Claude Code, Codex, Cursor, ...). Read this
first, then open only the doc you need from the map below.

Project: PX4 Autopilot fork porting PX4 + NuttX to the Renesas RDK-RZ/V2H
(R9A09G057H). Primary flight core is **Cortex-R8 core 0 (CR8-0)**. CR8-1 and
CM33 act as IO cores over IPC. RA8E1/RA8P1 targets also exist but are not the
focus here.

## 1. Where code lives

| What | Path |
|------|------|
| NuttX arch drivers (RZ/V) | `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/` (submodule) |
| NuttX board + defconfigs | `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/{src,configs}/` |
| NuttX apps (submodule) | `platforms/nuttx/NuttX/apps/` |
| PX4 platform HAL (RZ/V) | `platforms/nuttx/src/px4/renesas/rzv/` (hrt, dshot, io_pins, board_reset, ...) |
| PX4 boards | `boards/renesas/rdk-rzv2h/` (CR8-0), `rdk-rzv2h-io-cr8_1/`, `rdk-rzv2h-io-cm33/` |
| Debug / RTT / SVD tools | `platforms/nuttx/Debug/` (`rzv2h-ipc/` holds IPC HIL scripts) |
| Host contract tests | `test/rzv2h_*` (python3 / bash, run directly) |
| Register map (CMSIS-SVD) | `rzv2h.svd` (repo root) |
| Plans / agent reports | `plans/`, `plans/reports/` |

Both NuttX submodules track the OneKiwiTech GitLab forks: `nuttx` on branch `nuttx_ra_rzv`, `apps` on `main`.
Commit driver changes inside the submodule first, then bump the pointer.

**Upstream content you can ignore** (stock PX4/NuttX files, do not edit for port work):
`docs/README.md`, `docs/index.md`, `docs/en|ko|zh|uk/` (the PX4 User Guide site),
and `platforms/nuttx/NuttX/nuttx/README.md` (stock NuttX README).

## 2. Build — two different scripts

| Goal | Command (from repo root) | Output |
|------|--------------------------|--------|
| Full PX4 firmware | `./build.sh renesas_rdk-rzv2h_default` (`--list` for all targets, `--no-clean` to iterate) | `build/<target>/<target>.elf` |
| NuttX only (driver bring-up, NSH samples) | `platforms/nuttx/NuttX/build.sh <config>` | `platforms/nuttx/NuttX/nuttx/nuttx` (ELF), `.bin`, `.hex` |
- PX4 targets: `renesas_rdk-rzv2h_{default,core_only,sih,dshot}`, `renesas_rdk-rzv2h-io-cr8_1_default`, `renesas_rdk-rzv2h-io-cm33_default`.
- PX4 targets: `renesas_rdk-rzv2h_{default,core_only,simple,sih,dshot}`, `renesas_rdk-rzv2h-io-cr8_1_default`, `renesas_rdk-rzv2h-io-cm33_default`.
- `simple` is the isolated RTT PWM + ICM20948 accel/gyro bench profile; see `docs/renesas/simple-pwm-icm20948-validation.md`. Retired core-only resources/evidence remain historical.
- NuttX configs: `platforms/nuttx/NuttX/build.sh --list` (e.g. `nsh-rtt`, `nsh-scif`, `ipcc`, `adc`, `canfd`, `hil-full`). `--no-clean <config>` rebuilds the same config incrementally. Exit codes: 0 ok, 1 build failed, 2 bad usage.
- Never hand-run `tools/configure.sh` + `make`; the scripts handle distclean and stale arch symlinks.
- First-time setup: `source ./build_setup.sh` (checks deps, scrubs e2studio `CMAKE_*` env vars, inits submodules).

## 3. Run and debug on hardware

- Console is **SEGGER RTT**, not UART (SCI4 shell only in `nsh`/`nsh-scif` style configs).
- RTT: `JLinkGDBServer` **cannot** bridge RTT on CR8. Use `platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 <elf>`
  (JLinkExe attaches without reset, serves channel 0 on `127.0.0.1:19021`), then send NSH commands with
  `platforms/nuttx/Debug/nsh_console_exec.py`. Stop the bridge before starting a GDB session (one probe, one owner).
- Discover `_SEGGER_RTT` from the exact loaded ELF; historical defaults are CR8-0 `0x081A0000`, CR8-1 `0x081E0000`. J-Link devices: `R9A09G057H44_R8_0`, `_R8_1`.
- Register decode: `platforms/nuttx/Debug/svd_register_tool.py --svd rzv2h.svd ...`.
- Skills: `gdb-jlink-debug` (J-Link/GDB/RTT/SVD workflows), `audit-rzv2h-px4-nuttx-port` (cross-layer audit), `firmware-audit`.
- J-Link reset, ELF load, and target memory writes need explicit user approval.

## 4. Reference sources (`refs/`, local only)

`refs/` is gitignored (~1 GB). It may be missing on a fresh clone; ask the user instead of guessing.

| Path | Content |
|------|---------|
| `refs/px4-freertos-posix-renesas-fsp/` | Working PX4-on-FreeRTOS port for CR8-0 on the **RDK** board (FSP config; `rzv_gen/pin_data.c` is the RDK pin authority, but it does not configure every peripheral, e.g. CAN/ADC: then use the RDK schematic) |
| `refs/rzv2h_evk/<periph>/<periph>_rzv2h_evk_{cm33,cr8_0,cr8_1}_ep/` | Renesas FSP example projects per peripheral, **per core**, for the **EVK** board (not RDK). Use them for IP behavior (registers, clocks, IRQ/ELC); never take pins from their `pin_data.c`. |
| `refs/rzv2h_gb_ether/` | GbEther driver reference |
| `refs/rzv2h_scripts/` | Pinmap / ELC / CMSIS-header generators, `rzv2h_pin_mapping.csv` |

Evidence precedence and per-driver source picks: `docs/renesas/reference-source-map.md`.

## 5. Evidence rules

- Status tiers: stub → source-audited → build-clean → bounded on-target → production
  (defined in `docs/renesas/port-status-nuttx.md`).
- A clean build, RTT output, or a static register comparison is **not** on-target proof. Do not promote a driver
  without a named board transcript.
- Update `docs/renesas/port-status-nuttx.md` / `port-status-px4-hal.md` when a driver's status changes.

## 6. Doc map

| Need | Doc |
|------|-----|
| Port index | `docs/renesas/README.md` |
| Add/port a driver (FSP → NuttX) | `docs/renesas/porting-playbook.md`, `docs/renesas/freertos-to-nuttx-mapping.md` |
| Driver status | `docs/renesas/port-status-nuttx.md`, `docs/renesas/port-status-px4-hal.md` |
| Hardware, clocks, memory, pins | `docs/renesas/hardware.md`, `docs/renesas/pinmap.md`, `docs/renesas/multicore-memory-map.md` |
| Multi-core IPC | `docs/renesas/ipc-architecture.md`, `docs/renesas/rzv2h-ipc-hil-test-guide.md` |
| Validation checklist | `docs/renesas/validation-checklist.md` |
| Simple PWM + ICM bench | `docs/renesas/simple-pwm-icm20948-validation.md` |
| Driver design / coding rules | `docs/design-guidelines.md`, `docs/code-standards.md` |
| Architecture, build/flash/debug | `docs/system-architecture.md`, `docs/deployment-guide.md` |
| Scope, roadmap, code tour | `docs/project-overview-pdr.md`, `docs/project-roadmap.md`, `docs/codebase-summary.md` |
| Reusable prompts | `docs/renesas/prompt-recipes.md` |
| Past incidents and lessons | `docs/journals/` |
| Active plan | `plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md` |

## 7. Conventions

- PX4 code: PX4 style (`make format`). NuttX submodule: NuttX style (`tools/checkpatch.sh`). See `docs/code-standards.md`.
- Conventional commits, no AI attribution. New files: kebab-case.
