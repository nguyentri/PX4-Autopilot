# Per-Driver Validation Checklist

Use this checklist with the [porting playbook](../porting-playbook.md). Save a
completed record under the owning plan's reports directory and link it from
[NuttX status](../port-status-nuttx.md) or [PX4 HAL status](../port-status-px4-hal.md).
This is an unexecuted checklist, not evidence that any gate has passed.

Select checks for the named driver/profile. Mark an item not applicable with
its reason; never omit an applicable failure, cleanup, timing or safety gate.
The [deployment guide](../../deployment-guide.md) owns build and debug commands.
Reset, image loading and target-memory writes require explicit authorization.

## Completed sensor-free RTT campaign boundary

The committed [validation record](../evidence/sensor-free-rtt-validation-261024.md)
and [machine matrix](../evidence/sensor-free-rtt-matrix-261024.json) record 128
native entries: 92 PASS, 2 NOT-PASS, 6 BLOCKED and 28 OUT-OF-SCOPE. This
campaign admits register, ISR-delivery and internal-function checks only. It
does not cover sensors, external peripheral traffic, PWM waveforms or
production qualification, and it must not be used to promote a PX4 HAL or
flight-path claim. Both GBETH units remain supported; matching-core I/O headers
take precedence where present. The matrix is the result authority; this
checklist does not reproduce its profile inventory.

## Source and build evidence

- [ ] Name the board, core, profile, root/NuttX/apps revisions and comparison
      sources. Follow the [reference map](../reference-source-map.md); label
      missing sources and different-IP examples.
- [ ] Trace register bases, offsets, widths, masks, clock/reset resources,
      pinmux and IRQ/ELC routes to the applicable manual/CMSIS/FSP evidence.
- [ ] Check formulas and edge/level behavior against the selected IP contract;
      record intentional differences. Confirm live clocks for timing claims.
- [ ] Check Kconfig dependencies, board registration and Make/CMake source
      selection against the actual upper-half API.
- [ ] Run the owning build script for the named profile and inspect linked
      objects/symbols. Record command, exit status and artifact SHA-256.
- [ ] Run focused host contracts for the changed behavior and
      [coding checks](../../code-standards.md). Preserve and explain failures.

A missing schematic or generated pin artifact can remain a physical gate while
source/host/build work proceeds from the selected RDK reference. A known
software correctness failure cannot be waived as a hardware follow-up.

### Isolated RTT sample fixtures

The [native board configurations](../../../platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/)
include separately named CR8-0 validation fixtures. List them with
`platforms/nuttx/NuttX/build.sh --list`; build one at a time through that script.
`nsh-rtt-interactive` provides the baseline; `dmac-memcpy-rtt`, `gtm-rtt`,
`canfd-rtt`, `hil-spi-loopback-rtt` and `spi-loopback-rtt` provide internal
tests. `pwm-rtt`, `pwm-oneshot-rtt` and `adc-rtt` check software completion
without qualifying a physical waveform or analog input.

These fixtures use RTT console input/output, foreground builtin completion,
nonblocking trim and NSH memory commands. Use only address-only `mb`/`mh`/`mw`
reads, after validating the named peripheral's clock/reset/MSTOP gates.
Missing log markers cannot pass. Use READLINE for these RTT fixtures; the
cursor-position editor can wait for an unsupported terminal response. The
legacy SPI and PWM oneshot examples run during boot; drain retained RTT
output before console synchronization. Bridge readiness checks must not open
a client and consume that single-client stream.

`gy912-polled-gpio-cs` and `gy912-dma-ssl-rtt` preserve the standalone
ICM20948 SPI0/P94 wiring in separate polling/GPIO-CS and DMA48/49/hardware-SSL
fixtures. Both require positive sensor IRQ evidence. Their validation
configs retain sensor identity/configuration/sample/result output and SPI
WARN/ERROR while disabling per-transaction SPI INFO flooding; assertions and
stack coloration remain enabled. Original verbose images faulted during the
[2026-10-14 campaign](../../../plans/reports/test-261014-0904-rzv2h-rtt-sample-validation.md);
reduced-log passes do not establish a repair for that fault. Add no wiring
for this suite. IPC peer state, WDT, storage writes and external SCI-SPI loopback are
outside its contract. Archive each exact ELF and resolved configuration before
building the next image; obtain explicit approval before RAM-loading it.

## Initialization, failure and reset

- [ ] Clock, module reset, pins, peripheral state, IRQ attachment and delivery
      follow the selected IP lifecycle; no register access before its clock.
- [ ] Failure at each acquired resource unwinds ownership in reverse order.
      Check retry, duplicate initialization, close and reopen behavior.
- [ ] Clear pending state before enabling delivery as required by the IP;
      verify read-back delays or settling constraints where specified.
- [ ] Shutdown quiesces transfers and callbacks before freeing state or gating
      clocks. Report cleanup failures rather than claiming success.
- [ ] If suspend/resume is supported, repeated cycles restore the complete
      contract without stealing another instance's resources.
- [ ] If reset is in scope, prove actual reset and startup of the exact image,
      warm-reset independence and inactive motor pins through reset/boot.

## Interrupts and concurrency

- [ ] The ISR identifies and clears only its owned source; architecture and
      peripheral acknowledgement do not double-clear or leave a stuck event.
- [ ] CPU-level and peripheral-level masking are handled separately, with
      edge/level and priority set for the real route.
- [ ] ISR execution is bounded and uses only APIs allowed in interrupt context;
      blocking work and ordinary diagnostic formatting run in task context.
- [ ] Measure event-to-callback latency and jitter against the selected
      requirement; record instruments, workload and interrupt interference.
- [ ] Protect ISR/task shared state with the appropriate critical-section or
      interrupt-safe primitive; restore saved interrupt state. Use the owning
      mutex/semaphore contract for task/work-queue state.
- [ ] Check per-instance ownership, simultaneous events, callback lifetime,
      detach/reentry and return semantics against the actual callback API.
- [ ] Cross-core sharing has an explicit ownership/coherency protocol; local
      interrupt masking or `volatile` alone is insufficient.

### C.4 P94 Button TINT Retest

The [named P94 confirmation](../evidence/gpio-button-interrupt-validation.md) records
user-confirmed interrupt delivery for CR8-0 `rdk-rzv2h:nsh-leds`. It contains
no passing transcript or exact loaded ELF hash; those gates remain open.
This image's P94 input cannot share the sensor extension's P94 CS output.

- [ ] Archive loaded ELF SHA-256, source/board revisions, load/reset provenance
      and the passing boot/press transcript.
- [ ] Confirm PM=`01`, PMC=`0` and ISEL29_H bit 0=`1` at `0x10412d4c`.
- [ ] Capture the selected TINT/GIC route and `INTR8SEL0` access at `0x10400140`.
- [ ] Record repeated press/release counts, debounce and physical LED0/PB4
      toggles; verify falling-edge press handling and no release-only toggle.
- [ ] Exercise attachment, detachment and recovery; establish cold-boot,
      latency and workload bounds before broader qualification.

## DMA and cache, when enabled

- [ ] Resolve channel/unit ownership and trigger events from the selected
      configuration. FSP is evidence for routing constraints, not permission
      to copy another consumer's channel allocation.
- [ ] Compare DMA channel and ELC/INTC activation mapping with the core-matched
      FSP reference; explain any intentional allocation differences and verify
      the selected trigger route in hardware.
- [ ] Validate source/destination reachability, byte count, transfer width and
      alignment. Confirm CPU versus DMAC bus aliases for CR8 TCM buffers.
- [ ] Trace cache clean/invalidate ownership through the actual driver API.
      Protect destination data before DMA and CPU consumption afterward;
      avoid overlapping cache-line ownership and CPU reuse during transfer.
- [ ] Confirm supported one-shot/reload semantics in the current DMAC driver;
      do not infer linked-descriptor support from another controller.
- [ ] Verify completion versus error handling, timeout, repeated start/rearm,
      buffer lifetime and stop/disable cleanup.
- [ ] For memory-copy proof, run the selected `dmac-memcpy` image after an
      approved load and archive `PASS: DMAC memcpy`, CPU addresses and status.
      Read N0SA/N0DA separately when bus-alias proof is required.
- [ ] Qualify each enabled peripheral-triggered consumer separately. Capture
      activation, ordering, rearm, cleanup and error recovery; a memory copy
      does not prove SPI, serial, I2C or DShot pacing.
- [ ] For DShot, measure every selected GPT output and ESC response before
      calling that path functional.

## Functional and physical evidence

- [ ] Use the selected device procedure linked from the [port index](../README.md)
      for wiring, commands, identity/data checks and expected results.
- [ ] Capture normal operation, a relevant injected failure and recovery.
      A prompt, successful host check or internal loopback cannot prove an
      external sensor, transceiver or actuator connection.
- [ ] Measure applicable clock/bus rates, signal levels, timing and pin safety;
      state accepted tolerances and instrument limits before reporting PASS.
- [ ] For UART profiles, test 9600, 115200 and 460800 baud where supported;
      record unsupported rates explicitly. Compare SCI-B clock/divisor and
      generated baud settings with the core-matched FSP SCI-B source. SCIFA
      requires its own IP evidence; SCI-B is not a substitute.
- [ ] If persistence is selected, prove partition boundaries, save/reboot/load
      and controlled power-loss recovery without erasing boot/executable data.
      Label TMPFS results volatile.
- [ ] If multi-device deployment is selected, prove per-unit identity from its
      approved provisioning source; otherwise limit the result to one prototype.

### SCI0 loopback profile

The native `sci-spi-loopback` profile registers SCI0 as `/dev/spi0` and
includes NuttX `spitool`; the RSPI loopback example cannot drive SCI-SPI.
The board source assigns P5_0 to MOSI, P5_1 to MISO and P6_0 to SCK.
After an authorized image load and wiring check, connect P5_0 to P5_1 and run:

```text
spi exch -b 0 -f 1000000 -m 0 -w 8 -x 4 a55ac33c
```

Require `Received:` to contain `A5 5A C3 3C` without a transfer error.
Repeat with the jumper removed and confirm the exchange still completes
within its deadline before reconnecting it. The master still supplies clocks;
an unconnected MISO pin can return arbitrary bytes without a transfer error.
This procedure is an unexecuted physical gate and does not test timeout recovery.

## Reliability when required by the profile

State the workload, duration, event rate and pass threshold. For interrupt
stress qualification, exercise the maximum supported rate for at least one
minute and at least 10,000 cycles. Record why a gate is not applicable; retain
any stricter acceptance criteria of the selected profile.

- [ ] Required events/callbacks are neither lost nor duplicated under that load.
- [ ] Interrupt counters advance without drops; post-test peripheral registers
      match the expected stopped state and the command shell remains responsive.
- [ ] Callback return values follow the actual API contract. Close/detach
      releases owned callback context only after in-flight callbacks finish;
      repeated registration and teardown do not leak resources.
- [ ] System liveness, resource bounds, state cleanup and recovery hold afterward.
- [ ] Record worst-case timing, not only averages. Simulator/host timing does
      not qualify the target's compiler, memory layout or interrupt workload.

## Completion record

Record the following together, with links to retained artifacts:

| Field | Required information |
|---|---|
| Identity | Board/module/core/profile and exact source revisions |
| Artifact | ELF SHA-256, build command/result and selected configuration |
| Execution | Approved load/reset method, console route and complete transcript |
| Source/host proof | Applicable checks, results, failures and excluded scope |
| Physical proof | Device observations, analyzer/register captures and tolerances |
| Reliability | Selected workload, acceptance bounds and measured results |
| Result | PASS, FAIL or DEFERRED; strongest observed evidence tier |
| Open gates | Missing provenance, unresolved defects and remaining qualification |

Use the [status definitions](../port-status-nuttx.md#status-legend). Never promote
source/build evidence to target qualification, or a bounded sample result to
production or flight readiness.
