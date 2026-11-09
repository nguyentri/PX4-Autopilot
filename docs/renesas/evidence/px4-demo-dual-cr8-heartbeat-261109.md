# PX4 demo dual-CR8 heartbeat — on-target evidence (2026-11-09)

This is **PX4** evidence. Both cores ran the PX4 `demo` images below. It is
separate from the earlier NuttX sample transcripts (`sci5-nsh-*`,
`rtt-hil-demo-*`), and neither set may stand in for the other.

| Item | Value |
|------|-------|
| Board | Local RDK-RZ/V2H, one J-Link (serial redacted), FT232R on SCI5 |
| Tree | `main` @ `34c9ff17797` plus the uncommitted heartbeat change set |
| CR8-0 | `build/renesas_rdk-rzv2h_demo/renesas_rdk-rzv2h_demo.elf`, built 2026-11-09 21:35:11, sha256 `21ae1dc77adb2be1…` |
| CR8-1 | `build/renesas_rdk-rzv2h-io-cr8_1_demo/renesas_rdk-rzv2h-io-cr8_1_demo.elf`, built 21:35, sha256 `90c8711edc1f0979…` |
| CR8-0 console | MAVLink shell over SCI5 (`/dev/ttyUSB0` @57600, `rzv2h-mavlink-shell-exec.py`) |
| CR8-1 console | NSH over RTT (`nuttx-rtt-bridge.sh start cr8_1`, `_SEGGER_RTT=0x081e2400`) |
| CM33 | Not connected |

## 1. Paired check: `rzv2h-px4-demo-heartbeat-check.sh` (exit 0)

Run 3 used `--load` and RAM-loaded both cores; run 5 ran on those resident
images and passed:

```
  PASS  CR8-0 demo image, MAVLink on /dev/ttyS5
  PASS  CR8-0 initiator sees CR8-1 alive (age < 500 ms), tx/rx rising
  PASS  CR8-1 responder sees CR8-0 alive (age < 500 ms), tx/rx rising, free answers
  PASS  CR8-1 held: CR8-0 reports peer lost (age -1 ms) at +10 s of 15 s, MAVLink answers
  PASS  CR8-1 resumed: CR8-0 reports peer alive again
  PASS  no data abort / stack overflow / assert / PANIC on either console
== PASS: PX4 demo CR8-0 <-> CR8-1 heartbeat proven, including loss and recovery ==
```

CR8-0 identity (`ver all`): `HW arch: RENESAS_RDK_RZV2H`, `Build variant: demo`,
build datetime `Nov  9 2026 21:35:11`; `mavlink status` reports
`transport protocol: serial (/dev/ttyS5 @57600)`.

CR8-0 status, two samples about 4 s apart (MAVLink shell):

```
INFO  [rzv2h_heartbeat] role: initiator (source 0, peer 1)
INFO  [rzv2h_heartbeat] link: online epoch 0x00000020 sessions 8
INFO  [rzv2h_heartbeat] peer: alive age_ms 82 seq 2398 uptime_ms 301479 loops 22745 state 1
INFO  [rzv2h_heartbeat] tx: sent 2615 failed 7 seq 2399
INFO  [rzv2h_heartbeat] rx: valid 2615 ignored 0 stale 0 restarts 0
---
INFO  [rzv2h_heartbeat] peer: alive age_ms 56 seq 2436 uptime_ms 305511 loops 23072 state 1
INFO  [rzv2h_heartbeat] tx: sent 2653 failed 7 seq 2436
INFO  [rzv2h_heartbeat] rx: valid 2653 ignored 0 stale 0 restarts 0
```

CR8-1 status (RTT NSH):

```
INFO  [rzv2h_heartbeat] role: responder (source 1, peer 0)
INFO  [rzv2h_heartbeat] link: online epoch 0x00000022 sessions 14
INFO  [rzv2h_heartbeat] peer: alive age_ms 92 seq 46 uptime_ms 315953 loops 25396 state 1
INFO  [rzv2h_heartbeat] tx: sent 2699 failed 4 seq 46
INFO  [rzv2h_heartbeat] rx: valid 2703 ignored 0 stale 0 restarts 0
INFO  [rzv2h_heartbeat] raw: tx 2698 rx 2703 timeouts 3 stale_acks 1 bad_hdr 9 bad_entry 0 recoveries 14 ready 1 degraded 0
```

During the hold, `rzv2h-core-halt-resume.sh cr8_1 hold 15` held CR8-1
halted inside one JLinkExe session (`PC: (R15) = 4180B140`) with no reset. At
+10 s CR8-0 reported:

```
INFO  [rzv2h_heartbeat] link: offline epoch 0x00000000 sessions 10
INFO  [rzv2h_heartbeat] peer: lost age_ms -1 seq 0 uptime_ms 0 loops 0 state 0
INFO  [rzv2h_heartbeat] raw: tx 2707 rx 2706 timeouts 10 ... ready 0 degraded 1
```

After the hold ended, CR8-0 recovered on its own with no reload:

```
INFO  [rzv2h_heartbeat] link: online epoch 0x00000035 sessions 11
INFO  [rzv2h_heartbeat] peer: alive age_ms 39 seq 21 uptime_ms 332566 loops 23683 state 1
```

## 2. Standalone CR8-0 (CR8-1 out of the link)

1. Over RTT, `rzv2h_heartbeat stop` on CR8-1; the following `status` printed `not running`.
2. `rzv2h-load-one-core.sh cr8_0 <demo elf>`: `VERIFY PASS (running at PC=0x4091c1e4)`.
3. CR8-0 MAVLink shell 15 s later:

```
HW arch: RENESAS_RDK_RZV2H
INFO  [rzv2h_heartbeat] link: offline epoch 0x00000000 sessions 0
INFO  [rzv2h_heartbeat] peer: lost age_ms -1 seq 0 uptime_ms 0 loops 0 state 0
INFO  [rzv2h_heartbeat] tx: sent 0 failed 0 seq 0
INFO  [commander] Preflight check: FAILED
	transport protocol: serial (/dev/ttyS5 @57600)
```

The `commander check` result is the same as the pre-heartbeat baseline
(`plans/261109-1931-px4-demo-dual-cr8-heartbeat/reports/board-check-261109-cr8_0-demo-mavlink-shell-sci5.txt`).
The module publishes no uORB topic, so it cannot change arming.

4. Re-pair: `rzv2h-load-one-core.sh cr8_1 <demo elf>` (`VERIFY PASS`). Eight
   seconds later CR8-0 reported `peer: alive age_ms 53 seq 97`.

## 3. Board findings from this run

- A CR8 core halted by JLinkExe runs again as soon as JLinkExe disconnects. A
  loss test must keep the halt inside one JLinkExe session
  (`connect, halt, sleep, go`); `rzv2h-core-halt-resume.sh` now has only that
  `hold` mode.
- Run 2 (about 21:41) failed during the load.
  - CR8-0 loaded normally. Then the CR8-1 connect read `Target voltage: 1.80 V`,
    followed by `Measured: 0.0 Volt`.
  - The CR8-0 verify that followed found CR8-0 at its reset vector
    (`PC = 0x00000000`), so CR8-0 was really reset, not just misread.
  - The host kernel logged no USB disconnect for the J-Link or the FT232R
    after the 19:52 attach. The earlier "FT232R re-enumerated" note was wrong:
    it came from the `/dev/ttyUSB0` timestamp, which changes on every serial
    write.
  - Cause not proven: a dip in target power, or a reset during the CR8-1
    connect. It happened once in seven runs.
  - VTref was back at 1.79-1.80 V for every later run.
- On the 57600 link, `mavlink status` shows 68-75 % rx loss. pymavlink's
  message cache can raise `TypeError` on garbled frames; the shell helper now
  skips that error.

## 3a. Rerun after a board reconnect (run 6, exit 0)

The board was unplugged and reconnected at 21:50, which lost the RAM images.
`--load` then reloaded both cores and all six checks passed again (loss seen
at +6 s of the 15 s hold). About 20 s after the loads, CR8-0 already showed
`sessions 7`, `timeouts 1` and `bad_hdr 5`, and CR8-1 showed `sessions 3`,
`timeouts 2` and `bad_hdr 0`. Most of the session churn therefore comes from
startup: load ordering plus the verify and bridge halts. It is not steady-state
loss.

## 3b. Run 7 after another session's image (exit 0)

At 22:15 CR8-0 ran a different image: RAM at `0x4080fc38` held
`wfi; nop; bx lr`, not the demo ELF's code, and SCI5 sent no MAVLink. No
kernel USB event was logged, so the image changed by a load, not a board
reconnect. Once the board was free, `--load` at 22:21 reloaded both cores and
all six checks passed again (loss seen at +9 s of the 15 s hold).

## 3c. Steady-state soak after run 7 (no probe activity)

CR8-0 status over the MAVLink shell, 5 min 47 s apart. No J-Link process ran
between the two samples:

```
22:22:29  link: online epoch 0x00000043 sessions 6
          tx: sent 343 failed 5 seq 136
          raw: tx 343 rx 343 timeouts 5 stale_acks 0 bad_hdr 0 bad_entry 0 recoveries 6 ready 1 degraded 0
22:28:16  link: online epoch 0x00000043 sessions 6
          peer: alive age_ms 8 seq 3362 uptime_ms 402020 loops 31005 state 1
          tx: sent 3569 failed 5 seq 3362
          rx: valid 3569 ignored 0 stale 0 restarts 0
          raw: tx 3569 rx 3569 timeouts 5 stale_acks 0 bad_hdr 0 bad_entry 0 recoveries 6 ready 1 degraded 0
```

There were 3226 exchanges at about 9.3 per second. In the same window,
sessions, epoch, timeouts, recoveries and failed sends stayed the same, and
bad_hdr stayed at 0. Every session and timeout came from the loads, verify
halts and the hold, none from steady-state operation.

## 4. Open items

- Session churn at steady state: closed by section 3c. Every halt or GDB
  attach still legitimately costs one session.
- CR8-1 `bad_hdr`: 9 after run 5, 0 after run 6. CR8-1 was not sampled
  during the run 7 soak. Probably frames caught mid-recovery; not diagnosed.
- Soak length: about 6 minutes. A multi-hour soak has not been run.
