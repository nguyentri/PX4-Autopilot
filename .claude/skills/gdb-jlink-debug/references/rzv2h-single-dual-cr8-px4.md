# RZ/V2H RDK: single-core and dual-CR8 sessions (PX4 + NuttX)

Board: Renesas RDK-RZ/V2H (R9A09G057H), one J-Link on SWD. CR8-0 is the
flight core. CR8-1 is the IO core in the dual profile. The CM33 is out of
scope: never connect to it (it resets the SoC). `D=platforms/nuttx/Debug`.

## Images, cores and RTT blocks

Run `$D/jlink-debug-preflight.py` for the live list. The values below were
true on 2026-10-13. Always re-read them from the ELF you load.

| ELF | Core / J-Link device | Entry | `_SEGGER_RTT` | Console |
|---|---|---|---|---|
| `build/renesas_rdk-rzv2h_{default,drone,simple,sih,dshot,dualcr8}/*.elf` | CR8-0 `R9A09G057H44_R8_0` | `0x40800000` | `0x081a2400` | NSH on RTT ch0 |
| `build/renesas_rdk-rzv2h-io-cr8_1_default/*.elf` | CR8-1 `R9A09G057H44_R8_1` | `0x41800000` | none | none (SCI1 is not wired); log in `g_sci1port.xmit` |
| `platforms/nuttx/NuttX/nuttx/nuttx-ipcc-raw-cr8_0.elf` | CR8-0 | `0x40800000` | `0x081a0000` | NSH on RTT |
| `platforms/nuttx/NuttX/nuttx/nuttx-ipcc-raw-cr8_0-sci4.elf` | CR8-0 | `0x40800000` | none | NSH on SCI4 `/dev/ttyUSB0` 115200 |
| `platforms/nuttx/NuttX/nuttx/nuttx-ipcc-raw-cr8_1.elf` | CR8-1 | `0x41800000` | `0x081e0000` | NSH on RTT |

The bridge aliases default to the NuttX addresses (`0x081A0000` /
`0x081E0000`). A PX4 CR8-0 image needs its ELF passed, otherwise the bridge
points RTT at the wrong block.

Images are RAM-loaded and do not survive a power cycle or a reset. "Which
image is running?" has no on-board answer. Use the last load log
(`$D/rzv2h-ipc/logs/load-CR8-*.log`) or ask the user.

## Single-core PX4 on CR8-0 (current priority)

```bash
export JLINK_SERIAL=$($D/jlink-debug-preflight.py --print-serial)
ELF=build/renesas_rdk-rzv2h_drone/renesas_rdk-rzv2h_drone.elf
$D/rzv2h-ipc/rzv2h-load-one-core.sh cr8_0 "$ELF"        # project standing authorization
$D/nuttx-rtt-bridge.sh start cr8_0 "$ELF"
$D/nsh_console_exec.py --marker 'ver all' 'ps' 'free' 'uorb top -1'
$D/nsh_console_exec.py --marker 'listener sensor_accel -n 1' 'commander status'
$D/nuttx-rtt-bridge.sh stop
$D/jlink-gdb-oneshot.py cr8_0 "$ELF" --attempts 1 -ex 'bt' -ex 'info registers pc cpsr'
```

The `simple` profile is the PWM + ICM20948 bench image
(`docs/renesas/validation/simple-pwm-icm20948-validation.md`).

## Dual CR8 (dualcr8 + io-cr8_1)

```bash
C0=build/renesas_rdk-rzv2h_dualcr8/renesas_rdk-rzv2h_dualcr8.elf
C1=build/renesas_rdk-rzv2h-io-cr8_1_default/renesas_rdk-rzv2h-io-cr8_1_default.elf
$D/rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh "$C0" "$C1"  # CR8-0 first, then CR8-1
$D/nuttx-rtt-bridge.sh start cr8_0 "$C0"
$D/nsh_console_exec.py --marker 'px4io_bridge status' 'commander status'
$D/nuttx-rtt-bridge.sh stop
$D/jlink-gdb-oneshot.py cr8_0 "$C0" --attempts 1 -x $D/rzv2h-ipc/rzv2h-px4-cr8_0-bridge-health.gdb
$D/jlink-gdb-oneshot.py cr8_1 "$C1" --attempts 1 -x $D/rzv2h-ipc/rzv2h-px4-cr8_1-io-health.gdb
```

- Load order is CR8-0, then CR8-1: the CR8-1 responder adopts the
  recovery epoch of the CR8-0 initiator. To replace only one image, use
  `rzv2h-load-one-core.sh`. After a CR8-0 reload, reload CR8-1 too.
- Commander blocks arming until CR8-1 reports a fresh lease and heartbeat.
- CR8-1's boot log: `-ex 'dump binary memory <scratch>/sci1.bin
  g_sci1port.xmit.buffer g_sci1port.xmit.buffer+g_sci1port.xmit.size'`, then
  `strings` the file. Keep it in the scratch dir; it is target data.
- To get rates, sample the health snippet twice a known time apart and diff
  the counters. Every sample halts that core for 1-3 s. On a CR8-0 sample
  that shows up afterwards in `px4io_bridge status` as a fault-flag blip
  (e.g. `0x804`, then `0x0`) and extra `faults=`/`recoveries=` counts on the
  link. These are probe artefacts, not firmware faults; the link recovers
  by itself.
- What the snippets print (board run 2026-10-13, dualcr8 + io-cr8_1):
  CR8-0: ring `tx_hdr->state` / `rx_hdr->state` (`0x1` = up), bridge
  `_stats`, `_link_down`, `_io_alive`. CR8-1: loop counters, the output lease
  state (`OutputLease::State::Safe` while disarmed), raw link stats and the
  `g_sci1port` log head/size. A snippet that does not match the ELF makes
  oneshot exit 6; `test/rzv2h-jlink-debug-tools-test.py` resolves both
  snippets against the built ELFs.

## RTT perturbs what you measure

J-Link reaches the CR8 RTT buffers only in stop mode. With the bridge
attached, CR8-0 was halted about 25 % of the time, which produced lease
blips and IPC link recoveries that do not happen without the probe. To
measure link or lease behavior, detach first and let the board run alone:

1. Through the bridge, write a script on the target. Use double quotes:
   NSH keeps single quotes literally.
   `echo "sleep 15" > /fs/b.sh`, then `echo "<cmd>" >> /fs/b.sh` per line,
   and finish with `echo "echo BURSTDONE" >> /fs/b.sh`.
2. Send `sh /fs/b.sh` and stop the bridge within the 15 s sleep.
3. Wait for the run to finish, restart the bridge and drain the backlog with
   `$D/nsh_console_exec.py --monitor --timeout 5`. The 8 KB up-buffer uses
   TRIM mode, so the oldest lines are dropped when it overflows.

Each bridge restart is a fresh connect and carries the reset hazard of the
connect-safety reference. If the bridge exits 3, stop and report.

## NSH limits on these images

| Limit | PX4 rdk-rzv2h profiles | NuttX `ipcc-raw-*` demo images |
|---|---|---|
| `CONFIG_NSH_MAXARGUMENTS` | 15 on drone/dualcr8, NuttX default 7 elsewhere | 16 |
| `CONFIG_SCHED_WAITPID` | yes: builtins run in the foreground | no: builtins run in the background, output follows the prompt, so wait with `--until 'REGEX'` |
| Idle-shell logging | yes (`CONFIG_DEBUG_INFO` clock lines): use `--marker` | rare |

All of them:

- "too many arguments" means use fewer tokens. Rely on the command's
  defaults.
- The RTT down-buffer (host → target) is 1 KB and the up-buffer 8 KB in
  TRIM mode. Keep commands short; `nsh_console_exec.py` paces the bytes.
- The RTT telnet port takes one client at a time. Use one
  `nsh_console_exec.py` run per batch of commands.
- Ctrl-C over RTT does not stop a blocking command (e.g. a `hexdump` of
  `/dev/ipcc1`). Diagnose unresolved task state, then use the guarded loader
  under the project's standing board authorization when recovery needs it.

Check a profile before relying on a limit:
`grep -E 'NSH_MAXARGUMENTS|SCHED_WAITPID|DEBUG_INFO' boards/renesas/rdk-rzv2h/nuttx-config/<profile>/defconfig`.

## When something goes wrong

| Symptom | Likely cause → move |
|---|---|
| Bridge exit 3 with "RESET" | reset invalidates image execution; preserve logs, preflight host state and restore the known image/pair under the project grant |
| Bridge exit 3 with "held in reset or was never started" | CR8 not running; DBGEN alone is not a reset. Preserve logs, verify core/ELF identity and use the main skill's recovery sequence without another permission question. |
| `nsh_console_exec.py` exit 1, prompt mode | log lines after the prompt → retry with `--marker` (on the drone image: prompt mode 1 of 3 runs, `--marker` 3 of 3; ~2.7 `SCI6 clocks enabled` lines/s) |
| `--marker` also times out | core halted or crashed, or stale RTT address → oneshot `bt` + `info registers pc cpsr` |
| Oneshot exit 3 | owner on the probe or port (preflight). On WSL, check `usbipd` |
| PC parked at `0x0` / `0xffffffff` on verify | the image did not start. Read the load log; check the ELF/core pairing (entry address) |
| CR8-1 counters frozen | CR8-1 halted or crashed: oneshot `bt` on CR8-1, then dump the `g_sci1port` log |
