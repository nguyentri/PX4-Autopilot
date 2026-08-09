# Parametric Prompt Recipes

**Date:** 2026-08-09
**Status:** Active workflow reference
**Purpose:** Copy-pasteable Claude-Code prompts for common RZ/V2H porting tasks

Each recipe is a template. Substitute `<placeholder>` values and paste the
result as a direct Claude-Code prompt. If a plan is needed, invoke `/ck:plan`
with the completed request; this repository does not define recipe-specific
CLI flags.

For `firmware:audit`, resolve `<sample>` and `<core>` through
[reference-source-map.md](reference-source-map.md) before starting Mission 1.
Pass the active NuttX files, matching EVK project root, and every labelled
exception together. Never substitute `sci_b_uart` for SCIFA or `spi_b` for
RSPI; retain the CA55 Ethernet tree as secondary evidence only.

---

## Recipe 1: Driver Review

### When to Use
You have a working NuttX driver (`rzv_<driver>.c`) and want architectural feedback, completeness check, and test plan.

### Template

```
PROMPT:

Task: Review RZ/V2H NuttX driver implementation for <driver>.

Role: Technical reviewer ensuring driver follows NuttX best practices, handles 
edge cases, and integrates correctly with the RZ/V2H port.

Scope:
- Driver architecture (lower-half / upper-half split)
- ISR logic (source clear timing, work-queue deferral)
- Error handling (propagation, recovery)
- Cache coherency (DMA buffer invalidate/clean)
- Init sequencing (clock → reset/unreset → pins → IRQ → config)
- Concurrency (critical sections, mutex protection)

Files to Read (Primary):
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_<driver>.c (implementation)
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_<driver>.h (register map)
  - platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h/src/rzv2h_<driver>.c (standalone NuttX board wiring)

Files to Read (References):
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_gpt.c (timer reference)
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_serial.c (UART reference)
  - docs/design-guidelines.md (NuttX driver patterns)
  - docs/code-standards.md (code conventions)

Analysis Requirements:
1. Verify init sequence matches clock → reset/unreset → pins (IOPORT/PFC) → IRQ order
2. Check ISR clears the source it owns; defer work via `work_queue()`
3. Confirm no blocking calls in ISR (no sleep, malloc, syslog)
4. Check cache coherency: invalidate before RX DMA, clean before TX
5. Ensure nxmutex or critical sections protect shared HW registers
6. Verify error codes propagated (not swallowed)
7. Check Kconfig and Make.defs rules present
8. Review sample config compiles and driver registers on boot
9. Tag the result with the strongest evidence tier actually observed; do not promote a build-only result to hardware-ready

Deliverable Path:
  plans/reports/driver-review-<date>-rzv2h-<driver>-review-report.md

Success Criteria:
- [ ] All 8 analysis points explicitly addressed in report
- [ ] Concrete code line numbers cited for each finding
- [ ] Actionable recommendations (not vague)
- [ ] Optional: runnable test command for the driver

Validation Command:
  cd platforms/nuttx/NuttX/nuttx && ./tools/configure.sh rdk-rzv2h:<driver> && make -j$(nproc)
  # Verify no undefined references and driver registers
```

### Example Invocation
```
Paste Recipe 1 with <driver> replaced by spi-b, then invoke /ck:plan if needed.
```

---

## Recipe 2: Subsystem Audit

### When to Use
You need to understand the hardware architecture for a peripheral group (e.g., GPIO+ICU, UART+pinmux, SPI+DMAC) and map ownership, interrupts, clocks.

### Template

```
PROMPT:

Task: Audit RZ/V2H <subsystem> subsystem architecture and identify integration gaps.

Role: Systems architect documenting hardware topology, interrupt routing, 
clock dependencies, and driver ownership.

Scope:
- Hardware blocks and registers for <subsystem> (ref: FSP module r_<subsystem>)
- IRQ routing through ICU / GIC
- Clock and reset (CPG) dependencies
- Pin multiplexing requirements through IOPORT/PFC
- Driver coverage (which drivers implement which hardware blocks)
- Known gaps or missing drivers

Subsystem Examples: gpio-icu, uart-scif, spi-b-dmac, ether-dmac, ipc-mhu, adc-gtm

Files to Read (Primary):
  - docs/renesas/reference-source-map.md (resolve <sample>, <core>, and gaps first)
  - refs/rzv2h_evk/<sample>/<sample>_rzv2h_evk_<core>_ep/e2studio/ (when mapped)
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_*.h (HW headers)
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/Kconfig (driver enablement)
  - docs/renesas/hardware.md (HW overview)

Files to Read (References):
  - platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_*.c (existing drivers)
  - docs/design-guidelines.md (architecture patterns)

Analysis Requirements:
1. Create ownership matrix: which driver owns which hardware block
2. Create IRQ mapping table: hardware interrupt → ICU entry → GIC → NuttX driver
3. Document CPG clock tree for subsystem (source, dividers, freq)
4. Map pins required (from pinmap.md + FSP)
5. Identify driver gaps (hardware blocks without NuttX driver)
6. List FSP reference files for each gap (for future porting)
7. Document any known errata or silicon quirks
8. Suggest porting priority (dependencies: clocks/reset → pins → IRQ → drivers)
9. Record the strongest evidence tier observed for each claim

Deliverable Path:
  plans/reports/subsystem-audit-<date>-rzv2h-<subsystem>-audit-report.md

Deliverable Format:
  - Ownership matrix (block | NuttX driver | status | gaps)
  - IRQ mapping table (ICU entry | GIC ID | NuttX IRQ # | driver)
  - Clock tree (CPG source → dividers → freq → users)
  - Pin mux table (pin name | function | driver | current config)
  - Gap analysis (missing drivers, priority)

Success Criteria:
- [ ] Ownership matrix covers all hardware blocks in subsystem
- [ ] IRQ table matches actual NuttX driver irq_attach() calls
- [ ] Clock tree verified against rzv_cpg.c
- [ ] Pin list diff-able against docs/renesas/pinmap.md
- [ ] Gap list includes FSP source paths for future porting

Validation Command:
  grep -r "CONFIG_RZV_<SUBSYSTEM>" platforms/nuttx/NuttX/nuttx/
  grep -E "<driver>|<peripheral>" docs/renesas/pinmap.md
```

### Example Invocation
```
Paste Recipe 2 with <subsystem> replaced by uart-scif, then invoke /ck:plan if needed.
```

---

## Recipe 3: Migration Strategy

### When to Use
You are porting a subsystem, HAL layer, or driver from FreeRTOS to NuttX and need a step-by-step plan with dependencies, validation, and rollback points.

### Template

```
PROMPT:

Task: Create migration strategy for porting <target> from FreeRTOS to NuttX.

Role: Software architect planning phased migration with clear dependencies, 
test gates, and rollback procedures.

Scope:
- OS API changes (task/thread, semaphore, mutex, queue, timer)
- HAL layer refactoring (if <target> has PX4 HAL abstraction)
- Scheduler / work-queue changes (FreeRTOS priorities → NuttX)
- Clock / RTC / HRT time base migration
- Driver registration and init sequencing
- Build system (Kconfig, Make.defs, CMAKE if applicable)
- Testing and validation strategy

Target Examples: gpio-driver-suite, uart-subsystem, ipc-bridge, sensor-manager

Files to Read (Primary):
  - Core-matched EVK project selected through docs/renesas/reference-source-map.md
  - Integrated implementation at refs/px4-freertos-posix-renesas-fsp/ when system/RDK ownership is relevant
  - Equivalent NuttX driver(s) in platforms/nuttx/NuttX/nuttx/
  - docs/renesas/freertos-to-nuttx-mapping.md (API migration cheat sheet)
  - docs/design-guidelines.md (NuttX patterns)

Files to Read (References):
  - docs/system-architecture.md (CR8-0/1/CM33 topology)
  - Existing NuttX migration example: rzv_serial.c (if similar to target)

Analysis Requirements:
1. List all FreeRTOS APIs used in <target> (task_create, xSemaphore*, xQueue*, vTaskDelay, etc.)
2. Map each FreeRTOS API to NuttX equivalent (see freertos-to-nuttx-mapping.md)
3. Identify critical sections and mutual exclusion (mutex vs. semaphore vs. critical_section)
4. Document task/thread priority mapping (FreeRTOS 0-31 → NuttX 0-255; rescale if needed)
5. List clock/RTC dependencies (is <target> using FreeRTOS tick or hardware timer?)
6. Identify callback and ISR context changes (work_queue instead of xHigherPriorityTaskWoken)
7. Plan build system changes (Kconfig entries, Make.defs rules, cmake refactor if applicable)
8. Create ordered checklist: clock → driver init → HAL → tests
9. Define rollback point (when to revert if issues emerge)
10. Specify validation test (unit tests, integration tests, hardware validation)

Deliverable Path:
  plans/reports/migration-strategy-<date>-rzv2h-<target>-migration-plan.md

Deliverable Format:
  - API mapping table (FreeRTOS API → NuttX API | migration effort)
  - Dependency DAG (init order, blocking dependencies)
  - Phased checklist (Phase 1: APIs, Phase 2: HAL, Phase 3: Integration, Phase 4: Validation)
  - Per-phase success criteria and test gates
  - Rollback procedure (which commit to revert to, what to restore)
  - Risk assessment (what could break, mitigation)

Success Criteria:
- [ ] API mapping complete (all FreeRTOS calls → NuttX)
- [ ] Dependency DAG is acyclic and includes all 4 phases
- [ ] Each phase has measurable success criteria (test commands)
- [ ] Build system (Kconfig + Make.defs) changes scoped
- [ ] Rollback procedure is explicit and testable

Validation Command:
  (Phase 1 gate) choose an existing rdk-rzv2h config that exercises <target>,
                 then run ./tools/configure.sh rdk-rzv2h:<config> && make -j$(nproc)
  (Phase 2 gate) build the affected PX4 board target from the repository root
  (Phase 4 gate) run the focused in-tree contract or example documented for <target>
```

### Example Invocation
```
Paste Recipe 3 with <target> replaced by ipc-mhu-bridge, then invoke /ck:plan if needed.
```

---

## Recipe 4: HAL Port

### When to Use
You need to write a PX4 HAL abstraction layer for a peripheral (SPI, I2C, UART, GPIO) so PX4 application code is independent of the RZ/V2H driver.

### Template

```
PROMPT:

Task: Design and implement PX4 HAL abstraction for <peripheral>.

Role: PX4 HAL architect ensuring the abstraction is compatible with upstream 
PX4 device drivers and test frameworks.

Scope:
- PX4 HAL interface definition (SPI/I2C/UART/GPIO abstraction)
- Existing board-specific adapter (`spi.cpp`, `i2c.cpp`, `timer_config.cpp`,
  `init.c`, or the discovered equivalent)
- Driver registration and lifecycle (probe, init, shutdown)
- Error handling and exception handling
- Interrupt and DMA integration
- Power management (sleep/wake, clock gating)
- Testing strategy (unit tests, integration tests)

Peripheral Examples: spi-b, i2c, uart (scif), gpio (icu), ether

Files to Read (Primary):
  - PX4 NuttX device adapter: src/lib/drivers/device/nuttx/{SPI,I2C}.cpp when applicable
  - PX4 bus contract: platforms/common/include/px4_platform_common/i2c_spi_buses.h
  - RZ/V2H board adapters: boards/renesas/rdk-rzv2h/src/{spi.cpp,i2c.cpp,timer_config.cpp,init.c}
  - NuttX driver: platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_<peripheral>.c
  - docs/design-guidelines.md (NuttX driver patterns)

Files to Read (References):
  - docs/system-architecture.md (PX4 ↔ NuttX layering)
  - PX4 upstream examples: boards/px4/fmu-v6xrt/src/{spi.cpp,i2c.cpp}

Analysis Requirements:
1. Define PX4 HAL interface for <peripheral> (method signatures, error codes)
2. Review upstream PX4 drivers that use <peripheral> (e.g., IMU drivers use SPI)
3. Extend the existing RZ/V2H adapter; do not invent a generic
   `board_<peripheral>.c` boundary when the board already has a stronger one
4. Integrate with NuttX driver lower-half (rzv_<peripheral>.c)
5. Plan interrupt and DMA wiring
6. Document power state transitions
7. List test points (open, read/write, error cases, timeouts)
8. Plan integration with PX4 startup (board init sequence)

Deliverable Path:
  boards/renesas/rdk-rzv2h/src/<existing-adapter-file> (implementation)
  Documentation: plans/reports/hal-port-<date>-rzv2h-<peripheral>-hal-design.md

Success Criteria:
- [ ] HAL interface file created (or extended if exists)
- [ ] Existing board adapter compiles without errors
- [ ] Driver registration called during board init
- [ ] Test program opens, configures, reads/writes peripheral
- [ ] Error cases (timeout, hw failure) handled gracefully
- [ ] Upstream PX4 drivers can use the HAL

Validation Command:
  cd platforms/nuttx/NuttX/nuttx && ./tools/configure.sh rdk-rzv2h:<sample-app-using-<peripheral>>
  make -j$(nproc)
  # On board: run unit tests for <peripheral>
```

### Example Invocation
```
Paste Recipe 4 with <peripheral> replaced by spi-b, then invoke /ck:plan if needed.
```

---

## Recipe 5: App Migration

### When to Use
You have a PX4 application (module, task) currently using POSIX threads and want to refactor it to use NuttX work-queues for efficiency.

### Template

```
PROMPT:

Task: Migrate PX4 application <app> from POSIX task to NuttX work-queue.

Role: PX4 software engineer modernizing app to use NuttX work-queue for 
better schedulability and resource efficiency.

Scope:
- Task / thread creation (pthread → work_queue)
- Event loop refactoring (blocking loop → work-queue callback)
- Scheduler priority mapping (POSIX priority → NuttX / work-queue level)
- Inter-task communication (semaphore, queue → NuttX equivalents)
- Timer/tick handling (hrt_absolute_time, usleep → NuttX HRT)
- Startup / lifecycle management
- Testing and validation

App Examples: sensor-manager, logger, estimator, command-handler

Files to Read (Primary):
  - src/modules/<app>/*.cpp (application source)
  - docs/renesas/freertos-to-nuttx-mapping.md (API cheat sheet)
  - docs/design-guidelines.md (work-queue patterns)

Files to Read (References):
  - platforms/nuttx/src/px4/ (existing work-queue and shim examples)
  - NuttX work-queue docs: platforms/nuttx/NuttX/nuttx/Documentation/NuttXWork.html (if available)

Analysis Requirements:
1. Identify current task entry point (pthread_create call in startup)
2. List all blocking operations (sleep, semaphore_wait, queue_receive)
3. Map task priority and scheduling requirements (real-time? deadline?)
4. Identify shared state and locks (nxmutex, critical sections needed?)
5. Document timing requirements (tick period, HRT usage)
6. List inter-task communication (other tasks signaling this one? vice versa?)
7. Plan work-queue type based on the module's latency and blocking tolerance
8. Identify initialization order (dependencies on other modules)
9. Create before/after code sketches

Deliverable Path:
  src/modules/<app>/WorkQueueAdapter.cpp or similar (refactored implementation)
  Documentation: plans/reports/app-migration-<date>-rzv2h-<app>-refactor-plan.md

Deliverable Format:
  - Current threading model (diagram)
  - Target work-queue model (diagram)
  - Per-task migration checklist (pthread → wq_run, blocking calls → nxsem_*, etc.)
  - HRT compatibility verification (timing preserved)
  - Test plan (existing tests still pass, performance comparable)

Success Criteria:
- [ ] Task refactored to use work_queue(HPWORK, ...) or work_queue(LPWORK, ...)
- [ ] All blocking calls replaced (sleep → usleep, sem_wait → nxsem_wait, etc.)
- [ ] Shared state protected with nxmutex (no race conditions)
- [ ] Application timing preserved (HRT measurement shows < 5% drift)
- [ ] Existing unit tests pass
- [ ] Memory footprint reduced (no per-task stack overhead)

Validation Command:
  # From the repository root, build the affected PX4 target:
  make renesas_rdk-rzv2h_default
  # Discover and run the existing focused test or contract for <app>;
  # do not invent a tests/modules path if none exists.
  # On board: monitor CPU utilization, task stack usage
```

### Example Invocation
```
Paste Recipe 5 with <app> replaced by sensor-manager, then invoke /ck:plan if needed.
```

---

## RZ/V2H Skill Workflow

Use the project-local skills as a fixed evidence loop around each roadmap
slice:

```text
audit-rzv2h-px4-nuttx-port
  -> ck:debug (when a failure is reproducible)
  -> gdb-jlink-debug (when on-target evidence is required)
  -> implement and verify
  -> ck:code-review --pending
```

| Need | Skill | Required output |
|---|---|---|
| Cross-layer parity and integration gap | `$audit-rzv2h-px4-nuttx-port <subsystem> <CR8_0|CR8_1|CM33>` | FSP/CMSIS, NuttX, board, PX4, build, and hardware-evidence trace. |
| Reproducible build or runtime failure | `$ck:debug <symptom>` | Root cause before a fix. |
| J-Link/GDB source, MMIO, or data-abort capture | `$gdb-jlink-debug` | ELF identity, probe/core, breakpoint, register/MMIO evidence, and conclusion. |
| Completed patch | `$ck:code-review --pending` | Spec-compliance, quality, and verification review. |

Use `gdb-jlink-debug` only after authorization for reset, load, continue, or
target writes. A read-only attach is the default hardware action.

## How to Use These Recipes

### Via Claude-Code
Copy the template, substitute placeholders, and paste it into Claude-Code.
Use `/ck:plan` with that completed request when a saved implementation plan is
appropriate.

**Substitution Rules:**
- `<driver>` → lowercase driver name (spi-b, uart, gpio, etc.)
- `<sample>` → exact EVK slug from `reference-source-map.md` (`adc_e`,
  `can_fd`, `sci_b_uart`, etc.); it is not always the NuttX driver name
- `<core>` → `cm33`, `cr8_0`, or `cr8_1`; never reuse generated vectors or
  configuration from another core without labelling it secondary evidence
- `<subsystem>` → subsystem group (gpio-icu, uart-scif, spi-dmac, ether, ipc-mhu)
- `<target>` → module or subsystem being migrated
- `<peripheral>` → hardware peripheral name
- `<app>` → PX4 application/module name
- `<date>` → current date in YYYY-MM-DD format

### Report Naming Convention
Deliverable reports go to:
```
plans/reports/
  driver-review-<date>-rzv2h-<driver>-review-report.md
  subsystem-audit-<date>-rzv2h-<subsystem>-audit-report.md
  migration-strategy-<date>-rzv2h-<target>-migration-plan.md
  hal-port-<date>-rzv2h-<peripheral>-hal-design.md
  app-migration-<date>-rzv2h-<app>-refactor-plan.md
```

---

## Related References

- [Design Guidelines](../design-guidelines.md) — detailed NuttX patterns
- [Porting Playbook](./porting-playbook.md) — step-by-step driver porting
- [FreeRTOS-to-NuttX Mapping](./freertos-to-nuttx-mapping.md) — API cheat sheet
- [Code Standards](../code-standards.md) — conventions and commit format

---

**Maintenance:** 
- Update recipes when new porting patterns emerge
- Track recipe use via report metadata (date, deliverable path)
- Promote successful patterns from reports back into playbook / guidelines
