# NuttX Driver Porting Playbook

**Status:** Source and build workflow; physical qualification is a separate gate
**Audience:** Contributors porting RZ/V2H FSP drivers or related board glue to NuttX

This is the contributor route for a new RZ/V2H driver. It records the decisions
that a port must preserve and points to the source, build, coding, and evidence
owners. It does not replace the NuttX upper-half contract, the selected FSP
project, or a board validation report.

## 1. Establish the comparison contract

Start with the [reference source map](./reference-source-map.md). Resolve the
sample, silicon view, core, and known exceptions before reading generated FSP
output. Use the mapped core-matched EVK project or the recovered RDK reference
where the map says it is authoritative. A nearby IP block is supporting
evidence only: SCI-B, SCIF/SCIFA, SPI-B, and RSPI must not be silently treated
as interchangeable.

Record the exact source paths used for the comparison, including the selected
`configuration.xml`, FSP implementation and configuration, generated HAL/vector
or pin output when available, and CMSIS headers. If generated output or
schematic evidence is absent, record that as a later physical-qualification
input. Do not invent a base address, IRQ, DMA event, pin, or clock value to fill
the gap, and do not turn a missing physical artifact into a source/build gate.

For the RDK sensor-extension work, retain the native default and existing
GY-912/simple P93 CS/P94 DRDY profiles. The configurable extension remains
explicitly selected and default-off; its software can be source/build reviewed
from the selected XML while physical use waits for board corroboration.

Before implementation, write a short task input containing:

- driver or subsystem, target core, board/profile, and intended boundary;
- source-map entry and exact reference paths, including labelled gaps;
- NuttX source/header/board/config files in scope;
- invariants to preserve: clock/reset, pin ownership, IRQ routing, cache/DMA,
  concurrency, error cleanup, and compatibility profile;
- evidence requested: source review, host/build result, or named on-target gate;
- files allowed to change and the rollback point.

Keep this task input with the work record so source choices and requested
evidence remain reviewable.

## 2. Derive the hardware contract

The hardware header belongs under
`platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/`. Derive register
bases, offsets, access rules, masks, CPG/reset IDs, ELC events, and interrupt
identifiers from applicable CMSIS, manual, and FSP evidence. Follow the layout
of the nearest current header and use NuttX register access helpers. Do not seed
the file with illustrative addresses or IRQ values.

Cross-check the selected core and silicon view. Pin alternate functions come
from board IOPORT/PFC configuration and the selected profile, not from ICU
routing tables. Confirm ownership against [pinmap.md](./pinmap.md) and the
profile's defconfig; flag a conflict instead of choosing a convenient pin.

The header and driver should make the following contract reviewable from their
own owners:

1. the module clock is enabled before peripheral access;
2. the documented module reset path is released before configuration;
3. board pin setup is applied for the selected instance;
4. peripheral state is initialized while delivery is masked or otherwise safe;
5. the actual ICU/GIC route is attached through the architecture's current API;
6. the peripheral and CPU interrupt sources are enabled at their required
   points; and
7. every failure unwinds resources in the reverse order and reports its error.

Do not infer one registration or return contract from another subsystem. A
lower-half factory may return a device pointer, while another initializer or
registration function returns a status. Read the selected upper-half interface
and its current RZ/V2H exemplar first. Useful exemplars are
`rzv_gpt.c`/`rzv_gtm.c` for timer lower halves, `rzv_spi.c` for a bus lower
half, and `rzv_serial.c` for the UART framework.

## 3. Preserve driver safety invariants

Apply these invariants to the selected driver and its actual upper-half API.

### Interrupts

An ISR reads the status needed to identify its event, clears the peripheral or
interrupt source it owns according to that IP's contract, records bounded state,
and returns through the NuttX architecture path. It must not block, allocate,
or format ordinary diagnostic output. Defer work that can block or take a
mutex to the work queue or task context selected by the subsystem.

There is no universal manual ICU or GIC acknowledgement sequence. The selected
architecture route may clear or acknowledge delivery for the driver. Add a
driver-specific acknowledgement only when the current architecture/IP contract
requires it, and verify that it does not double-clear the source. Configure
edge/level behavior and enable each line using the route's owning API; do not
copy an IRQ recipe from another core or peripheral.

### DMA and cache

Use the current DMAC interface in
`platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.h`. Prove source and
destination addressability, transfer width, length, channel ownership, trigger
route, buffer lifetime, and cleanup. For cached CR8 DMA, the live interface
uses `up_clean_dcache()` for memory written before a DMA read and
`up_invalidate_dcache()` before the CPU consumes DMA-written memory. Respect the
address range and alignment requirements of the actual transfer and its owner.

The DMAC implementation currently owns the cache calls for its configured
transfers in the paths that support them. A peripheral driver must still prove
that its buffer lifetime and any CPU reuse satisfy that interface. Keep one-shot
and hardware-triggered transfers distinct, and validate every enabled consumer
separately. A memory-copy example does not prove serial, SPI, I2C, or DShot
operation.

### Reset and timing

Use the current `rzv_clock_enable()`, `rzv_module_unreset()`, and matching
disable/uninitialize paths where the driver owns them. Apply any documented
power-up or register read-back delay from the selected IP evidence; do not add a
generic sleep as a substitute for a hardware contract. Shutdown must quiesce
active transfer/interrupt state before disabling the clock. Reset behavior,
inactive motor-pin levels, and warm-reset independence are profile-specific
acceptance gates, not assumptions from a clean build.

### Errors and shared state

Return initialization, attach, configuration, and transfer failures to the
caller. Use assertions for programmer invariants and normal logging for
recoverable failures in task context. Protect a register read-modify-write
shared with an ISR using a bounded critical section and restore the saved
interrupt state. Protect task-to-task or task-to-work-queue state with the
subsystem's mutex/semaphore contract. Keep per-instance state separate and make
idempotence or duplicate initialization explicit when the upper-half can call
the entry point more than once.

## 4. Wire the board and configuration

Standalone NuttX board glue belongs in
`platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/`; PX4-only adapters
remain under `boards/renesas/rdk-rzv2h/src/`. Add Kconfig and source selection
only where the driver is actually owned, and keep the option default-off unless
the profile contract explicitly selects it. The board registration must use the
selected subsystem's real lower-half and upper-half APIs.

Use `rzv2h_timer.c` as a concrete lower-half registration example: it checks the
timer factory result, registers the returned lower half, and uninitializes it
when registration fails. This pointer/`NULL` lifecycle is an example for that
interface only; do not generalize it to status-returning registrations.

Keep the sample config minimal and explicit about the target core, driver
option, board pins, console, and debug evidence needed for the test. Do not
copy a full defconfig or hand-maintain a list of all configurations here. The
machine-owned list is exposed by `platforms/nuttx/NuttX/build.sh --list`.

## 5. Build and review

Use [deployment-guide.md](../deployment-guide.md) for current PX4/NuttX build,
artifact, RTT, RAM-load, and J-Link procedures. It owns command details and
approval boundaries. In particular, J-Link reset, image load, and target memory
writes require explicit user approval; a read-only attach is the default.

The narrow software loop is:

1. run the selected source/header and configuration checks;
2. run the named NuttX or PX4 build through its owning script;
3. inspect the link/source-selection result and the expected symbols;
4. run the focused host contract or example test when one exists; and
5. hand the remaining physical checks to the per-driver validation record.

A clean build or host test establishes its own evidence tier only. It does not
prove pin electrical behavior, IRQ delivery, DMA coherency on hardware, reset
behavior, persistence, per-unit identity, or an integrated PX4 path.

Before review, check:

- source authority and any `(gap)` are named;
- clock/reset, pin, IRQ, upper-half, and cleanup contracts are traced to code;
- ISR source ownership and deferred work are justified for the actual IP;
- DMA cache, address, width, channel, and trigger assumptions are explicit;
- failure paths undo resources and return meaningful errors;
- Kconfig and source selection agree with board wiring;
- formatting, comments, and commit conventions follow [code-standards.md](../code-standards.md); and
- the result is labelled with the strongest observed evidence tier.

## 6. Validation handoff

Copy [validation-checklist.md](./validation/validation-checklist.md) for the driver and
link the completed record from the appropriate row in
[port-status-nuttx.md](./port-status-nuttx.md). Keep source/build review,
host tests, and named board transcripts separate. A status row may not advance
past the strongest evidence actually captured.

The checklist is context-sensitive: select only the DMA, power, timing,
concurrency, and reliability checks that the driver contract requires, while
retaining all applicable failure and recovery checks. Do not convert a generic
stress loop into a blanket gate. The P94 TINT retest remains tied to its named
`nsh-leds` image and its own register, edge, transcript, and provenance gates.

For hardware work, record the exact artifact hash, core, board revision, load
and reset provenance, console transcript, and any register or analyzer capture.
Keep the board owner approval boundary visible in the report. A missing passing
transcript or physical artifact is an open gate, not a reason to claim a
production result.

## Related owners

- [Reference source map](./reference-source-map.md) — comparison provenance and gaps.
- [FreeRTOS/POSIX to NuttX mapping](./freertos-to-nuttx-mapping.md) — semantic migration aid.
- [Code standards](../code-standards.md) — formatting, naming, comments, and commits.
- [Deployment guide](../deployment-guide.md) — build, artifact, RTT, and debug procedures.
- [Validation checklist](./validation/validation-checklist.md) — per-driver evidence record.
- [Port status](./port-status-nuttx.md) — status tier and validation-report owner.
- [Hardware](./hardware.md) and [pin map](./pinmap.md) — board-level contracts.
