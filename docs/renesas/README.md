# RZ/V2H Documentation Index

Mini-index for RDK-RZ/V2H porting documentation. Start here for RZ/V2H-specific content.

---

## Quick Navigation

### For Hardware & Pinout

1. **[hardware.md](./hardware.md)** — Clocks, memory map, GIC/ICU, DMAC, MHU, boot flow
2. **[pinmap.md](./pinmap.md)** — Authoritative pin ownership matrix; cross-check against pin_data.c

### For Driver Development

3. **[port-status-nuttx.md](./port-status-nuttx.md)** (Phase 2) — Driver status table: ported, tested, integration state
4. **[porting-playbook.md](./porting-playbook.md)** (Phase 2) — Step-by-step: add a new driver, FSP→NuttX recipe
5. **[freertos-to-nuttx-mapping.md](./freertos-to-nuttx-mapping.md)** (Phase 2) — POSIX/FreeRTOS → NuttX API cheat sheet

### For IPC & Multi-Core

6. **[ipc-architecture.md](./ipc-architecture.md)** (Phase 3) — IPCC/MHU, uORB bridge framing, CRC, sequence checks
7. **[multicore-memory-map.md](./multicore-memory-map.md)** — Ratified CR8-0/CR8-1/CM33 unified memory map & per-core address aliases (single source of truth)

### For Validation & Debugging

7. **[validation-checklist.md](./validation-checklist.md)** (Phase 3) — Per-driver bring-up checklist, FreeRTOS equivalence checks
8. **[prompt-recipes.md](./prompt-recipes.md)** (Phase 2) — Reusable Claude prompts: driver review, HAL port, migration

### AI-Assisted Porting Workflow

Use the project-local skills in this order for a bounded RZ/V2H change:

1. **[audit-rzv2h-px4-nuttx-port](../../.claude/skills/audit-rzv2h-px4-nuttx-port/SKILL.md)** — FSP/CMSIS-to-PX4 cross-layer audit.
2. **[ck-debug](../../.claude/skills/ck-debug/SKILL.md)** — root-cause proof for a build or runtime failure.
3. **[gdb-jlink-debug](../../.claude/skills/gdb-jlink-debug/SKILL.md)** — J-Link/GDB hardware evidence when source tracing is insufficient.
4. **[ck-code-review](../../.claude/skills/ck-code-review/SKILL.md)** — review the completed diff and its verification evidence.

Do not use RTT, build success, or a static register comparison as a substitute
for on-target evidence. GDB/J-Link reset, ELF load, and target writes require
explicit authorization.

### For Future Status

9. **[port-status-px4-hal.md](./port-status-px4-hal.md)** (Phase 3) — PX4 HAL integration status per peripheral

### Peripherals Deep Dives (TBD)

10. **[peripherals/canfd.md](./peripherals/canfd.md)** (Phase 3+) — CAN-FD dual-channel notes
11. **[peripherals/sdhi.md](./peripherals/sdhi.md)** (Phase 3+) — SDHI SD/eMMC driver, LittleFS mount
12. **[peripherals/adc.md](./peripherals/adc.md)** (Phase 3+) — 12-bit ADC, sensor buffering

---

## Recommended Reading Order for Newcomers

1. **Start:** [../project-overview-pdr.md](../project-overview-pdr.md) (5 min) — understand scope
2. **Understand:** [../system-architecture.md](../system-architecture.md) (10 min) — architecture layers
3. **Map:** [../codebase-summary.md](../codebase-summary.md) (15 min) — where code lives
4. **Hardware:** [hardware.md](./hardware.md) (10 min) — RZ/V2H blocks & clocks
5. **Pinout:** [pinmap.md](./pinmap.md) (5 min) — pin assignments
6. **Deep dive:** specific driver in porting-playbook.md or prompt-recipes.md

**Total:** ~45 minutes to orientation.

---

## Phase Coverage

| Phase | Files | Status |
|-------|-------|--------|
| **Phase 1 (Foundational)** | README.md, hardware.md, pinmap.md | IN PROGRESS |
| **Phase 2 (Workflow)** | port-status-nuttx.md, porting-playbook, freertos→nuttx mapping, prompt-recipes | PENDING |
| **Phase 3 (Status & Validation)** | port-status-px4-hal.md, ipc-architecture, validation-checklist | PENDING |
| **Phase 4 (Peripherals)** | peripherals/*.md (canfd, sdhi, adc) | PENDING |

---

## Key Reference Links

- **Master Plan:** [../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md](../../plans/260726-2218-rzv2h-px4-nuttx-goal-plan/plan.md)
- **Historical Plan:** [../../plans/rzv2h_nuttx_px4_unified_port_plan.md](../../plans/rzv2h_nuttx_px4_unified_port_plan.md) (superseded 2026-07-26)
- **RDK-RZ/V2H Board Pinout:** [../../boards/renesas/rdk-rzv2h/src/pinout.md](../../boards/renesas/rdk-rzv2h/src/pinout.md) (BOM, header, peripheral pin assignments, and wiring)
- **Pin Data Source:** [../../refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c](../../refs/px4-freertos-posix-renesas-fsp/rzv_gen/pin_data.c) (authority for pinmap.md)
- **NuttX Driver Port:** [../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/](../../platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/)
- **PX4 Board Definition:** [../../boards/renesas/rdk-rzv2h/](../../boards/renesas/rdk-rzv2h/)

---

## File Naming Convention

All files in this directory use kebab-case (e.g., `port-status-nuttx.md`, `freertos-to-nuttx-mapping.md`). This ensures Grep/Glob tools recognize them as self-documenting.

---

## Maintenance Cadence

- **Per PR:** Update `port-status-nuttx.md` and `pinmap.md` when a driver changes
- **Quarterly:** Review hardware.md for register/clock drifts
- **Yearly:** Full validation-checklist re-run and phase status update

---

## Document Ownership & Status

| Doc | Owner | Last Updated | Status |
|-----|-------|--------------|--------|
| README.md | docs-manager | 2026-07-11 | Phase 1 ✓ |
| hardware.md | docs-manager | 2026-07-11 | Phase 1 ✓ |
| pinmap.md | docs-manager | 2026-07-11 | Phase 1 (draft) |
| port-status-nuttx.md | TBD | — | Phase 2 |
| porting-playbook.md | TBD | — | Phase 2 |
| freertos-to-nuttx-mapping.md | TBD | — | Phase 2 |
| prompt-recipes.md | TBD | — | Phase 2 |
| ipc-architecture.md | TBD | — | Phase 3 |
| validation-checklist.md | TBD | — | Phase 3 |
| port-status-px4-hal.md | TBD | — | Phase 3 |
| peripherals/canfd.md | TBD | — | Phase 3+ |
| peripherals/sdhi.md | TBD | — | Phase 3+ |
| peripherals/adc.md | TBD | — | Phase 3+ |

---

## Questions?

For questions about structure or content, see the brainstorm report at `plans/reports/brainstorm-260711-0827-rzv2h-port-docs-init-report.md`.
