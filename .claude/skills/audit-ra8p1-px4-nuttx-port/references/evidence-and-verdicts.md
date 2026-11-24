# Evidence and verdicts

## Evidence ladder

| Tier | Meaning | Allowed claim |
|---|---|---|
| E0 | File/stub exists | `stub` only |
| E1 | Static trace and reference comparison | defect/parity hypothesis |
| E2 | Configured compile, final link and symbol proof | `build-clean` |
| E3 | On-target operation with archived output/measurements | `functional` |
| E4 | Repeated/stress/fault testing on intended hardware | `production` candidate |

Never promote status above the strongest completed tier. A build-only test is
not hardware proof. A loopback is not proof of board-level device integration.
An EK-RA8P1 FSP sample running on this board proves the hardware and FSP
path, not the NuttX/PX4 port.

## Reference availability

Record for each layer whether the reference was present, partial or absent:

- device header: `R7KA8P1KF_core0.h` (CM85) or `R7KA8P1KF_core1.h` (CM33),
  matching the audited core;
- FSP module: carrier sample path, or absent;
- feature/event tables: the sample's `bsp_feature.h` / `bsp_elc.h` line, or the
  manual section for a fact they do not encode;
- pin data: EK-RA8P1 FSP (board authority), agreeing or disagreeing with
  `evk-ra8p1` board files.

An absent reference lowers confidence; it is not a defect by itself.

## Severity

| Severity | Definition |
|---|---|
| Critical | Can prevent boot, corrupt executable/shared state, defeat a safety boundary, or damage hardware |
| High | Supported common path can hang, corrupt data, route the wrong resource, or fail deterministically |
| Medium | Bounded scenario produces wrong behavior, leak, race, or incomplete cleanup |
| Low | Maintainability, diagnostics or uncommon behavior with limited operational impact |

Severity requires a concrete failure sequence. Missing evidence is not itself a
runtime defect; label it `validation gap` unless code proves failure.

## Confidence

- High: current implementation and primary reference agree on the relevant fact.
- Medium: code trace is strong but a hardware/manual fact remains unresolved.
- Low: inference depends on stale plans, absent reference, or unknown wiring.

Ask the user only when confidence remains below roughly 85% after source search,
or when resolving the issue changes confirmed scope or hardware ownership.

## Verdicts

- `PASS`: no in-scope finding and required evidence tier met.
- `PASS_WITH_LIMITATIONS`: safe bounded slice works; exclusions stated.
- `DONE_WITH_CONCERNS`: audit complete; unresolved non-blocking findings remain.
- `FAIL`: one or more blocking findings invalidate the claimed capability.
- `BLOCKED`: required primary evidence or authorized validation is unavailable.

## Finding record

For each finding record:

1. Severity and confidence.
2. Claimed capability and core.
3. Concrete failure sequence and impact.
4. Implementation evidence (`path:line`).
5. Reference or contract evidence (`path:line`), or the absent-reference note.
6. Consumers/configurations affected, including `fpb-ra8e1` for shared code.
7. Minimal remediation and validation command/procedure.
8. Classification: regression, pre-existing, drift, validation gap, or deferral.

## Sticky decisions

Once verified, annotate `verified by path:line` or `verified by test <name>`.
Do not reverse on reviewer opinion alone. State new evidence or changed context.
Never silently reverse a user-confirmed core, feature boundary, threshold, or
hardware ownership decision.
