# RZ/V2H board samples through RTT

The opt-in RDK CR8-0 samples use the existing `hwtest` builtin. Their
[executable manifest](../../../platforms/nuttx/Debug/rzv2h-sample-profiles.json)
owns profile names, exact case IDs, evidence classes, typed state and allowed
register reads. Board configurations live under
[`rdk-rzv2h/configs`](../../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs).

The separate [all-native inventory](../../../platforms/nuttx/Debug/rzv2h-all-sample-configs.json)
covers all 55 configurations. Use `rzv2h-sample-build.py --all-configs` for
that matrix and the guarded local executor described in the
[CI/lab procedure](rzv2h-regression-ci.md#execute-an-approved-local-board-batch).
It preserves the 14-profile interface below. The all-native inventory includes
external fixtures, serial and boot-only entrypoints; it does not imply those
images can all run on the same wiring or through an interactive RTT shell.

The [current machine snapshot](../../../plans/261022-1849-rzv2h-jlink-retry/all-sample-results.json)
records load and runtime state for the shipped configurations. Use its
[remaining actions](../../../plans/261022-1849-rzv2h-jlink-retry/remaining-samples.md)
for the next step; the [retry report](../../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md)
owns the repaired TMPFS and raw RTT pair observations. Fixture admission,
engineering handoff checks and prohibited-core routes remain distinct blockers.

These profiles use controller-internal modes or board-fitted resources. They
require no new peripheral cable/card/jumper. SCI UART/SPI and I2C samples check
routing/registration/ownership without exchanging data with an unattached
peripheral. SCIF, MAC and CPU-local IPC have separate byte oracles. PB4/PB5
LED tests restore their sampled output level after initialization; they do not
measure light. P94 stays owned by the existing SPI0 ICM20948 connection.

## Build and check

Use `platforms/nuttx/Debug/rzv2h-sample-build.py --output <new-archive>`
to build the manifest profiles sequentially in a disposable isolated copy and
archive their receipts. Repeat `--profile <name>` for selected profiles. The
builder calls the existing NuttX build script and preserves shared outputs.
See the [CI procedure](rzv2h-regression-ci.md) for regression groups, dependency
inputs and archived-image tests.
Archive `nuttx.elf`, `resolved.config`, `nuttx.map`, `System.map` and a
`build-receipt.json` with the profile, successful build exit, compiler and
SHA-256 of the ELF/config/link map. Bind each receipt to the archived
`source-state.json` SHA-256 and its PX4/NuttX/apps commits and compiler.
SCIF also retains the exact `libarch.a` and
its `rzv_scif.o` member with both hashes. The receipt binds those compiler
outputs; it is not target authorization.

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-artifact-check.py \
  --manifest platforms/nuttx/Debug/rzv2h-sample-profiles.json \
  --builds <archive-directory> --source-state <source-state.json> \
  --output <build-checks.json>
```

`BUILD-CHECKED` verifies the selected core, resolved configuration, actual
builtin entry, required case strings, linker input provenance and RTT symbol.
The SCIF `up_putc` implementation may be discarded by the linker because RTT
owns the console; the retained archive/map establish its unique provider.
The xSPI artifact must retain the compiled weak default `-ENOTSUP` denial.

Interactive profiles retain parent/child exit status for foreground NSH
commands. Controlled initialization defers selected board setup to the suite;
automatic LEDs/buttons, watchdog automonitor and unrelated peers remain off.
Ethernet disables NSH netinit and DHCP. SDHI excludes MMCSD/FAT upper halves.

## Target execution and evidence

Obtain approval for the exact CR8-0 ELF/hash and its declared driver operations
before loading or initializing it. Use the repository J-Link preflight,
single-core loader and RTT bridge; stop on unexpected reset/connect-failure
markers. Never attach CM33. A current build does not identify the loaded image.

Run `hwtest` in the foreground. Capture unique bare `RUN_BEGIN: <id>` and
`RUN_END: <id>` markers around the invocation, terminal result and returned
prompt. After completion, issue a separate `ps` and health capture. Keep the
bridge/process/port cleanup receipt separate from driver state.

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-runner.py \
  --manifest platforms/nuttx/Debug/rzv2h-sample-profiles.json \
  --profile <profile> --transcript <rtt.log> --health <health.log> \
  --receipt <run-receipt.json> --output <result.json>
```

Required FAIL/SKIP/missing IDs, stale boundaries, wrong counts, nonnumeric IRQ
counters, missing task/prompt proof, errors or incomplete cleanup cannot pass.
A timeout leaves execution unresolved; it does not cancel a task.

SDHI requires a reviewed clock/reset handoff before lower initialization.
Ethernet MAC and SCIF function runs require clock/pad ownership and declared
output behavior; byte equality does not establish physical output suppression.
WDT reads always-on SYSC `bp_halted` before enabling its clock and refuses an
uninhibited counter. It never calls START/STOP/feed to create a precondition.

Registered lower halves, netdevs, initialized DMAC units, SGI15 and the matching
TMPFS mount have profile lifetime. Per-case descriptors, queues, work and loop
state must be cleaned. `/dev/ipcc4` in `ipc-local-loopback-rtt` is a separate
non-SMP, CPU-local SGI device; it has no MHU peer or shared DDR ring. It does not
qualify the existing multi-core IPC links. Parameter samples write no file data;
xSPI persistence remains denied. The TMPFS guard pins the mount through the
opened directory's `fd_root`, since NuttX uses a wrapper inode for directory
file descriptors. An existing `/fs` mount may return `ENOTDIR` from
`nx_mount`; initialization accepts it only after verifying TMPFS identity.

The [2026-10-22 hardware retry](../../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md)
passes all three TMPFS guards on the exact rebuilt image: stable identity,
idempotent mount, zero data writes and zero retained case descriptors.

A source review/build/guard result does not promote peripheral function.
Qualification remains owned by the
[driver status matrix](../port-status-nuttx.md), with named target transcripts.
