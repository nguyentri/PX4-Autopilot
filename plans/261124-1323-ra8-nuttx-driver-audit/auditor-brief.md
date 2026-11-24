# Auditor brief (shared by every phase auditor)

Working directory: `/home/tringuyen/PX4-Autopilot`. Timezone Asia/Bangkok; the date is 2026-11-24. Write in English.

## Baseline (pinned)
- PX4 `87f03177dbd`, NuttX submodule `8f85716a87`, apps `ee45eec37`. The RA8 tree is clean.
- `refs/ra8p1/` is extracted and read-only. It holds `R7KA8P1KF_core0.h` (CM85), `R7KA8P1KF_core1.h` (CM33), `ek_ra8p1/<sample>/<sample>_ek_ra8p1_ep/e2studio/` (88 EK-RA8P1 FSP samples) and `evk_ra8p1_dual_core/RA8P1_DSP_example{,_cpu0,_cpu1}/` (the only `r_ipc` carrier). Use the `e2studio/` copy and ignore `Debug/` outputs.
- Path prefixes: `A` = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`, `E` = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/evk-ra8p1`, `F` = `platforms/nuttx/NuttX/nuttx/boards/arm/ra8/fpb-ra8e1`.

## Method
Follow the skill `.claude/skills/audit-ra8p1-px4-nuttx-port/SKILL.md` and its references: `repository-map.md`, `audit-checklists.md`, `hardware-fact-parity.md`, `register-offset-audit.md` and `evidence-and-verdicts.md`. Read the ones your slice needs. Run `.claude/skills/audit-ra8p1-px4-nuttx-port/scripts/collect-audit-context.sh <topic>` per module.

Trace each capability per core: the FSP `configuration.xml`/`ra_gen`, the device header, `r_<module>`, Kconfig/Make.defs/CMakeLists.txt, the lower-half `ra_*.c` and `hardware/ra8p1/*.h`, the NuttX upper-half, board glue and defconfig, apps, PX4, ELF symbols and target evidence. Mark a layer N/A only with a reason.

## Hard constraints
- Static audit only. Do not build, configure, run `make` or `build*.sh`, flash, or touch hardware. The only build evidence is that `evk-ra8p1:adc-b` and `adc-b-hwtrigger` built clean as CM85 (2026-11-24). For every other config the ELF symbol layer is "not built (user declined builds)".
- Do not edit any source, config, doc or skill file. Write only your own report file.
- `refs/` is read-only. SCI10/SCI11 ELC events are out of scope.
- State the RA8E1 (`fpb-ra8e1`) blast radius for every finding in shared ra8 code.
- No finding IDs in proposed code comments.

## Finding record (per evidence-and-verdicts.md)
Each finding gives: an ID prefixed with your phase tag (for example `ARCH-01`), the severity (Critical/High/Medium/Low or validation gap), the confidence, the core, a concrete failure sequence, implementation evidence `path:line`, reference evidence `path:line` (or an absent-reference note), the affected configs including RA8E1, a minimal remediation, and the classification (regression / pre-existing / drift / validation gap / deferral). Proof of a defect must come from code; a missing reference only lowers confidence.

## Report layout
1. Scope, core(s), baseline.
2. A trace matrix per core: layer, anchor, status, and the FSP sample path used.
3. Findings, ordered by severity.
4. Items checked and found correct (brief, with `verified by path:line`).
5. Rejected or unsupported paths, and dead code.
6. Evidence tier reached per driver (E0-E3) and a verdict.
7. Unresolved questions.

End your final message with:
```
Status: DONE | DONE_WITH_CONCERNS | BLOCKED | NEEDS_CONTEXT
Summary: one or two sentences
Top findings: up to 5 one-line items with severity
```
