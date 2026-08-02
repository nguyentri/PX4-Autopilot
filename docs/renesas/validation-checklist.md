# Per-Driver Validation Checklist

**Date:** 2026-08-02
**Usage:** Copy and complete this checklist per driver during bring-up; link completed version to [port-status-nuttx.md](port-status-nuttx.md) Validation Report column.

---

## Template: Driver Name = `<driver>`

**Driver File:** `arch/arm/src/rzv/<driver>.c`  
**Header File:** `arch/arm/src/rzv/hardware/rzv_<driver>.h`  
**Sample Config:** `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/<config>/`
**Reference FSP:** `refs/px4-freertos-posix-renesas-fsp/rzv/fsp/src/r_<driver>/`

---

## SECTION A: Static Validation

### A.1 Register Map vs CMSIS

- [ ] All base addresses in `rzv_<driver>.h` match Renesas RZ/V2H user manual (UM, section CPG/Timers/Serial/etc).
- [ ] Bit field definitions (masks, shifts) match CMSIS device header `RZV_<PERIPHERAL>.h` (if available).
- [ ] Verify read/write access rules (RW, R/O, W/O) per datasheet for each register.
- [ ] No hardcoded magic addresses; all derived from `hardware/rzv_<driver>.h`.

**Failure Example:** Register offset off by 4 bytes → reads stale cached value or writes wrong peripheral.

---

### A.2 Clock/Reset Initialization Order

- [ ] Driver calls `rzv_clock_enable()` (or equivalent) BEFORE accessing peripheral registers.
- [ ] Reset de-assertion happens through the CPG/module reset path AFTER clock enable, BEFORE register write.
- [ ] CPG divisor set correctly (reference FSP driver for PLL/clock tree).
- [ ] No access to peripheral registers when clock is gated (would hang or read 0xFFFF).

**Checklist Item:** Trace `rzv_<driver>_initialize()` → verify CPG/reset calls precede register writes.

---

### A.3 Pin/Alternate Function Assignment

- [ ] Pins assigned to the peripheral match the selected instance in
      `platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/configs/<config>/defconfig`
      and the board IOPORT/PFC setup.
- [ ] Alternate function (AF) routing correct: UART TXD pin → SCIF_TXD via IOPORT/PFC, not ICU or GPIO output.
- [ ] No pin conflicts: same pin not assigned to two peripherals simultaneously (verify with `pinmap.md`).
- [ ] Pull-up/pull-down configured per datasheet (e.g., UART RXD typically has pull-up).

**Validation Tool:** Read `rzv_pinmap.h`; cross-check defconfig AF assignments.

---

### A.4 Interrupt Vector & Priority Assignment

- [ ] IRQ number assigned to peripheral (from ICU interrupt mapping) in `rzv_irq.h`.
- [ ] ISR priority is documented per device and matches the board interrupt plan.
- [ ] ISR registered via `irq_attach()` with correct handler signature.
- [ ] No IRQ conflicts: same vector number not assigned to two drivers.

**Verification:** Run `grep -r "RZV_IRQ_<DRIVER>" platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/`.

---

## SECTION B: Initialization Order Compliance

### B.1 Driver Init Entry Point

- [ ] `<driver>_initialize()` exists and called from `up_initialize()` (or board-specific init).
- [ ] Return contract matches the selected NuttX interface: status-returning
      initializers use `0`/negative `errno`, while lower-half factories may
      return a device pointer or `NULL`.
- [ ] Idempotent: multiple calls to `initialize()` do not corrupt state (re-entrant guards if needed).

---

### B.2 Register Initialization Sequence

For each supported peripheral instance, verify in order:

1. **Clock enable** → `rzv_clock_enable(MODULE_ID)` or CPG register write.
2. **Reset de-assertion** → CPG/module reset release helper for the module.
3. **Pin configuration** → board IOPORT/PFC alternate-function setup.
4. **Peripheral register defaults** → clear/set control registers to known state.
5. **Interrupt setup** → `irq_attach()` + enable via GIC/ICU.
6. **DMA setup (if used)** → channel reserve, alignment, cache setup.
7. **Device registration** → the current upper-half API (e.g.,
   `uart_register()` or `spi_register()`).

**Anti-pattern:** Setting registers before clock enable will fail silently or hang.

---

### B.3 Clock Divisor Verification

- [ ] Clock divider formula matches FSP reference driver.
- [ ] Baud rate (UART), SCK frequency (SPI), or sample rate (ADC) is achievable with the documented CPG settings.
  - Example: UART baud rate = PCLK / (16 × (BRR + 1)). Verify the module-specific BRR calculation.

**Test:** Load driver, read peripheral clock rate register, compare to expected divisor output.

---

## SECTION C: Interrupt Service Routine (ISR) Validation

### C.1 ISR Acknowledgment Sequence

- [ ] ISR reads status register (not assumed from callback context).
- [ ] ISR clears interrupt flag in peripheral (write 1 to ICLR or equivalent) BEFORE returning.
- [ ] If using GIC, verify the line is acknowledged by the architecture path or the driver-specific helper; do not assume a manual `gic_acknowledge(irq)` belongs in every ISR.
- [ ] Avoid double-clear: single write clears flag; no loop waiting for flag to clear.

**Failure Example:** ISR doesn't clear interrupt → immediate re-entry, hangs CPU.

---

### C.2 ISR Priority & Non-Blocking Semantics

- [ ] ISR does NOT call blocking functions (`nxmutex_lock`, `sem_wait`, `malloc`).
- [ ] ISR duration is measured and documented against the driver-specific acceptance criterion.
- [ ] ISR priority prevents preemption by lower-priority tasks according to the board interrupt plan.
- [ ] ISR re-entrancy: if peripheral can generate multiple simultaneous interrupts (e.g., RX + TX), use atomic flags or queue pending events.

**Test:** Enable ISR in NuttX config, attach oscilloscope to GPIO toggle, measure width and jitter.

---

### C.3 GIC Enable & Interrupt Masking

- [ ] After `irq_attach()`, interrupt is masked (disabled) in GIC until `up_enable_irq()`.
- [ ] `up_enable_irq()` called only once during initialization (not per-ISR entry).
- [ ] Peripheral-level interrupt enable (e.g., SPI TXE flag) separate from CPU-level (GIC) enable.

**Failure Example:** Forgetting `up_enable_irq()` → ISR never fires even on valid peripheral event.

---

## SECTION D: DMA Integration (if applicable)

### D.1 Cache Coherency & Invalidate/Clean

- [ ] Read-DMA buffer: invalidate the destination with
      `up_invalidate_dcache(start, end)` before CPU consumption.
- [ ] Write-DMA buffer: clean the source with
      `up_clean_dcache(start, end)` after CPU writes and before DMA start.
- [ ] Buffer alignment: cached CR8 DMA buffers aligned to the 32-byte
      Cortex-R8 cache line.
- [ ] Buffer size: multiple of DMA transfer width (e.g., SPI DMAC uses 4-byte words; buffer size ≥4 and divisible by 4).

**Failure Example:** CPU writes to buffer, DMA reads stale cached value → data mismatch.

---

### D.2 DMAC Channel Management

- [ ] Channel setup uses `rzv_dmac_channel_initialize()` and
      `rzv_dmac_channel_configure()` once per assigned channel.
- [ ] Stop/cleanup uses `rzv_dmac_channel_stop()` or
      `rzv_dmac_channel_disable()` as required by the driver's lifecycle.
- [ ] No hardcoded channel numbers: use separate board assignments for each
      direction (for example, `CONFIG_RZV_DMAC_SPI0_RX_CHANNEL` and
      `CONFIG_RZV_DMAC_SPI0_TX_CHANNEL`).
- [ ] Channel interrupts (if used): ISR priority ≥ peripheral driver priority.

---

### D.3 One-Shot Transfer Integrity

- [ ] Keep `REN` clear and use N[0] register mode; the current driver does not
      support linked descriptors or continuous reload.
- [ ] Validate source, destination, byte count, and transfer-width alignment
      before enabling the channel.
- [ ] For CR8-0 ITCM/DTCM buffers, verify the programmed N[0] address uses the
      DMAC bus alias while the caller and cache operations use the CPU address.

**Test:** DMA transfer of known pattern (0xAA55AA55); verify buffer contains exact pattern post-transfer.

---

### D.4 RZ/V2H CR8-0 DMAC polling memory-copy proof

- [x] Build `rdk-rzv2h:dmac-memcpy` with `CONFIG_RZV_DMAC` and
  `CONFIG_EXAMPLES_RZV_DMAC` enabled.
- [ ] After an approved exact-image load procedure exists, load and run
  `rzv_dmac` on CR8-0; this is deliberately deferred from the build-only
  check.
- [ ] Archive UART output containing CPU addresses, final status, and
  `PASS: DMAC memcpy`.  If bus aliases are required as evidence, read N0SA
  and N0DA through the hardware debugger; the supported application interface
  deliberately exposes CPU addresses only.
- [ ] Keep peripheral-triggered DMAC, DTC, serial, SPI, I2C, and DShot DMA
  outside this memory-copy proof; validate every enabled consumer separately.

### D.5 Hardware-Triggered Peripheral Proof

- [x] Source/build contract supports INTC `DMkSEL` routing and one-shot
  memory-to-peripheral transfers used by serial and the opt-in DShot image.
- [ ] Verify the selected activation event and DMAC unit/channel on target.
- [ ] Capture transfer ordering, repeated trigger/re-arm behavior, cleanup,
  and error recovery.
- [ ] For DShot, capture each GPT waveform and confirm ESC response before
  treating the path as functional.

---

## SECTION E: Concurrency & Shared Register Access

### E.1 Critical-Section Protection

- [ ] Shared register access (multiple bits written by driver + ISR) guarded
      with `enter_critical_section()` / `leave_critical_section()`.
- [ ] Example: if an ISR and task update related SPI state, capture the
      returned `irqstate_t` and leave the critical section after the atomic
      update.
- [ ] Mutexes used for non-ISR-to-ISR sharing (task-to-task or task-to-workqueue).

**Anti-pattern:** Task reads STATUS, ISR modifies STATUS, task writes wrong bit → data corruption.

---

### E.2 Per-Instance State

- [ ] Driver state (e.g., per SPI instance) stored in separate structs (not globals).
- [ ] State protected if accessed from both ISR and task (e.g., callback pointer in SPI device).
- [ ] Multi-instance safe: if board uses SPI0 and SPI1 simultaneously, no register read/write race.

---

## SECTION F: Power Management

### F.1 Suspend/Resume Hooks (if applicable)

- [ ] If driver implements PM idle hook, verify `<driver>_suspend()` / `<driver>_resume()`.
- [ ] Suspend: stop DMA, disable interrupts, gate clock (in reverse order of init).
- [ ] Resume: re-enable clock, reset, reconfigure registers, enable interrupts.
- [ ] Idempotent: multiple suspend/resume cycles do not corrupt state.

---

## SECTION G: Functional Equivalence vs FreeRTOS Reference

### G.1 Clock Formula Verification

**Checklist Item:** Compare NuttX driver clock calculation to FSP (FreeRTOS) reference.

Example (UART baud rate):

```c
/* NuttX (rzv_scif.c) */
uint16_t brr = (PCLK / (16 * baud)) - 1;

/* FSP (r_sci_b.c) */
uint16_t brr = (SCI_B_PCLK / (16 * baud)) - 1;
```

- [ ] Formula identical.
- [ ] PCLK value matches (verify CPG divisor state).
- [ ] Baud rate achievable: test 9600, 115200, 460800.

---

### G.2 Timing & Edge Semantics

**Checklist Item:** Compare trigger edge/level, sample timing to FSP.

Example (GPIO IRQ):

```c
/* NuttX (rzv_gpio.c) */
if (rising_edge)  conf |= GPIO_EDGE_RISING;

/* FSP (r_ioport.c) */
if (rising_edge)  conf |= IOPORT_IRQ_EDGE_RISING;
```

- [ ] Edge/level semantics identical.
- [ ] Trigger timing is measured if the edge path is safety-critical; document the observed value and the acceptance criterion used.

---

### G.3 DMA Channel & Peripheral Assignment

- [ ] DMA channel assignment matches FSP (e.g., SPI0 TX → DMAC ch. 2).
- [ ] Trigger source (ELC event) routed correctly in ICU.

---

## SECTION H: Stress & Reliability Testing

### H.1 Repeated Interrupt Load

**Setup:** Configure driver to generate interrupts at max rate (e.g., SPI loopback, UART RX on fast baud).

- [ ] No ISR drops: interrupt counter increments steadily for ≥10,000 cycles.
- [ ] No register corruption: post-test, peripheral state matches expected (e.g., SPI_SR TXEMPTY = 1 after stop).
- [ ] No CPU hang: system remains responsive (can still run shell commands).

**Test Duration:** ≥1 minute at max interrupt rate.

---

### H.2 Latency Measurement

**Setup:** Measure time from hardware event to callback start.

- [ ] Jitter and latency are recorded against the driver-specific requirement.

**Measurement Method:**
1. Toggle GPIO input (external signal generator or loopback).
2. ISR toggles output GPIO on event.
3. Oscilloscope measures delay between input and output edge.

---

### H.3 Callback Reliability

- [ ] Registered callbacks fire for every valid hardware event (no skipped callbacks).
- [ ] Callback return value honored (e.g., IOIR_HANDLED vs IOIR_NOTHANDLED).
- [ ] No callback memory leaks (callback context freed on device close).

---

## SECTION I: Illustrative Completion Format

> The SCIF report below is formatting guidance only. It is not RDK-RZ/V2H
> validation evidence and must not be copied into a status row as a PASS.
> The current SCIF lower-half remains blocked until its clock and IOPORT/PFC
> requirements are resolved and proven on target.

```markdown
# Validation Report: <driver/config>

**Date:** <YYYY-MM-DD>
**Tester:** <name or lab>
**Core/board revision:** <CR8-0|CR8-1|CM33>, <revision>
**Config and revisions:** <config>, <root/NuttX hashes>
**Boot/load provenance:** <cold|warm|debugger>, <exact command>
**Artifact SHA-256:** <hash>

## Static Evidence

- [ ] CMSIS/manual/FSP authority and applicability recorded.
- [ ] Base/offset/clock/reset/pin/IRQ claims traced to source.
- [ ] Board registration and expected node/consumer traced.

## Build Evidence

- [ ] Clean named configure/build/link result recorded.
- [ ] Expected board/lower-half symbols or objects present.
- [ ] No unresolved symbols or source-list mismatch.

## Target Evidence

- [ ] Complete boot log and command transcript attached.
- [ ] Successful operation and one injected failure/recovery captured.
- [ ] Register/analyzer/scope evidence attached where applicable.
- [ ] Timing, resource, and stress bounds state both criterion and result.
- [ ] `reboot` reaches a hardware reset, restarts the exact artifact, and
      preserves inactive motor-pin levels throughout reset and early boot.
- [ ] Repeated warm resets do not depend on another core or debugger state.
- [ ] Parameter save/reboot/load and controlled power-loss recovery prove the
      selected nonvolatile backend; TMPFS evidence is explicitly volatile.
- [ ] The reported UUID/GUID is unique per unit, or the report limits the
      result to one prototype and excludes identity-sensitive deployment.

## Result

**Result:** <PASS|FAIL|DEFERRED>
**Strongest evidence tier:** <configured|build-clean|hardware-ready|on-target functional|PX4-integrated|stress-validated>
**Open gates:** <remaining evidence or none>

## Unresolved Questions

- <question or "None">
```

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — per-driver status links to this checklist.
- [Design Guidelines](../design-guidelines.md) — driver skeleton patterns and architecture.
- [Deployment Guide](../deployment-guide.md) — test harness and validation tools.
