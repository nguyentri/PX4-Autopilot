# RTT sample, HIL and PX4 demo run on RDK CR8-0 (2026-11-09)

Board: local RDK-RZ/V2H, probe `<probe-sn>`, CR8-0 loads (CR8-1 for the IPC pair).
The CM33 was never connected. All images were RAM-loaded with the guarded
single-core or paired loaders under the AGENTS.md standing board grant. Raw
transcripts stay in the local, gitignored
`plans/261109-0823-rzv2h-rtt-hil-demo-hardware-run/` tree; the excerpts below
are copied from them.

## Outcome

- The guarded batch runner passed 87 of 90 native RTT sample profiles.
  - `bmp280` passed after its defconfig gained `CONFIG_SCHED_WAITPID`.
  - `ether1-board-rtt` cannot pass on the RDK: the board has no ether1 PHY.
  - `ether-mac-loopback-rtt` still fails with `-116` (ETIMEDOUT); see below.
- `canfd-dual` passed after the same WAITPID fix. Without it, NSH ran `can` in
  the background and the received frames interleaved with the next command.
- Three profiles the runner does not admit yet were run by hand over RTT. All
  three passed (see the next section).
- The PX4 `renesas_rdk-rzv2h_demo` image ran with the free-running HRT, and
  `reboot` reset the SoC.
- The CR8-0 ↔ CR8-1 IPC autotest passed all seven checks.

## Manual RTT runs

| Profile | ELF sha256 (prefix) | Result |
|---|---|---|
| `ads1115` | `78731a0c5af08f57` | Scan finds 0x48. `ads1115 -n 3`: 3 rounds, 0 errors, AIN0 ≈ +3295 mV, AIN1–3 ≈ 0 mV |
| `icm45686-dma-ssl-rtt` | `97321d508c1ed637` | `ICM45686 result=0 samples=5/5 bursts=1 empty=1 max_fifo=12`, EXIT=0 |
| `adc-rtt` | `e2624b8c9babdcae` | `adc -n 2`: 4 channels × 2 samples, EXIT=0 |

For `adc-rtt`, completing the conversions is the full check. The RDK brings out
no ADC analog pin, so the inputs float (2018–2171 counts) and their values carry
no meaning. This run covers the ADC start-trigger change: the reset value of
ADSTRGR now selects no trigger source for TRSA/TRSB.

## PX4 demo (`renesas_rdk-rzv2h_demo`)

ELF sha256 `b9f836ef00ecdcc84a4b0b2999c60cd5b6f2543811e6f7278732cc9186b6bf7f`;
`_SEGGER_RTT` at `0x081a2400`. `ver all` reported PX4 `de51948323` and NuttX
`cac03a185e`; the NuttX tree also held the uncommitted free-running `rzv_hrt.c`
that was committed after this run.

- ICM-45686: 0 bad register, 0 bad transfer, 0 FIFO overflow, 1 FIFO reset at
  start. `vehicle_angular_velocity` ran at 4925 Hz FIFO; accel at 666.7 Hz.
- `pwm_out` interval averaged 1459 µs (about 685 Hz); `bmp280` comms errors 0;
  `uorb top` listed 91 topics.
- The `Accel #0 fail: TIMEOUT` / `BARO #0 failed: TIMEOUT` errors and the
  `vehicle_imu` data gaps match the [bench baseline](../validation/demo-bench-validation.md).
  After 30 s with the RTT bridge stopped, the gap counters rose only around the
  two reconnects (13 to 27–31). The maximum intervals of 0.5–0.8 s are RTT
  stop-mode halts, not HRT faults.
- `reboot` (`board_reset` → `up_systemreset`): the console stopped. A
  read-only GDB connect then reported `DBGEN is not asserted` on CR8-0, so the
  SoC reset happened and the CR8 cores were left in reset by the boot firmware.
  The code did not hang inside `up_systemreset`.

The host test `test/rzv2h-hrt-free-running-runtime-test.py` passed 6/6.

## IPC autotest

`rzv2h-ipc-demo-autotest.sh` with the `ipcc-raw-cr8_0` (`d3ecd744134c6e65`) and
`ipcc-raw-cr8_1` (`11d8028e91b55c66`) sample images. Both were built after NuttX
`5ef165b5e6` (MHU doorbell/acknowledge block pairing), so this run covers the
new `/dev/ipcc1` block route:

```text
IPCTEST_RESULT core=CR8-0 mode=recover dev=/dev/ipcc1 status=pass
IPCTEST_RESULT core=CR8-0 mode=ping dev=/dev/ipcc1 status=pass pass=100 expected=100 timeouts=0
IPCTEST_RESULT core=CR8-1 mode=auto-echo dev=/dev/ipcc1 status=pass echoed=100 expected=100
== PASS: CR8-0 <-> CR8-1 IPC over /dev/ipcc1 proven on both cores ==
```

## Watchdog

The held-back WDT changes and the committed baseline fail identically. On
`wdt-nonstart-rtt`, `guard_hardware_stopped` fails; on `wdt0-board-rtt`,
identity returns -16. SYS_WDT0–3_CTRL (`0x10430C00`–`0x10430C0C`) read 0, so
BP_HALTED is clear and the profiles correctly refuse to run. This matches the
2026-10-22 observation and is accepted as a board precondition. The WDT driver
changes stay uncommitted until they have a hardware pass.

## Ethernet ether0 `-116`

The investigation stopped after three repair attempts, and the edits were
reverted:

- With descriptors in SRAM, the DMA raises a bus error.
- With descriptors moved to non-cached DDR, the bus error is gone (DMA_CH0
  status 0x500, MTL TXQ0 debug 0x00010012). The MAC still never transmits:
  MAC_DEBUG stays 0x00020000 at both 100M and 1000M, and RX descriptor 0 stays
  OWN (des3 0xc1000000).
- CPG: CLKON11 0x3FFF, CLKMON5 0xFFFFFFFF (ETH0 TX/RX/TX180/RX180 running),
  CSDIV0 0.

## Not rerun

`test/rzv2h-sdhi-wdt-instance-artifact-test.py` needs an archive that holds the
SDHI profiles; the archive from this run lacks them.

## Open

- Why the ether0 MAC TX path stalls after it fetches descriptors
  (MAC_DEBUG 0x00020000). The source comparison in
  [ether0 RGMII configuration gap](ether0-rgmii-interface-config-gap-261109.md)
  and its board readback narrow this to the TXC pad direction
  (`PFC_OEN.OEN0` = 1). No fix has been tried yet.
