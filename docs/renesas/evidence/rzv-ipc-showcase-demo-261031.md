# ipcdemo CR8-0 ↔ CR8-1 showcase board run, 2026-10-31

The `ipcdemo` customer showcase passed every acceptance check on the local
RDK-RZ/V2H. These are the CR8-0 `ipcc-demo-cr8_0-sci4` and CR8-1
`ipcc-demo-cr8_1` images, using `/dev/ipcc1` over the raw IPCC link.

- Heartbeats ran in both directions for more than five minutes; none were
  missed.
- One-way and concurrent pings both completed with 0 timeouts:
  - 300/300 one-way from CR8-0;
  - three rounds of 100 in each direction at the same time.
- `say` messages were delivered both ways.
- After CR8-1 was reloaded on its own, the link came back without any console
  command.
- The raw `ipcc-raw-cr8_0` + `ipcc-raw-cr8_1` pair passed the HIL autotest.

The [board transcript](rzv-ipc-showcase-demo-261031.txt) holds the console
lines. Sections A0 to H below refer to it.

## Scope and images

| Image | defconfig | sha256 |
|---|---|---|
| `nuttx-ipcc-demo-cr8_0-sci4.elf` (CR8-0) | `ipcc-demo-cr8_0-sci4` | `0d78b67f96a91029b1cc2f52553589f100626ea4e76b5291661d907e88f60d77` |
| `nuttx-ipcc-demo-cr8_1.elf` (CR8-1, `_SEGGER_RTT` 0x081e0000) | `ipcc-demo-cr8_1` | `f79e72a6dda7e990d2109928fca8b8f6d9a67526a9510d8bbc812c174ce6e4ac` |
| `nuttx-ipcc-raw-cr8_0.elf` (CR8-0) | `ipcc-raw-cr8_0` | `95a1eb4458dfe015c41ec92f4801874bbdd1078eea5786dffdf195b725586027` |
| `nuttx-ipcc-raw-cr8_1.elf` (CR8-1) | `ipcc-raw-cr8_1` | `39c0d493ec003d83ee6e5fd6938154ea8c3301dc2ee7857059b1b9af413719bd` |

- The demo images come from nuttx `40015473ec`.
- The raw pair was built from a working tree that also carried uncommitted
  `CONFIG_INIT_STACKSIZE=4096` edits in the `ipcc-raw-*` defconfigs.
- Consoles:
  - CR8-0 NSH on SCI4 at 115200;
  - CR8-1 NSH on J-Link RTT through `nuttx-rtt-bridge.sh`, probe `<probe-sn>`.
- Images were loaded into RAM with the guarded loaders
  (`rzv2h-load-one-core.sh`, `rzv2h-ipc-demo-load-both-auto.sh`).
- The CM33 was never attached.
- Board actions ran under the AGENTS.md standing board authorization.

## Root causes found and fixed on target

1. **CR8-1 RTT output blocked the IPC reader (section A0).**
   - The demo used the default SEGGER RTT BLOCK up-buffer mode. When the buffer
     is full and no host drains it, an RTT write spins with IRQs masked.
   - So whenever CR8-1 logged, its `ipcdemo` reader stopped taking frames.
     About 100 ms after each CR8-1 heartbeat, CR8-0's TX-ACK wait timed out and
     the link dropped. That gave 38 link-down events in 2.5 min.
   - When the host connected, CR8-1 printed the whole backlog at once.
   - Fix: `CONFIG_SEGGER_RTT_UP_MODE_TRIM=y` in `ipcc-demo-cr8_1`
     (nuttx `6dea500353`).
2. **J-Link stop-mode RTT halts outlasted the 100 ms TX-ACK timeout
   (section A).**
   - On Cortex-R8, J-Link reads RTT in stop mode, which halts CR8-1 for each
     read. With the bridge attached, some halts lasted more than 100 ms.
   - The TRIM build still lost 4 of 300 pings, and each loss caused a link
     drop and recovery (epochs 151–154).
   - Fix: `CONFIG_RZV_IPC_TX_TIMEOUT_MS=400` in both demo defconfigs
     (nuttx `40015473ec`).
   - With the fix, round trips peaked at 241 ms and nothing was lost
     (section E).
3. **The guarded loader could not write over a foreign image's MPU map.**
   - After the CR8-1 image had run on CR8-0, the resident SCTLR/MPU blocked the
     debugger's writes to the CR8-0 SDRAM window. `__start` then prefetch-aborted
     over and over.
   - Fix: `rzv2h-ipc-hil-loadstart.gdb` now writes the Cortex-R8 reset SCTLR
     (0x00C50078) before `load` (PX4 `235a972018e`).

No IPC driver source change was needed: the link, epoch recovery and ACK path
behaved as designed.

## Results (fixed build)

| Check | Result | Transcript |
|---|---|---|
| Boot, link up without commands | epoch 157 on both cores; CR8-1 reports `TX timeout 400 ms` | D |
| One-way ping, bridge attached | 300/300, rtt max 167 ms | E |
| Concurrent ping, both directions, bridge attached | 3 × (100/100 + 100/100), CR8-0 rtt max 241 ms, CR8-1 max 9 ms | E |
| Heartbeat soak 23:30:50–23:36:11 | CR8-0 63 acked, CR8-1 51 acked, 0 missed, no other lines | F |
| Ping with no RTT host | 3 × 100/100, rtt max 1 ms | G |
| `say` both ways | delivered, rtt 3 ms / 0 ms | C |
| CR8-1-only reload | CR8-0 relinks (epoch 144) and reports `peer back` with no command | B |
| Raw pair autotest | 7/7 PASS, no abort/overflow/assert | H |

- Sections B and C ran on the TRIM build that still had the 100 ms timeout.
  Their results don't depend on the timeout.
- While the bridge is attached, CR8-1 heartbeats arrive about every 6.3 s
  instead of every 5 s. The cause is that CR8-1's tick pauses during the
  stop-mode halts.

## Limits

- This is bounded on-target evidence for the demo profile only:
  - the CM33 links, cold power cycles and PX4 images were not tested;
  - all timing comes from host-side console timestamps.
- The `ipcc-raw-*` configs still use the 100 ms TX timeout and BLOCK RTT.
  - Their auto-echo prints nothing per frame, so the stall stays latent there.
    The raw autotest still passed.
  - A manual `ipctest` run with the RTT bridge attached can still hit the
    stop-mode timeout.
