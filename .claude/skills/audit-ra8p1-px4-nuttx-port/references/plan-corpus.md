# Plan corpus routing

Read current source first. Use plans as history, decisions and evidence—not as
authority when they contradict the live tree. The RA8P1 corpus is small and
entirely historical.

## RA8P1 history

| Document | Use |
|---|---|
| `plans/ra8p1_px4_nuttx_gap_analysis.md` | Baseline gap list (marked historical). Re-verify each "CONFIRMED" item before citing it. |
| `plans/ra8p1_codex_gap_analysis_prompt.md` | The prompt that produced the gap analysis; scope and method only, not findings. |
| `docs/renesas/port-status-nuttx.md` | RA8 NSH-over-RTT buffer note for `fpb-ra8e1` / `evk-ra8p1`. |
| `docs/renesas/port-status-px4-hal.md` | `boards/renesas/evk-ra8p1/Kconfig` escaped-prompt note. |

Baseline themes from the gap analysis worth re-checking:

- CM33 `px4io_ipc` enablement (`MODULES_PX4IOFIRMWARE`, `add_subdirectory`).
- GPT motor-output ownership duplicated between CM85 and CM33 timer configs.
- IPC shared-memory base disagreement across PX4 linkers, board comments and
  NuttX board scripts.
- HRT on GPT0 with direct register access while ICU/ELC configs are off.
- SPI chip-select disagreement between manifest, docs and board code.

## Not RA8P1

- `plans/260729-1153-rzv2h-ra8p1-sih-demo/` is an RZ/V2H plan that only borrows
  the RA8P1 SIH idea. Do not use it as RA8P1 evidence.
- RZ/V2H plans and reports use different arch, boards and references.

## Supersession rule

Prefer the newest report for current findings and keep older reports for
regression comparison. When old and new disagree, verify the live source and
record which revision or user decision caused the change. New RA8P1 audit
reports go to the active plan's `reports/` or `plans/reports/`.
