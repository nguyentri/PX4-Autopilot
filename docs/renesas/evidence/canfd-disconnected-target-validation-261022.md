# CAN-FD disconnected-board validation — 2026-10-22

RDK-RZ/V2H, CR8-0; board revision unspecified. The user reports CAN1/CAN2
are disconnected and authorized sample RAM loads/runs. No wiring change,
requested SoC reset or CM33/CR8-1 connection occurred. Evidence is limited
to named warm RAM-load images, Classic internal loopback and missing-ACK cleanup.

[Target report](../../../plans/reports/debug-261022-0838-canfd-disconnected-validation.md),
[raw logs, decoded registers and exact results](../../../plans/261022-0756-canfd-disconnected-validation/artifacts/results.json),
[acceptance verification](../../../plans/261022-0756-canfd-disconnected-validation/artifacts/verification.json).

## Observed

- `canfd-rtt`: three four-frame HW0 loopback runs pass ID/DLC/payload comparison;
  final application exit is 0, with reset mode, standby output high and no task left.
- `canfd-dual`: two accepted four-frame HW0 payload captures pass. Exact-image
  GDB checks both HW0 and HW3 in internal loopback, then reset and isolated after close.
- Supplemental dual build: only `CONFIG_EXAMPLES_CAN_DEVPATH` changes to
  `/dev/can1`. Two four-frame HW3 runs pass byte comparison, then close;
  driver counters show submitted=8, failed=0 and IRQ-completed=0.
- `canfd-ext`: two `rzv_canfd -n 1 -t 100` invocations fail at the first Classic
  length-zero CAN1→CAN2 case, as expected without a peer ACK. Cancellation,
  close and reopen complete; the directly captured application status is 1.
  Final counters show submitted=2, failed=2, last-result=-140 (ECANCELED),
  active=0 and IRQ-completed=0. Error IRQ logs contain AERR+BEF and error-passive.
- All 49 mechanical acceptance checks pass over retained transcripts, including
  28 Classic frames. Capture attempts with transport/synchronization failures
  are retained and excluded. Final preflight has no probe owner or busy debug port.

## Register checks

Both channels use NCFG `0x30926001` and DCFG `0x07070f00`. The global CFG
is `0x1`, with DCE/DRE clear. Global mode is operational and RAM initialization
is complete. AFL count words are `0x10000`, `0x1`, `0`, mapping HW0/FIFO0
and HW3/FIFO1. Their RX FIFOs report empty after the tests.

While open, channel CTR is `0x07002f00` for internal loopback and `0x2f00`
for normal operation; STS is `0x80`. Normal-mode PA2/PA3 output latches are
low; internal loopback and final close have both high (`P2A & 0xc == 0xc`).
After close, CTR/STS are `0x2f01`/`0x1`, RX IRQ enables are clear,
channel ICU routes are detached, and TX mailbox statuses 0/192 are zero.
Shared FIFO enable and global RX/error routes persist by design.

Clock monitors show CAN clock bits enabled, module-stop bit clear and reset
monitor bits deasserted. P8 function fields for P80/P81/P86/P87 are mode 5.
GIC IRQs 385..390 contain priority `0xc0`; packed ICU source selectors are
366/367/368/354/371/357. Correct priority address base is `0x12c11400`.
The initial wrong-offset read is excluded. CPU and GDB peripheral reads agree.

Both FDCFG registers read **0**, with TDC disabled. The prior
[FSP settings review](../../../plans/reports/code-review-261022-0733-canfd-fsp-parity.md)
identified this settings-parity gap; the target read now establishes the value
on these images. This run does not qualify FD/BRS at the configured data bitrate.

## Exact images

All shipping images are from the repaired source archive. The supplemental
build preserves the same production NuttX patch SHA-256
`23c9e1455ac61be35b40c5485ac2b75ba4e94aaca2504ff3727eba2bba93e1bc`.

| Image | ELF SHA-256 |
|---|---|
| `canfd-rtt` | `15697eb83ac4b158315915f5427a66a291f45efa624847720b0fb8775854a849` |
| `canfd-dual` | `187ecd5c8a7596b27bb03f2ca6529ca22ae92b73817a14e7615cb110dba9ff5b` |
| `canfd-ext` | `7e63ec37423788187860a2dfc0e9104f3a77c004166487971e6be68a7e8799ac` |
| `canfd-dual-can1-validation` | `57ddbdacfae1209311592e505d3c0c420cc77b3f0493ee84ff26db31928e37d7` |

Full paths, resolved configuration hashes, receipts and commands are in the
linked results JSON. Original resolved profiles and production source changes
were preserved. The temporary HW3 device-path profile was removed after archive.
The board was left running the original `canfd-rtt` ELF, CAN closed and isolated.
The initial DBGEN failure stopped before download; the user explicitly approved
retry and stopping the separate interactive JLinkExe owner. All later guarded
loads succeeded without reset markers. Probe identifiers are redacted.

## Remaining qualification

Classic lengths 1..4 are covered in internal loopback; this does not establish
successful normal-mode TX/RX interrupt delivery or connected CAN-FD/BRS data.
Only the HW0 normal-mode error interrupt is demonstrated. The missing-ACK test
stops before FD frames, and never reaches HW3 normal-mode transmission.
The 100 ms setting is a software deadline; complete capture calls took about
2.1–2.6 s including paced RTT and health commands. No precise deadline or
absolute bus bitrate was independently measured.

FSP TDC parity, transceiver voltage/timing, termination, electrical standby,
connected-bus recovery, stress and expansion channels HW1/2/4/5 remain open.
GPIO output-register reads establish software state, not measured pin voltage.
This record extends bounded on-target coverage; it does not establish production readiness.
