---
title: RZ/V2H ADC Ethernet SCIF Audit Fixes
status: completed
priority: P1
effort: high
branch: gitlab-migration
tags: [rzv2h, firmware, adc, ethernet, scif]
created: 2026-08-09
source-report: ../reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md
---

# RZ/V2H ADC, Ethernet, and SCIF Audit Fixes

## Overview

Fix source-proven defects from Mission 1. Keep board/manual-dependent clock, pin, IRQ, and PHY timing changes blocked until authoritative evidence and HIL exist.

## Phases

- [x] Scout active drivers, callers, references, history, and tests.
- [x] Diagnose root causes and authority boundaries.
- [x] Implement source-proven fixes; see [phase 1](phase-01-source-proven-fixes.md).
- [x] Add regression contracts and run focused builds/static checks.
- [x] Review, update report status, and record unresolved hardware questions.

## Dependencies

- Checked-in core-matched EVK FSP/CMSIS references for ADC and SCIFA CPG.
- Checked-in legacy CA55 GBETH reference as secondary same-IP evidence only.
- NuttX network, ICU, serial, and linker contracts.

## Acceptance Criteria

- Every applied fix maps to a verified finding and root cause.
- Regression contracts fail against the pre-fix source and pass against the edited source.
- Focused driver builds or syntax checks pass.
- Hardware-authority blockers remain explicit; no fabricated literals.
- Audit report records fixed, partial, and blocked outcomes.
