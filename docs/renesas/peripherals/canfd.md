# CAN-FD Peripheral Notes

**Updated:** 2026-10-22

**Hardware:** RDK-RZ/V2H, R9A09G057H, CR8-0

**Status:** bounded on-target for HW0/HW3 Classic internal loopback and
HW0 missing-ACK cancellation/close/reopen. The
[2026-10-22 target record](../evidence/canfd-disconnected-target-validation-261022.md)
covers the disconnected-board campaign. Successful connected CAN-FD/BRS traffic
and TX/RX success IRQ delivery remain open. See
[the status inventory](../port-status-nuttx.md).

## Source owners and profiles

NuttX paths below are relative to `platforms/nuttx/NuttX/nuttx/`:

| Owner | Path |
|-------|------|
| Lower half / register definitions | `arch/arm/src/rzv/rzv_canfd.{c,h}`, `hardware/rzv_canfd.h` |
| Public status/cancel ABI | `include/nuttx/can/rzv_canfd.h` |
| Board pins and registration | `boards/arm/rzv/rdk-rzv2h/{include/board.h,src/rzv2h_canfd.c}` |
| Dedicated command (apps submodule) | `../apps/examples/rzv_canfd/` |

| Build config | Channels | Mode / command | Console |
|--------------|----------|----------------|---------|
| `canfd` | HW0 | Internal loopback, generic `can` | SCI4 |
| `canfd-rtt` | HW0 | Internal loopback, generic `can` | RTT |
| `canfd-dual` | HW0+HW3 | Internal loopback, generic local `can` | SCI4 |
| `canfd-ext` | HW0+HW3 | Normal bus, dedicated `rzv_canfd` | RTT |

Build with `platforms/nuttx/NuttX/build.sh <config>` from the repository root.
The connected command is enabled only in `canfd-ext`; it uses extended IDs,
CAN-FD and `CONFIG_CAN_FIFOSIZE=2` (one usable upper-half TX ring entry).
The generic CAN sample and upper half are unchanged.

## Device, pins and wiring

| Device | Kconfig | HW channel | RDK port | TX / RX | RX FIFO | Standby |
|--------|---------|------------|----------|---------|---------|---------|
| `/dev/can0` | `RZV_CANFD0` | 0 | CAN1, J2 | P80 / P81 | 0 | PA2 |
| `/dev/can1` | `RZV_CANFD3` | 3 | CAN2, J3 | P86 / P87 | 1 | PA3 |
| `/dev/can1` or `/dev/can3` | `RZV_CANFD1` | 1 | Expansion pads | P82 / P83 | 1 or 3 | External owner |
| `/dev/can2` | `RZV_CANFD2` | 2 | Expansion pads | P84 / P85 | 2 | External owner |
| `/dev/can4` | `RZV_CANFD4` | 4 | Expansion pads | P42 / P43 | 4 | External owner |
| `/dev/can5` | `RZV_CANFD5` | 5 | Expansion pads | P46 / P47 | 5 | External owner |

All six hardware channels (0..5) can be enabled together. All CAN signals
use PSEL 5. HW1 remains exclusive with SCI9 (GPS M10). When HW3 is selected,
HW1 uses `/dev/can3` and FIFO3 so onboard HW3 retains `/dev/can1` and FIFO1.
Without HW3, HW1 retains its legacy `/dev/can1` and FIFO1. HW2/4/5 have fixed
node/FIFO indices. This preserves the existing CAN1/CAN2 sample paths.
Onboard CAN2 uses HW3; it does not conflict with SCI9.

Select optional channels with `CONFIG_RZV_CANFD1/2/4/5`. They default off and
require external transceivers plus exclusive pad ownership. The pad muxes
come from native RZ/V2H pin definitions; they do not establish RDK connector
routing or fitted external circuitry. Only HW0/HW3 have onboard standby
callbacks and the bounded cancellation capability. Other channels return
`ENOTSUP` for cancellation until their board integration supplies isolation.
The [supplied schematic](../rzv2h-rdk-canfd.png) and
[official communication guide](https://renesas-rdk.github.io/rzv2h_rdk_documentation/latest/chapter-2/common_interfaces/communication_interface.html)
identify the onboard ports. The schematic shows a dual TCAN1046VDMTRQ1 and
two 60.4 Ω split-termination resistors per port. Verify the fitted board
revision and termination; do not add terminators without checking it.

Connect **J2.1↔J3.1 CANH, J2.2↔J3.2 CANL, J2.3↔J3.3 GND**. Connect through
the transceivers, using these bus connectors. Keep Linux/other cores from
owning CANFD or these GPIOs and exclude other CAN writers or bus traffic.

PA2/STB1 and PA3/STB2 are high for standby, low for normal mode. Board
initialization holds standby high before pin setup. First open lowers only
a successfully configured normal-mode channel; loopback remains isolated.
Mode changes allow 20 µs per the [TI datasheet](https://www.ti.com/lit/ds/symlink/tcan1046v-q1.pdf).
Setup failure, cancellation and last close assert standby. Physical polarity,
levels and transitions still need measurement on the fitted RDK.

## Register and interrupt contracts

- Controller base: `0x12440000`. A channel's mailbox 0 index is `channel*64`;
  HW3 uses mailbox 192, ID window `0x12456000`, control `0x12440390`, status
  `0x12440890`, TX enable `CFDTMIEC[6]` bit 0 at `0x12440f68`.
- Sparse acceptance rules use HW0's count in `CFDGAFLCFG[0]` high half and
  HW3's in `CFDGAFLCFG[1]` low half. Every enabled channel has one rule;
  its count uses register `channel/2`, high half for even channels and low
  half for odd channels. Consecutive rules follow ascending hardware channel
  order and route to the descriptor's dedicated FIFO. All six enabled gives
  count registers `[0..2] = 0x00010001`. Sparse high-channel sets preserve
  their hardware count fields while packing their rule entries from zero.
- DLC checking and replacement are disabled for these accept-all rules.
  Their minimum DLC is zero; replacement would discard nonempty payloads.
  Classic and FD frames retain their received DLC and valid payload bytes.
- `rzv_icu_attach()` allocates CPU IRQ routes. The legacy `RZV_ELC_CANFD_*`
  aliases supplied to it are IRQSEL source IDs: global error 366, global RX
  367, channel n TX `368+n` and error `354+n`, for n=0..5.
- Shared RX/global-error routes persist across sibling close. Per-channel
  TX/error and owned FIFO interrupts are masked during cancellation. Old
  mailbox results and the actual per-route GIC pending request are cleared
  before a new request/reopen.
- `CONFIG_RZV_CANFD_IRQ_PRIORITY` applies to every attached CAN route before
  it is enabled. Its range is 0..15, default 12; lower values have higher
  priority. CAN-FD selects the CR8 architecture's IRQ-priority facility.
- Internal loopback services completion synchronously and provides no
  normal-mode TX IRQ proof. External success requires the real TX ISR.
- No DMA path exists.

## Clock and frame timing

Constants assume an 80 MHz CANFDCLK:

| Phase | Bitrate | BRP | TSEG1 | TSEG2 | SJW |
|-------|---------|-----|-------|-------|-----|
| Nominal | 400 kbit/s | 2 | 74 | 25 | 25 |
| FD data with BRS | 3.2 Mbit/s | 1 | 16 | 8 | 8 |

Bitrate is `CANFDCLK / (BRP * (1 + TSEG1 + TSEG2))`; register fields hold
value minus one. There is no runtime bitrate ioctl. A passing pair on one
controller clock cannot independently qualify absolute bitrate: use an
independent analyzer or scope for that measurement.

## Connected command and completion contract

After an approved load of the retained `canfd-ext` ELF on CR8-0, use its
SEGGER RTT NSH console:

```text
nsh> rzv_canfd -n 32 -t 1000
```

Defaults are 32 rounds and 1000 ms per frame. `-n` accepts 1..256 and `-t`
accepts 1..5000; signs, trailing characters, zero and overflow are rejected.
Both separated (`-n 32`) and attached (`-n32`) arguments work. Both devices
open `O_RDWR|O_NONBLOCK` before the first transfer, with exactly one client
and no competing writer.

Each round sends 41 cases in each direction: Classic lengths 0..8 plus
FD lengths 0..8, 12, 16, 20, 24, 32, 48, 64 with BRS off and on. The default
is **2624 frames**. Distinct extended IDs encode round, direction and case;
a deterministic payload also depends on the predicted TX sequence. Zero
length checks the header and byte count. Raw DLC and mapped byte length are
checked separately; payload comparison covers only valid bytes.

One frame is outstanding at a time. Every passing line records its TX
sequence, matching IRQ-completed sequence and semantically equal peer RX.
Peer RX with a missing TX IRQ times out and fails. Absolute monotonic
per-frame deadlines survive interrupted waits. Repeated transfers wrap the
one-entry software ring and exceed eight RX slots in aggregate; this is
not a burst, saturation or throughput qualification.

The public v1 ABI contains `CANIOC_RZV_LOOPBACK` (existing scalar command),
`CANIOC_RZV_GET_TX_STATUS` and `CANIOC_RZV_CANCEL_TX`. Status is an atomic
snapshot without servicing completion. Sequence IDs are monotonic across
close/open, zero is invalid and exhaustion requires a fresh boot.

On failure the app cancels an active sequence with at most `min(t,1000)` ms
of cleanup before close. The lower half asserts standby, masks its owned
routes and requests abort/reset. It retires the upper-half entry exactly
once as failed. Reset timeout also drains software while keeping the port
physically quarantined; it never reports TX success. This prevents generic
CAN close from waiting forever on the queued entry. Cancellation requires
the single usable TX slot and an owned standby callback; larger legacy
queues return `ENOTSUP` without mutation. The port stays isolated until
close/reopen. A successful reopen can run again in the same boot; a still
faulted controller instead fails open within its reset bound.

If an internal-loopback timeout cannot recover the channel, the driver
masks its owned IRQs/FIFO, keeps onboard standby asserted and records a
terminal isolated fault. It retires queued frames as failures without
submitting them to the stalled hardware, so generic close can finish even
with a larger legacy queue or a callback-free expansion channel. Internal
test mode supplies isolation for unmanaged expansion channels; this does
not add normal-bus cancellation support. Further mode changes are rejected
until close and a successful fresh open recover the channel.

## Validation and evidence

Host contracts and clean builds establish software readiness; see the
[connected-test software receipt](../evidence/canfd-connected-software-validation-261022.md)
and [six-channel extension receipt](../evidence/canfd-six-channel-software-validation-261022.md).
Those checkpoints precede the subsequent semantic audit fixes; use the
[current audit-repair receipt](../evidence/canfd-audit-fixes-software-validation-261022.md)
for payload filtering, failed-loopback recovery, IRQ priority and current ELFs.
The [2026-10-22 target campaign](../evidence/canfd-disconnected-target-validation-261022.md)
adds 28 verified Classic frames across HW0 and HW3, mode/timing/FIFO/IRQ-priority
register checks and repeated disconnected-bus cancellation/close/reopen. HW3
payload tests use a separately archived dual profile whose only config change
is `CONFIG_EXAMPLES_CAN_DEVPATH="/dev/can1"`; the generic command has no runtime
device selector. The original SCI4 dual image disables NSH memory commands,
so its register checks use GDB. Its generic sample prints received bytes;
the retained verifier compares them with the source-defined expected payload.

The missing-ACK command returns exit 1 after its first Classic length-zero
case, and HW0 error IRQ delivery is observed. Successful normal-mode TX/RX
IRQs, FD/BRS payloads and connected traffic remain pending. FDCFG reads zero
on both channels, so TDC is disabled; FSP TDC settings parity remains open.
The older 2026-08-09 HW0 four-frame run remains historical evidence.

A separately authorized physical run must retain the exact ELF/config/hash,
board revision, measured standby levels and wiring, and full RTT transcript:

1. Run the default full matrix on the healthy interconnect; require both
   directions, all lengths/BRS modes and zero mismatches/timeouts.
2. Remove the CANH/CANL interconnect before invoking a missing-ACK test.
   Require bounded nonzero failure, cancellation, terminal isolated status
   and completed close. Changing wiring and loading/resetting need approval.
3. Restore the interconnect and run the full matrix again without reboot.
   Require successful reopen and all cases passing. Missing-TX-IRQ injection
   is host-tested; target injection needs a separately approved mechanism.

Follow the [deployment guide](../../deployment-guide.md) and repository
J-Link/RTT workflow. Stop after a probe reset/connect failure, without retry.
A complete named transcript may extend the bounded-on-target evidence;
it does not establish production readiness or independently measured timing.

Use the core-matched EVK FSP `refs/rzv2h_evk/can_fd/can_fd_rzv2h_evk_<core>_ep/`
for IP registers/clocks/interrupts, not board pins. See
[reference sources](../reference-source-map.md), [pinmap](../pinmap.md) and
[validation checklist](../validation/validation-checklist.md).
