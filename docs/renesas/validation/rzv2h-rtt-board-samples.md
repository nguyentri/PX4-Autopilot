# RZ/V2H board samples through RTT

The opt-in RDK CR8-0 samples use the existing `hwtest` builtin. Their
[executable manifest](../../../platforms/nuttx/Debug/rzv2h-sample-profiles.json)
owns profile names, exact case IDs, evidence classes, typed state and allowed
register reads. Board configurations live under
[`rdk-rzv2h/configs`](../../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs).

The separate [all-native inventory](../../../platforms/nuttx/Debug/rzv2h-all-sample-configs.json)
owns the current configuration set. Use `rzv2h-sample-build.py --all-configs`
for that machine-owned matrix and the guarded local executor described in the
[CI/lab procedure](rzv2h-regression-ci.md#execute-an-approved-local-board-batch).
The all-native inventory includes
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

## Per-instance coverage

The [driver catalogue](../../../platforms/nuttx/Debug/rzv2h-driver-coverage.json)
records hardware domains, implemented paths, profile bindings and open gates.
Fixed profiles inspect RIIC0–8, SPI0–2, SCI-I2C0–9, SCI-SPI0–9 and both A/B
outputs of logical GPT0–15 (physical GPT0–7/10–17), GBETH0/1, SDHI0–2 and
WDT0–3. Select them with
`--all-configs --profile riic8-board-rtt`, for example. They require controlled
initialization and emit required guard/identity/stability cases plus actual driver identity and
family/unit/channel/output state. Native SPI profiles additionally compare a
varied byte pattern through the selected controller’s internal loopback.
GPT identity inspection does not start PWM.
`ether0-board-rtt` and `ether1-board-rtt` each select exactly one MAC and
disable automatic network initialization. Their three generic instance cases
inspect actual identity/base/interface with no DMA, loopback, PHY writes,
queued work or attached IRQs. They preserve the legacy MAC0 case grammar.
Registration requires the declared Ethernet parent-clock handoff; it does not
establish a working PHY, physical link or traffic path.

`sdhi0-board-rtt` through `sdhi2-board-rtt` query the selected lower half after
the declared handoff, without MMCSD/FAT or media probing. Identity checks
require masked interrupts, no attached IRQ, pending transfer, watchdog or
semaphore waiter. These profiles use the current CR8-only SDHI path.
`wdt0-board-rtt` through `wdt3-board-rtt` enable exactly one watchdog selector.
They read its always-on inhibition state before registration and require
zero start/feed calls both before and after it. Counting inhibition must
already exist; the test does not create it. Each watchdog's core/domain
ownership remains an independent prerequisite.
These checks establish controller selection and stable ownership; SPI loopback
adds an internal byte comparison. External
transfers, waveforms and physical pad routing require separate evidence.

Unassigned RIIC/SCI/SPI board routes remain denied in normal initialization.
SCI UART pads supplied by an earlier stage require the explicit default-off
`CONFIG_RZV2H_SCI_UART_PRECONFIGURED` option. Native RIIC7 and SCI7-I2C cannot
both register bus7; native and SCI SPI cannot both register buses0–2. Duplicate
registration is a build/admission error without renumbering existing buses.

The DMAC memcpy policy covers all 80 channels through bounded command batches
with exact per-channel comparison and completion.

The catalogue keeps registration, internal function, external function,
electrical, cold-state and stress evidence separate. Missing/unsupported cells
and required-case skips never become passes. Existing ADC/CAN/DMAC/GPIO/GTM/
HRT/POEG/WDT/IPC domains and header-only IP remain explicit; a profile count is
not a hardware-channel coverage percentage. SCI SPI/I2C behavior is checked
against the [official hardware manual](../reference-source-map.md#sci-b-mode-authority).
Both MACs retain explicit pad/parent-clock handoff gates. Expanded RDK routes
and physical qualification remain open.

SCI-I2C rate requests are ceilings under the manual's minimum pulse/SDA-delay
rules. At nominal P5CLK=100MHz, the 400kHz request selects 260,416Hz; 100kHz
selects 97,656Hz. See the [timing policy](../port-status-nuttx.md#sci-i2c-timing-policy)
before comparing throughput or measured waveforms. These calculations do not
qualify a board route or fixture.

The completed [sensor-free RTT validation record](../evidence/sensor-free-rtt-validation-261024.md)
and [machine matrix](../evidence/sensor-free-rtt-matrix-261024.json) are the
current campaign evidence. They account for 92 PASS, 2 NOT-PASS, 6 BLOCKED and
28 OUT-OF-SCOPE entries within the 128-entry run. The admitted checks are
limited to registers, ISR delivery and internal functions; no sensors, PWM
waveforms or production qualification are implied. Both GBETH units remain
supported, with matching-core I/O headers taking precedence where present.

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
Native archives retain and hash all three policy inputs: selected manifest,
legacy case contract and driver catalogue. Admission and resume reject missing
or changed inputs; those archived contracts do not authorize hardware actions.
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

An RTT syslog console routes ARM early diagnostics through RTT even when
`RZV_DIAGNOSTICS_RTT` is not explicitly enabled. This keeps boot progress
independent of the SCI3 fallback and its inherited UART/SPI/I2C state. The
explicit diagnostic option still selects RTT for builds with a serial console.
Output-only RTT loggers also own early diagnostics when no serial console is
selected; they do not depend on an inherited fallback SCI configuration.

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
