# CR8-0 DShot600 and DMAC validation

The 2026-10-20/21 RDK-RZ/V2H bench run verifies bounded, disarmed DShot600
motor-stop transfers on CR8-0. All four channels consume 128 bytes, and a
second module start/stop succeeds. This establishes DMA completion on the
named image; electrical waveforms, nonzero throttle and ESC response remain
unqualified.

## Image and source identity

Device: `R9A09G057H44_R8_0`; console: RTT at `0x081a2400`.
The images were built from working changes on PX4 base
`62b798a32e07df8e89fe3831971d32ea39682dba` and NuttX base
`68b60a174ca98782f3aed089c3ca2d2ecf49087e`.

| Artifact | SHA-256 |
|---|---|
| `renesas_rdk-rzv2h_dshot.elf` | `31f1b6078dc2bdefbfede1ea4e31b42a22fe7d3c7afda628939cf06e3b1ba78e` |
| Repaired `dmac-memcpy-rtt` NuttX ELF | `d71be6f935e8ef28057c3f0b8bb6d1b576dedcb6d7ac37676a856a3f88cce128` |
| `rzv_dmac.c` | `4f3ad8749049c96dd38205863874798e6d4dd10aedc6a47ff6faee04a243e6d9` |
| `rzv_dmac.h` | `4a6bebf1ac0260c5eb89ec6bd04e93fa71adf03a30573b8d4d90f99178137efc` |
| `hardware/rzv_dmac.h` | `8c96a01d868f516096f74ec3a97d1f5942fe3651b290d01ca4b3546e8a789bac` |
| `hardware/rzv_intc.h` | `90d14c76729d943474d232df08f0aea2ab31808c8b477b7b88b1f3670602d510` |
| PX4 `dshot/dshot.c` | `a10a8f6682ea6c981c42b1fcc791bd4ffbf6fedaf97e39b42443d419a983f3db` |
| Shared PX4 `nsh/defconfig` | `10e4f5fc98005e48c5c5c423e310fbb08aefbfb537223b160eb12667313add60` |

The source hashes identify the tested working revision independently of the
base hashes printed by `ver all`. Required build wrappers passed for DShot,
default PX4 and the standalone DMAC sample. No flight arm or nonzero actuator
stimulus was used, and CR8-1/CM33 were not connected.

The reviewed implementation was subsequently committed as NuttX
`5cf2c27ac7ac77cf9df4b7f78f4981e7b4f3c72b` and PX4 `c3603d73076`.
The tested source/configuration hashes above remain unchanged.

## Diagnosis and repair

CPU register access works on all five DMAC units. The fresh DMAC0 control
reproduces a GPT destination write fault: `CHSTAT_ER`, group errors `0xf`,
source advancement of four bytes and 124/128 bytes remaining. It does not
establish a universal inability to access DMAC0–2 registers or GPT.

The repaired driver separates CHEXT AXI protection attributes from priority,
corrects ICU bus-status offsets, rejects active hardware at configure, clears
inactive stale status and software-owned event routes, and restores/verifies
hardware event routes before each start. Polling ownership disables route
auto-clear and preserves neighboring selectors. First-failure diagnostics
read only the initialized DMAC unit before reset. An initial diagnostic
attempt read inaccessible SYS registers and aborted; those reads were removed.
Debugger fill `0xaaaaaaaa` was not interpreted as a policy value.

Old DMAC0 GPT event selections survived the RAM-image handoff. The initial
DMAC3 comparison stalled with disabled routes. The repaired RAM-copy fixture
explicitly adopted our inactive old channels and released their routes;
subsequent DShot transfers on explicit DMAC3 channels 56–59 completed. This
supports the stale-route diagnosis; the exact hardware rejection sequence was
not instruction-traced. Renesas prohibits duplicate event selections. The
driver does not change global access policy or steal other channel routes.

DShot latches its HAL state off on frame/start failure until explicit recovery
and logs its first verified complete frame once per initialization. Shared
NSH parser/stack budgets also allow the full PX4 startup script to finish.

Primary authority: Renesas R01UH1032EJ0140,
[RZ/V2H hardware manual](https://www.renesas.com/en/document/mah/rzv2h-group-users-manual-hardware),
§4.7.5.2.14 (CHEXT), §4.6.1.2.2(15) (BEISR),
§4.6.1.2.2(32) (request selection/CLRON and duplicates), and Table 1.7-1
(GPT access). Core-matched local FSP/CMSIS views corroborate mapping/offsets.

## Executed evidence

The [retained transcript](dshot-dmac-cr8-0-transcript-261020.txt) contains ten
named captures, including the failed control, repaired runs and cleanup.
Trailing whitespace is trimmed in the retained copies; each capture records
both its original sanitized-file hash and the retained-body hash:

- `rzv_dmac 0 8 9 10 11 16 24 32 40 48 56 64 72`, twice: **26/26**
  one-KiB comparisons pass across both groups of all five units.
- Repaired boot and restart log `DShot TX frame complete: channels 0xf,
  128 bytes each`. The log follows terminal count on every active channel
  and successful quiescence. Motor functions 101–104 have zero values;
  commander is disarmed and PWM owns no mixer functions.
- Final snapshot: DMAC3 local channels 8–11 have zero remaining bytes,
  sources advanced 128 bytes and no channel/group errors. HAL state is off;
  all four GPT counters and output-enable gates are disabled. DShot/PWM
  modules are stopped; inactive DMA configuration/routes remain owned.
- Two RTT-attached HRT checks exceeded the sleep bound: 113,116 and
  177,030 µs. The control/status and restart transcripts retain both failures. A delayed
  check with the probe detached passes at 10,167 µs sleep and 4 µs callback
  latency; its temporary files were removed. This supports probe timing
  interference without establishing long-run timing.

Focused host checks pass: production DMAC **19/19**, DShot **23/23**, startup
and board profiles **19/19**, and register-layout **2/2**. These model MMIO
boundaries and compare CMSIS layouts; they do not prove physical timing.
Review on 2026-10-21 found no blocking defect in this scoped revision.
No task-owned J-Link/GDB/RTT processes or debug listeners remained after the
run; the repaired image was left resident and disarmed. Later host review
reconfirmed that no debug processes remained.

## Remaining qualification

The precise boot-policy reason for DMAC0 GPT write rejection remains unknown
because SYS access was unavailable. Physical four-pin waveforms, nonzero
throttle, powered ESC response, cold-cycle and soak behavior remain open.
These captures qualify the named motor-stop path and channels only.
