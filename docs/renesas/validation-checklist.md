# Per-Driver Validation Checklist

**Date:** 2026-07-11  
**Usage:** Copy and complete this checklist per driver during bring-up; link completed version to [port-status-nuttx.md](port-status-nuttx.md) Validation Report column.

---

## Template: Driver Name = `<driver>`

**Driver File:** `arch/arm/src/rzv/<driver>.c`  
**Header File:** `arch/arm/src/rzv/hardware/rzv_<driver>.h`  
**Sample Config:** `boards/arm/rzv/rdk-rzv2h/configs/<config>/`  
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
- [ ] Reset de-assertion (ICU) happens AFTER clock enable, BEFORE register write.
- [ ] CPG divisor set correctly (reference FSP driver for PLL/clock tree).
- [ ] No access to peripheral registers when clock is gated (would hang or read 0xFFFF).

**Checklist Item:** Trace `rzv_<driver>_initialize()` → verify CPG/reset calls precede register writes.

---

### A.3 Pin/Alternate Function Assignment

- [ ] Pins assigned to peripheral in `rzv_pinmap.h` match `boards/arm/rzv/rdk-rzv2h/configs/<config>/defconfig`.
- [ ] Alternate function (AF) routing correct: UART TXD pin → SCIF_TXD via ICU, not GPIO output.
- [ ] No pin conflicts: same pin not assigned to two peripherals simultaneously (verify with `pinmap.md`).
- [ ] Pull-up/pull-down configured per datasheet (e.g., UART RXD typically has pull-up).

**Validation Tool:** Read `rzv_pinmap.h`; cross-check defconfig AF assignments.

---

### A.4 Interrupt Vector & Priority Assignment

- [ ] IRQ number assigned to peripheral (from ICU interrupt mapping) in `rzv_irq.h`.
- [ ] ISR priority assigned (CPU priority level, GIC priority value) matches device role.
  - Flight-critical (SPI, I2C): priority 0–3 (high).
  - Non-critical (watchdog): priority 4–15 (low).
- [ ] ISR registered via `irq_attach()` with correct handler signature.
- [ ] No IRQ conflicts: same vector number not assigned to two drivers.

**Verification:** Run `grep -r "RZV_IRQ_<DRIVER>" arch/arm/src/rzv/`.

---

## SECTION B: Initialization Order Compliance

### B.1 Driver Init Entry Point

- [ ] `<driver>_initialize()` exists and called from `up_initialize()` (or board-specific init).
- [ ] Returns status (int): 0 on success, -ENODEV on error (no hardware) or -EBUSY (already open).
- [ ] Idempotent: multiple calls to `initialize()` do not corrupt state (re-entrant guards if needed).

---

### B.2 Register Initialization Sequence

For each supported peripheral instance, verify in order:

1. **Clock enable** → `rzv_clock_enable(MODULE_ID)` or CPG register write.
2. **Reset de-assertion** → write RST register (ICU) or equivalent.
3. **Pin configuration** → `pm_pinctrl()` or GPIO alternate function set.
4. **Peripheral register defaults** → clear/set control registers to known state.
5. **Interrupt setup** → `irq_attach()` + enable via GIC/ICU.
6. **DMA setup (if used)** → channel reserve, alignment, cache setup.
7. **Device registration** → `<type>_register()` (e.g., `uart_register()`, `spi_dev_register()`).

**Anti-pattern:** Setting registers before clock enable will fail silently or hang.

---

### B.3 Clock Divisor Verification

- [ ] Clock divider formula matches FSP reference driver.
- [ ] Baud rate (UART), SCK frequency (SPI), or sample rate (ADC) achievable with CPG settings.
  - Example: UART baud rate = PCLK / (16 × (BRR + 1)). Verify BRR calculation for 115200 baud.
- [ ] Tolerance within ±3% (standard for serial comms).

**Test:** Load driver, read peripheral clock rate register, compare to expected divisor output.

---

## SECTION C: Interrupt Service Routine (ISR) Validation

### C.1 ISR Acknowledgment Sequence

- [ ] ISR reads status register (not assumed from callback context).
- [ ] ISR clears interrupt flag in peripheral (write 1 to ICLR or equivalent) BEFORE returning.
- [ ] If using GIC, ISR should end with `gic_acknowledge(irq)` to deassert the interrupt line.
- [ ] Avoid double-clear: single write clears flag; no loop waiting for flag to clear.

**Failure Example:** ISR doesn't clear interrupt → immediate re-entry, hangs CPU.

---

### C.2 ISR Priority & Non-Blocking Semantics

- [ ] ISR does NOT call blocking functions (nxmutex_lock, sem_wait, malloc).
- [ ] ISR duration <100 µs (measure with GPIO toggle on enter/exit).
- [ ] ISR priority prevents preemption by lower-priority tasks (kernel scheduler respects GIC priority levels).
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

- [ ] Read-DMA buffer: `arm_dcache_inval_range()` BEFORE reading DMA result (invalidate CPU cache).
- [ ] Write-DMA buffer: `arm_dcache_clean_range()` AFTER copying data to buffer, BEFORE DMA start (flush CPU cache).
- [ ] Buffer alignment: DMA data buffers aligned to cache line (32 or 64 bytes, typically).
- [ ] Buffer size: multiple of DMA transfer width (e.g., SPI DMAC uses 4-byte words; buffer size ≥4 and divisible by 4).

**Failure Example:** CPU writes to buffer, DMA reads stale cached value → data mismatch.

---

### D.2 DMAC Channel Management

- [ ] Channel reserve: `dmac_channel_reserve()` called once per peripheral instance.
- [ ] Channel release: `dmac_channel_release()` called when driver closed (cleanup).
- [ ] No hardcoded channel numbers: use board-specific assignment (e.g., `CONFIG_RZV_SPI0_DMA_CHANNEL`).
- [ ] Channel interrupts (if used): ISR priority ≥ peripheral driver priority.

---

### D.3 DMA Chain & Transfer Integrity

- [ ] Linked descriptors: verify descriptor count and byte alignment (each descriptor may have alignment requirement).
- [ ] Transfer size bounds: DMAC supports max transfer size (e.g., 64k per descriptor); break larger transfers into chain.
- [ ] No descriptor corruption: validate fields (source, dest, len, next_descriptor_addr) match memory layout.

**Test:** DMA transfer of known pattern (0xAA55AA55); verify buffer contains exact pattern post-transfer.

---

### D.4 RZ/V2H CR8-0 DMAC polling memory-copy proof

- [x] Build `rdk-rzv2h:dmac-memcpy` with `CONFIG_RZV_DMAC` and
  `CONFIG_EXAMPLES_RZV_DMAC` enabled.
- [ ] Flash and run `rzv_dmac` on CR8-0; this is deliberately deferred from
  the build-only check.
- [ ] Archive UART output containing CPU addresses, final status, and
  `PASS: DMAC memcpy`.  If bus aliases are required as evidence, read N0SA
  and N0DA through the hardware debugger; the supported application interface
  deliberately exposes CPU addresses only.
- [ ] Keep peripheral-triggered DMAC, DTC, serial, SPI, I2C, and DShot DMA
  outside this proof until separately designed and validated.

---

## SECTION E: Concurrency & Shared Register Access

### E.1 IRQSave Protection

- [ ] Shared register access (multiple bits written by driver + ISR) guarded with `irqsave()` / `irqrestore()`.
- [ ] Example: SPI module may have TX register and STATUS register; ISR reads STATUS, task writes to TX → use irqsave lock.
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
- [ ] Trigger timing <100 ns after hardware edge (measure with oscilloscope if critical).

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

- [ ] Jitter <100 µs (acceptable for most UAV apps).
- [ ] Max latency <500 µs (hard real-time requirement for flight control).

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

## SECTION I: Example Completion

**Driver: UART (rzv_scif.c)**

```markdown
# Validation Report: rzv_scif.c

**Date:** 2026-07-15  
**Tester:** John Developer  
**Config:** boards/arm/rzv/rdk-rzv2h/configs/nsh-scif/

## A. Static Validation

### A.1 Register Map
- [x] Base address 0x1004A000 matches UM section 27.3 (Serial Communication Interface F).
- [x] Bit definitions verified: SMR, SCR, FSR, FTDR, FRDR, SPTR.
- [x] No magic addresses; all from rzv_sci.h.

### A.2 Clock/Reset
- [x] rzv_clock_enable(MODULE_ID_SCI_F) called before register init.
- [x] Reset deasserted via ICU write.
- [x] CPG divisor set for PCLK = 100 MHz.

### A.3 Pins
- [x] SCIF_TXD on port 1 pin 3 (AF9) matches defconfig.
- [x] SCIF_RXD on port 1 pin 2 (AF9) with pull-up enabled.
- [x] No pin conflicts.

### A.4 IRQ
- [x] IRQ 201 (from UM) assigned to SCIF_F in rzv_irq.h.
- [x] Priority set to 5 (non-critical).
- [x] No conflicts detected.

## B. Initialization Order

- [x] up_initialize() → rzv_serial_initialize() → scif_init() sequence verified.
- [x] Clock → Reset → Pin → Register → IRQ order confirmed.
- [x] Baud rate 115200: PCLK 100MHz, BRR = 54 (formula: (100e6 / (16 * 115200)) - 1 = 53.67 ≈ 54).
- [x] Idempotent: called twice in test, no corruption.

## C. ISR

- [x] ISR clears FSR (frame status) register before return.
- [x] GIC acknowledge called (via up_enable_irq mechanics).
- [x] ISR duration <50 µs (measured with GPIO toggle).
- [x] No blocking calls inside ISR.

## D. DMA

- [x] Not used in this driver (polled UART).

## E. Concurrency

- [x] Driver state per-instance (one state_s struct per SCIF_F instance).
- [x] No shared globals.

## F. Power Management

- [x] suspend/resume not implemented (blocking poll only).

## G. Functional Equivalence

- [x] Baud rate formula matches FSP r_sci_b.c.
- [x] 115200 baud verified with serial terminal (loopback).
- [x] Edge semantics N/A (UART not edge-triggered).

## H. Stress

- [x] Loopback test: 100k characters at 115200 baud; no drop.
- [x] Latency: <100 µs from RX interrupt to callback.
- [x] CPU remains responsive during test.

## I. Pass/Fail

**Result: PASS** ✓

**Status:** functional

**Notes:** Ready for integration. Consider adding DMA support in future for high-rate telemetry.
```

---

## Related Docs

- [NuttX Port Status](port-status-nuttx.md) — per-driver status links to this checklist.
- [Design Guidelines](../design-guidelines.md) — driver skeleton patterns and architecture.
- [Deployment Guide](../deployment-guide.md) — test harness and validation tools.
