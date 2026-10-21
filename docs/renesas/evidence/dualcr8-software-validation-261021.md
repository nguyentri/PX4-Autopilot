# Dual-CR8 software validation receipt

**Scope:** canonical CR8-0 `renesas_rdk-rzv2h_dualcr8` sensor bring-up and the
CR8-1 `renesas_rdk-rzv2h-io-cr8_1_pwm` supervisor candidate
**Date:** 2026-10-21
**Evidence tier:** build-clean and host-checked; no hardware tier promotion

This receipt records the durable facts from the final review-fix verification
run. Detailed logs and machine JSON remain local evidence under
`plans/reports/261021-1422-review-fixes-evidence/` and
`build/rzv2h-review-fixes-default-261021-1422-final/`; those paths are not
required to reproduce the status claims below.

## Accepted software boundary

- `dualcr8` is the canonical exact-BOM CR8-0 sensor profile. Its checked-in
  board contract selects one polled ICM-45686 on P93, BMM150, BMP390, M10 and
  TFmini. `dualcr8.px4board` disables local PWM/DShot and the legacy PX4IO
  bridge, and requires first I/O status before arming.
- The CR8-1 `pwm` image is a compiled v3 supervisor candidate. The shared
  `src/apps/` CMake target is `rzv2h_demo`; it is not a `src/lib/rzv2h_demo`
  tree. The candidate hardware contract currently returns zero output
  profiles, output rate, output mask and hardware contract. Its status is
  therefore **UNCONFIGURED/inhibited**, and it is not an admitted actuator
  peer.
- The candidate source separates controller, 400 Hz worker (2.5 ms period)
  and status reporter. The logical output lease is 50 ms. Any external cutoff
  remains `50 ms + 2.5 ms + declared measured scheduler/HAL budget`; no exact
  50 ms physical cutoff or core-halt containment result is claimed. Epoch
  adoption resets the responder session view, and a worker epoch change resets
  its generation comparison baseline while retaining inhibition and fault
  latches.
- No hardware identity, ESC/power/storage/kill selection, reset/core-halt
  containment result, battery policy, persistent-storage proof or physical
  output qualification is recorded here. There is no admitted CR8-0/CR8-1
  actuator pair, deployed A55 gateway/ROS/DRP-AI path, or validated-flight
  claim.

## Verification results

The final isolated source snapshot recorded:

- **61 host suites / 583 cases: PASS** (`PASS=61`, `FAIL=0`, `NOT-RUN=0`).
- Functional `mixer_module_tests` and `CollisionPrevention`: **PASS**.
- Firmware builds: **PASS** for `renesas_rdk-rzv2h_dualcr8`,
  `renesas_rdk-rzv2h-io-cr8_1_pwm`, and an isolated legacy
  `renesas_rdk-rzv2h_default` archive.
- Five candidate ELF/ROMFS/package artifact cases and the isolated default
  archive check: **PASS / BUILD-CHECKED**. All target actions were empty and
  on-target status was `NOT-RUN`.

The final firmware ELF SHA-256 values were:

| Target | SHA-256 |
|---|---|
| `renesas_rdk-rzv2h_dualcr8` | `044010f7e75e2c92c60d65d420a48254cf99ced7f63bccd44dd8cd1ecb0dfd37` |
| `renesas_rdk-rzv2h-io-cr8_1_pwm` | `f948d898c8b692858d7a76486d961b266b6575b741931398dc67b55dcf05e6dc` |
| isolated `renesas_rdk-rzv2h_default` | `a13c1849d136cd2dcff0839784e1e544e363c4900d2b5a440cbd38064ecb6676` |

The isolated default archive SHA-256 was
`470c9d4d93948e959e7a3f0f501c35b14cbd891743c755fb16e5132ce2a3e14d`.

The implementation was subsequently committed as parent `30e81622635`, with
the obstacle-bin bounds fix in `5e68270877c` and NuttX board changes in
`cc10d09f984d993e39b7ba04cfba9b15425cf75c`. The ELF hashes above identify
the verification builds before these local commits; a rebuild may have
different Git version metadata.

Commit preparation removed one extra blank line at the end of
`init/dualcr8/rc.board_sensors` and refreshed its policy-pinned source hash.
The artifact checker rejected the intermediate stale hash, then passed after
the refresh. Startup commands were unchanged. The final source/policy passed
8 profile cases, 5 actual candidate artifact cases, 26 CI-policy cases and
11 artifact-parser unit cases. The isolated default archive retains its
original frozen source/policy receipt.

## Review repairs covered by the receipt

The six review findings were repaired and covered by the final host/build
verification:

1. consumed mixer publication values and progress now use one coherent
   publication timestamp;
2. an offline responder can adopt a new initiator epoch;
3. worker fault recovery establishes a new epoch baseline while preserving
   the inhibit latch;
4. gateway wording and status are component-only software contracts, with
   runtime transport, uORB and Commander integration still pending;
5. timing wording distinguishes the 50 ms lease, 2.5 ms worker period and
   measured scheduler/HAL cutoff from unqualified core-halt containment; and
6. model deployment wording uses the actual TVM compiler artifact boundary.

## Source and policy anchors

- [canonical CR8-0 profile](../../../boards/renesas/rdk-rzv2h/dualcr8.px4board)
- [CR8-1 candidate profile](../../../boards/renesas/rdk-rzv2h-io-cr8_1/pwm.px4board)
- [shared application target](../../../src/apps/CMakeLists.txt)
- [zero-default hardware contract](../../../src/apps/hardware-contract.hpp)
- [PX4 profile policy](../../../Tools/rzv2h-px4-profiles.json) (policy version
  3; nine RZ/V2H profiles)
- [host regression catalog](../../../Tools/rzv2h-regression-catalog.json)

The software claims can be rechecked with the repository-owned profile and
regression tools described in [the regression procedure](../validation/rzv2h-regression-ci.md).
They remain software evidence only; physical selection, containment, battery
acquisition and policy, power-loss persistence, and manual-kill qualification
are open gates.
