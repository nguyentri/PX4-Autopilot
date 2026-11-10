# Dual RTT on one J-Link through the AXI-AP (board gate, 2026-11-10)

Result: **pass**. One J-Link session served both CR8 RTT consoles live at the same time, with input routed to the right core and neither core halted. This was a bounded on-target check of a prototype, not a shipped tool.

## Setup

- Board: local RDK-RZ/V2H, J-Link S/N 52000195, J-Link software V8.94.
- Images: `build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf` (CR8-0) and `build/renesas_rdk-rzv2h-io-cr8_1_demo/renesas_rdk-rzv2h-io-cr8_1_demo.elf` (CR8-1), RAM-loaded by `rzv2h-ipc-demo-load-both-auto.sh` (both VERIFY PASS: CR8-0 PC `0x408f7d80`, CR8-1 PC `0x4180b140`).
- RTT control blocks: `_SEGGER_RTT` at `0x081a2400` (CR8-0) and `0x081e2400` (CR8-1). Both sit in MPU region 3, which is non-cacheable SRAM (`rzv_mpu_regions.c:139`, `:229`).
- Prototype: `plans/261110-0642-vscode-dual-cr8-build-load-trace-ux/reports/dual-rtt-axi-ap-gate-prototype.py`, which calls `libjlinkarm.so` through `ctypes`.

## Method

1. `JLINKARM_CORESIGHT_Configure("")` sets up raw DAP access. No core connect is made, so there is no stop-mode halt and no connect sequence.
2. Check that DP `CTRL/STAT` shows debug and system power up (`0xf0000040`).
3. DP `SELECT = 0x01000000` (AP1, the AXI-AP); `CSW = 0x10806052` (the AP's original protection bits, 32-bit access, single auto-increment).
4. Per core: parse up buffer 0 and down buffer 0. Read `RdOff..WrOff`, then write `RdOff`. Write input at `WrOff`, then advance `WrOff`. Poll every 50 ms.

## Results

| Check | Result |
|-------|--------|
| Control block id and descriptors, both cores | `SEGGER RTT`, 3 up / 3 down; up0 8 KiB, down0 1 KiB on each core |
| Input isolation | `echo gate_cr8_1` and `echo gate_cr8_1_again` ran on CR8-1 only; `echo gate_cr8_0` ran on CR8-0 only |
| Shell on both cores | `ps` answered on each core from its own console |
| Cores not disturbed | three `rzv2h_heartbeat status` reads on each core over 30 s: peer `alive`, `age_ms` 11–108, `degraded 0`; timeout counters unchanged (CR8-0 3, CR8-1 1) |
| Probe health | DP `CTRL/STAT = 0xf0000040` before and after; no reset or clock-start markers; no J-Link processes left |
| Poll rate | 16.6–17.2 cycles/s with a 50 ms sleep; draining a 4.4 KB backlog took 0.54 s (about 8 KB/s) |

## Failures found on the way (and what the product must do)

- **CSW protection bits:** `CSW = 0x12` (protection bits cleared) read only zeros, and `0x30806052` or `0x70806052` failed outright. Keep `0x10806052`.
- **1 KiB auto-increment wrap:** reads that crossed a 1 KiB address boundary returned stale data from the start of that block. ADIv5 only guarantees TAR auto-increment within 1 KiB, so TAR must be reprogrammed at every 1 KiB boundary.
- **Other paths that don't work:** the J-Link "AHB-AP (AP2)" memory zone gave "Could not read memory". The default path through a CR8-0 connect halts CR8-0 for each access (stop mode) and cannot read CR8-1's block. Two JLinkExe RTT sessions misroute input (2026-11-09).
- **No memory commands after a failed connect:** with CR8-1 not started (DBGEN not asserted), a JLinkExe `mem8` issued after the failed `connect` made JLinkExe reconnect on its own and try to start the CR8 clocks. Run JLinkExe with `-ExitOnError 1`, or use raw DAP access with no core connect.

## 10-minute soak and burst check (2026-11-10, 10:04–10:15)

Result: **transport pass, burst loss confirmed**. Script: `plans/261110-0642-vscode-dual-cr8-build-load-trace-ux/reports/dual-rtt-soak.py` (same raw-DAP path; 10 ms poll while data flows, 50 ms idle).

**Images under test changed.** Another agent session on the same board reloaded both cores at about 10:03 for tick-calibration work. That was after the demo images above were loaded and before the soak started. The soak therefore ran on images that lack `rzv2h_heartbeat` (`command not found` on both cores), and the CR8-0 image prints NuttX `clkinfo` lines (`SCI6/SCI9 clocks enabled/disabled`, `rzv_clock.c:1271`) several times a second. The control blocks were at the same addresses (`0x081a2400`, `0x081e2400`). The heartbeat checks in this run are void. The transport and burst results stand.

| Check | Result |
|-------|--------|
| Duration / probe health | 600.1 s; DP `CTRL/STAT = 0xf0000040` before and after; no DAP error; no J-Link process left |
| Throughput | 53 487 B from CR8-0 (2 055 lines) and 6 606 B from CR8-1; 4 464 poll cycles (7.4/s). The longest single cycle took 10.1 s, during a CR8-0 burst |
| Burst A (120 s): `param show` on CR8-0, `ls -lR /proc` on CR8-1, then echo markers | both markers arrived (`MARK_A0`, `MARK_A1`) |
| Burst B (300 s): each burst command sent twice back to back, then markers | `MARK_B1` arrived; **`MARK_B0` never arrived** |
| Up-buffer fill | CR8-0 reached 8191/8192 (full) on 3 samples; CR8-1 peaked at 2028 |
| Input after the soak | `echo CHK0` / `echo CHK1` answered on the right core only |
| Per-poll latency after the soak | 0.32–1.24 s per poll for 0–369 B, against about 9 ms per cycle in the morning gate. Not explained: the board was shared, so re-measure on a quiet board |

Conclusions for the product:
- Up buffer 0 uses no-block trim mode, so a burst bigger than what one poll can drain loses output silently, as `MARK_B0` showed. The bridge must count the cycles where it sees a full buffer and show "output dropped" in the pane. A filled buffer is evidence of a gap, not proof.
- Reading one AP word at a time limits throughput. Before relying on dual mode for PX4 boot logs, check whether the V8.94 DLL offers a batched AP transfer. Otherwise make the CR8-0 up buffer larger in RTT images, or keep `switch` mode, which uses the JLinkExe RTT engine, for those images.
- Probe ownership must also cover other host sessions, not just this extension. The board was reloaded under a running test without any lock conflict.

## Quiet-board soak on the demo images (2026-11-10, 10:33–10:43)

Result: **transport and heartbeat pass, burst loss repeats**. Same script and schedule as the first soak. Both demo images were reloaded at 10:32:56 by `rzv2h-ipc-demo-load-both-auto.sh` (VERIFY PASS, CR8-0 PC `0x40848360`, CR8-1 PC `0x4180b140`), and no other session used the probe during the run.

| Check | Result |
|-------|--------|
| Boot backlog | CR8-0 3 901 B (the whole PX4 boot), CR8-1 291 B; both fit in the 8 KiB up buffer |
| Heartbeat, 10 reads per core | peer `alive` every time, `age_ms` 7–95, `degraded 0`; timeout counters unchanged (CR8-0 2, CR8-1 0) |
| Poll rate | 9 619 cycles in 600 s (16.0/s); longest gap 1.9 s. The 0.3–1.2 s per-poll latency of the first soak did not recur, so it came from the shared probe |
| Burst A (120 s) | `MARK_A0` and `MARK_A1` both arrived |
| Burst B (300 s, doubled commands) | `MARK_B1` arrived; **`MARK_B0` was lost again**; CR8-0 up buffer at 8191/8192 on 2 samples |
| Totals | CR8-0 30 648 B, CR8-1 10 207 B (peak fill 1 538 B) |
| Probe health | DP `CTRL/STAT = 0xf0000040` before and after; no J-Link process left |

Follow-up research (`plans/reports/researcher-261110-1044-jlink-batched-ap-reads-and-cr8-0-boot-log-fallback.md`): the V8.94 DLL has no batched AP read, and raw AXI-AP word reads measured 1.3–4.0 ms per word that afternoon, against about 5.5 KB/s for the JLinkExe RTT engine. The chosen fix is a 32 KiB CR8-0 up buffer; the board check is below. The afternoon rate drop is explained below as host CPU load.

## Raw-read slowdown: host CPU load (2026-11-10, afternoon)

The afternoon drop from about 0.6 ms to 1.3–4.0 ms per raw AXI-AP word came from host CPU load, not from the probe or the board. Measured with the same word-read loop on the same board:

| Host state | ms per word |
|------------|-------------|
| Idle | 0.59–0.70 |
| 8-job PX4 build at normal priority | 6–19 |
| Same build at `nice -n 19` | 0.7–2.6 |

The product therefore starts builds at `nice -n 19` while a dual bridge runs. Board soaks were run with no build on the host.

## 32 KiB CR8-0 up buffer and firmware drop counter (2026-11-10, 12:20–12:45)

Changes under test (uncommitted at the time): `CONFIG_SEGGER_RTT_BUFFER_SIZE_UP=32768` in the seven CR8-0 RTT defconfigs, and a NuttX change in `drivers/segger/syslog_rtt.c` that adds `g_syslog_rtt_dropped`, a count of the bytes the no-block up buffer could not take. The counter lives in the RTT section, which is not zeroed at boot, so a host reports the change since attach. Demo images rebuilt and RAM-loaded with both VERIFY PASS (CR8-0 PC `0x408e6c3c`, CR8-1 PC `0x4180b140`). From the ELF: `_SEGGER_RTT` at `0x081a8404`, `_acUpBuffer` at `0x081a0404` (32 768 B), `g_syslog_rtt_dropped` at `0x081a0000`; CR8-1 keeps its 8 KiB up buffer and its control block at `0x081e2400`.

| Run | Burst A (1× `param show`) | Burst B (2× `param show`) | Burst C (3× `param show`) | Notes |
|-----|---------------------------|---------------------------|---------------------------|-------|
| Soak3, 480 s, 32 KiB, no counter | `MARK_A0`, `MARK_A1` arrived | `MARK_B1` arrived, **`MARK_B0` lost** | **`MARK_C0` lost** | 6 377 polls (13.3/s); boot backlog CR8-0 4 887 B |
| Soak4, 420 s, 32 KiB + counter | both markers arrived, counter 0 | `MARK_B1` arrived, `MARK_B0` lost, **counter +10 447 B** | `MARK_C0` arrived after **counter +22 729 B** | 4 687 polls (11.2/s); longest cycle 10.2 s (one full 32 KiB drain, about 3.2 KB/s); boot backlog CR8-0 3 852 B, CR8-1 291 B |

Soak4 detail:
- Heartbeat at 5, 65, 128, 185, 245, 305 and 367 s: peer `alive` on both cores, `age_ms` 3–148, `degraded 0`; timeout counters unchanged (CR8-0 3, CR8-1 0).
- Totals: CR8-0 142 296 B (3 991 lines), CR8-1 8 511 B (peak fill 2 103 B of 8 KiB). Dropped since attach: 33 176 B, all on CR8-0.
- The host-sampled fill check saw a full CR8-0 buffer on only 1 sample while the firmware counted 33 KB lost, so host sampling cannot stand in for the counter.
- Probe health: DP `CTRL/STAT = 0xf0000040` before and after; no J-Link process left.
- Probe not exclusive for the whole run: at 12:42:05–12:42:10 (soak t ≈ 255–260 s, between the 245 s heartbeat and burst B) a process outside this session wrote two `jlink-gdb-oneshot` logs, one ending in "Core internal signal DBGEN is not asserted". No reset followed (both cores' uptime kept counting) and both cores answered at 305 s. Bursts B and C ran after that access ended.

Conclusions for the product:
- 32 KiB holds the whole boot log and one complete `param show` (about 43 KB arrives complete because the host drains while PX4 prints). Back-to-back repeats exceed what the raw-read drain can keep up with, and trim mode drops them.
- The firmware counter detects every loss with its size. The dual bridge reads `g_syslog_rtt_dropped` once per poll and shows "output dropped: N B"; a full-buffer heuristic is not needed.
- Remaining limit: the drain rate (about 3 KB/s on raw word reads). A faster drain needs batched transfers, which V8.94 does not offer, so `switch` mode stays the fallback for long dumps.

## `dualcr8` boot log on the 32 KiB buffer (2026-11-10, 12:52–12:55)

`renesas_rdk-rzv2h_dualcr8` was rebuilt at `nice -n 19` with the 32 KiB buffer and the counter (`_SEGGER_RTT` `0x081a8404`, `g_syslog_rtt_dropped` `0x081a0000`; `test/rzv2h-dualcr8-artifact-contract-test.py` OK). It was RAM-loaded with `renesas_rdk-rzv2h-io-cr8_1_pwm` (VERIFY PASS, CR8-0 PC `0x408fccb4`, CR8-1 PC `0x4180b2fc`) and read for 30 s with the dual raw-DAP reader.

| Check | Result |
|-------|--------|
| CR8-0 boot backlog | 12 900 B, starting at the `NUTTX` banner; the image keeps printing clock and reset trace lines (`Clock enabled: domain=…`, `SCI9 clocks disabled`) afterwards |
| CR8-1 boot backlog | 449 B, ending at `nsh>` |
| Drop counter | 0 at attach and 0 after 30 s. It also read 0 after this reload although the previous demo image had reached 33 176, so a fresh load starts it at 0 here; the bridge still uses the change since attach |
| Polls | 404 in 30 s (13.4/s); DP `CTRL/STAT = 0xf0000040` before and after |

The demo images were then reloaded (VERIFY PASS, CR8-0 PC `0x40910d14`, CR8-1 PC `0x4180b140`), and no J-Link process was left.
