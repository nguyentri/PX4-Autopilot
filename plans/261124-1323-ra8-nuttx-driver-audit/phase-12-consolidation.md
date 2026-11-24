---
phase: 12
title: "Phase 12: Consolidation and status docs"
status: pending
priority: P1
effort: "0.5d"
dependencies: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
---

# Phase 12: Consolidation

## Goal
Produce one ranked view of all findings and update the status docs, but only to the evidence tier actually reached.

## Files to Create / Modify
- Create: `plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-ra8-nuttx-consolidated.md`
- Modify (only if a tier changed): `docs/renesas/port-status-nuttx.md`, `docs/renesas/port-status-px4-hal.md` (RA8 rows)

## Tasks & Steps
1. Build a coverage table with every `ra_*.c` and every evk-ra8p1 config, the phase that covered it, its tier (stub / source-audited / build-clean / bounded on-target) and its verdict.
2. Merge the findings and rank them by severity. Remove duplicates of the same root cause that showed up in several phases. Mark each as regression, pre-existing, doc drift, missing evidence or intentional deferral, and give the RA8E1 blast radius.
3. List the FSP modules that have no NuttX driver and the NuttX drivers that have no FSP reference.
4. Propose a fix backlog grouped for later `/ak-cook` plans. Do not implement it.
5. Run the whole-plan sweep: check the links, the report paths, and that the dates and SHAs match phase 1.

## Verification
- Every success criterion in `plan.md` is checked against the reports.
