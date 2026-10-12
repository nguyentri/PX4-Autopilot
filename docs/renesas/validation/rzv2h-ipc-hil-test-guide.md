# RZ/V2H Raw IPC — HIL Test Guide (`/dev/ipcc1` CR8-0 ↔ CR8-1)

Repeatable hardware-in-the-loop procedure to qualify the CR8-0 ↔ CR8-1 native
raw IPC link and run the `ipctest` ping/echo acceptance (100/100, both
directions) on live silicon. Companion to the address-contract proof in
[rzv2h-three-core-ipc-artifacts.md](../evidence/rzv2h-three-core-ipc-artifacts.md) and the
probe/reset rules in
[rzv2h-three-core-jlink-contract.md](../rzv2h-three-core-jlink-contract.md).

## What the link does

- `/dev/ipcc1` = raw MHU-B-NS doorbell IPC, Link 1, CR8-0 ↔ CR8-1.
- CR8-0 is the **initiator** (owns the recovery epoch), CR8-1 the **responder**
  (adopts the initiator epoch). The responder converges automatically on the
  doorbell/poll path — no manual `--recover` on CR8-1.
- Boot auto-echo waits for a ready, non-degraded link before echoing, so it
  does not spin on a half-open link.

This guide qualifies the native raw IPC ABI-v2 owned by
`rzv_ipc_channels.h`. It is separate from the reference CA55 RPMsg/RPC/uXRCE
path and from the optional CA55 profile. A missing target transcript leaves a
physical qualification gate open; it does not block source-backed standalone
CR8 software work.

## Prerequisites

- Built images for both cores, verified against the address contract first
  (see the artifacts doc's Repro Commands). Load order matters — verify both
  before touching the target.
- `gdb-multiarch` on the host. Do **not** use `arm-none-eabi-gdb` here; its
  bundled Python is broken in this environment.
- SEGGER J-Link tools: `JLinkGDBServerCLExe` (for the volatile load) and
  `JLinkExe` (for RTT bridging). Know your probe serial number and use SWD.
- Core device selectors: CR8-0 = `R9A09G057H44_R8_0`, CR8-1 =
  `R9A09G057H44_R8_1`.
- Discover `_SEGGER_RTT` from each exact loaded ELF. Historical raw-image
  addresses were CR8-0 `0x081A0000` and CR8-1 `0x081E0000`.

Helper GDB scripts live in `platforms/nuttx/Debug/rzv2h-ipc/`:

| Script | Purpose | Mutating? |
|---|---|---|
| `rzv2h-ipc-hil-readonly.gdb` | Attach, dump regs/bt, read GIC SPI target bytes | no |
| `rzv2h-ipc-hil-loadstart.gdb` | Volatile RAM load + PC=`__start` + `go`, no reset | yes (RAM + run) |
| `rzv2h-ipc-hil-verify-resume.gdb` | Brief halt to confirm a core is running + SPIs retargeted, then resume | no lasting change |
| `../nuttx-rtt-bridge.sh` | Attach JLinkExe to one core and serve RTT using its ELF | owns probe; no reset |

## Procedure

### 1. Verify the address contract (read-only, off-target)

Use the checker described in the artifact record with the canonical manifest
and the expected SHA-256 for each selected ELF. Each must print
`RESULT=ADDRESS_CONTRACT_VERIFIED`. Historical recorded hashes apply only to
those images. Stop on a mismatch; checker success alone does not authorize a
subsequent load. Reset, RAM load and target writes require explicit approval.

### 2. Load CR8-0 first (initiator)

The initiator must publish the recovery headers before the responder boots so
the responder adopts them at bring-up. Start one J-Link GDB server for the
CR8-0 device selector, then:

```sh
gdb-multiarch -q -batch <cr8_0-elf> -x platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-hil-loadstart.gdb
```

This writes the PT_LOAD segments to core-local RAM, sets PC to `__start`,
resumes, and detaches — **no `monitor reset`** (a reset here has unmeasured
SoC-wide scope while a peer image may already be resident).

### 3. Load CR8-1 last (responder)

Restart the GDB server for the CR8-1 device selector and repeat the loadstart
with `<cr8_1-elf>`. On boot the responder finds the initiator's RECOVERING
headers and adopts the epoch, coming up ready with a live auto-echo.

### 4. Drive `ipctest` over RTT

Follow the [deployment guide](../../deployment-guide.md) to attach
`nuttx-rtt-bridge.sh` to CR8-0 with the exact loaded ELF. It uses JLinkExe on
`127.0.0.1:19021`; JLinkGDBServer cannot bridge CR8 RTT. Stop the GDB session
before starting RTT. A single probe serves one core's RTT at a time.

On the CR8-0 NSH prompt:

```sh
ipctest --recover -d /dev/ipcc1
ipctest --ping    -d /dev/ipcc1 -n 100 -s 64
```

`--recover` performs the bounded two-sided rendezvous (initiator publishes a
fresh epoch and doorbells; the responder adopts). Running `--recover` again on
an already-healthy link returns immediately — it does not re-arm the wait.

### 5. Expected output

```
IPCTEST_RESULT core=CR8-0 mode=recover dev=/dev/ipcc1 status=pass
...
ipctest ping: 100/100 pass, 0 timeout
IPCTEST_RESULT core=CR8-0 mode=ping dev=/dev/ipcc1 status=pass pass=100 expected=100 timeouts=0
```

Final stats: `epoch=2 ready=1 degraded=0 tx=100 rx=100 invalid_headers=0
invalid_entries=0`, and no data abort / stack-pointer fault.

## Manual interactive demo

Once the 100/100 path above passes, the same two RTT consoles drive a
human-in-the-loop demo — no rebuild, no extra hardware. Text rides inside the
fixed 64-byte raw frame, so the peer echoing the identical frame *is* the ack;
the driver and the raw ABI are untouched.

### Demo modes

| Flag | Role | Behavior |
|---|---|---|
| `--say "<text>"` | sender | Send one text frame, wait for the echo, verify byte-match, print `IPCTEST_ACK`. Text ≤ 60 chars. |
| `--sink` | peer | Loop: display each received frame's decoded text (`IPCTEST_RX`), then echo it back as the ack. Ctrl-C to stop. Serves both `--say` and `--heartbeat`. |
| `--heartbeat` | sender | Send `-n` beats, one every `--interval` ms, each with a sequence + label; print per-beat round-trip latency and a summary. |
| `--interval <ms>` | option | Heartbeat period (default 1000 ms). |

`--say`/`--sink`/`--heartbeat` always emit exactly 64 bytes, so the `-s` size
rule that applies to `--ping`/`--echo` is not needed for them.

### Two-console run (relay + ack)

Bring up both cores per the [Procedure](#procedure) above (CR8-0 first, CR8-1
last). For simultaneous consoles with one probe, use the SCI4 + RTT split
below. For RTT-only operation, switch the single bridge between cores as the
autotest does; do not start competing probe owners.

1. On the **CR8-0** NSH (the peer that displays):

   ```sh
   ipctest --sink -d /dev/ipcc1
   ```

2. On the **CR8-1** NSH (the sender):

   ```sh
   ipctest --say "hello core0" -d /dev/ipcc1
   ```

3. Expected — CR8-0 prints the received text, CR8-1 prints the matching ack:

   ```text
   # CR8-0 (--sink)
   IPCTEST_RX core=CR8-0 from=peer kind=say seq=0 text="hello core0"

   # CR8-1 (--say)
   IPCTEST_ACK core=CR8-1 dev=/dev/ipcc1 seq=0 text="hello core0"
   IPCTEST_RESULT core=CR8-1 mode=say dev=/dev/ipcc1 status=pass
   ```

Swap the roles (run `--sink` on CR8-1 and `--say` on CR8-0) to prove the
reverse direction with the same binaries.

### Heartbeat

Keep `--sink` running on one core and start the beat on the other:

```sh
ipctest --heartbeat -d /dev/ipcc1 -n 5 --interval 1000
```

Expected on the sender:

```text
IPCTEST_ARMED core=CR8-0 mode=heartbeat dev=/dev/ipcc1 count=5 interval=1000
IPCTEST_BEAT core=CR8-0 dev=/dev/ipcc1 seq=0 rtt_ms=1
...
ipctest heartbeat: 5/5 beats, 0 timeout
  latency min/avg/max = 1/1/2 ms
IPCTEST_RESULT core=CR8-0 mode=heartbeat dev=/dev/ipcc1 status=pass beats=5 timeouts=0
```

The `--sink` console prints one `IPCTEST_RX ... kind=beat` line per beat.

### Single-probe transport split (SCI4 + RTT), one screen recording

The two-console recipe above needs one RTT session per core, but a single
physical J-Link can bridge only **one** RTT control block at a time. To film
both cores of the link with one probe, split the console transports: keep CR8-1
on RTT and move CR8-0's NSH to the SCI4 physical UART (P70/P71). SCI4 is a plain
UART independent of the MHU IPC link, so the 100/100 `/dev/ipcc1` path is
untouched — only where CR8-0's console prints changes.

**Images** — build CR8-0 from the SCI4-console variant, CR8-1 unchanged:

| Core | Build config | Console |
|---|---|---|
| CR8-0 (initiator) | `rdk-rzv2h:ipcc-raw-cr8_0-sci4` | SCI4 UART, 115200 8N1 |
| CR8-1 (responder) | `rdk-rzv2h:ipcc-raw-cr8_1` | RTT block `0x081E0000` |

`ipcc-raw-cr8_0-sci4` is `ipcc-raw-cr8_0` with the NSH console moved from RTT to
SCI4; role, loopback, and the 64-B raw ABI are identical.

**Wiring** — one J-Link to the board (SWD) for CR8-1 RTT, plus an FT232
USB-serial adapter on the SCI4 pins (P70 TXD / P71 RXD, GND common) at 115200
8N1 for CR8-0. Under WSL, `usbipd attach --wsl --busid <id>` both the J-Link and
the FT232; the FT232 then enumerates as e.g. `/dev/ttyUSB0`.

**Run** (scripts in `platforms/nuttx/Debug/rzv2h-ipc/`). One command does everything and
opens **both** NSH consoles side by side in a single `tmux` window:

1. **One command.** Loads **both** cores to DDR (CR8-0 first), verifies each is
   running, opens the CR8-1 RTT bridge on `127.0.0.1:19021`, then launches a
   `tmux` window with the CR8-0 SCI4 console (left, `picocom` on `/dev/ttyUSB0`)
   and the CR8-1 RTT console (right, `nc`/`telnet` on `:19021`). Add `--build`
   to rebuild both images first; it reloads both cores every launch (a board
   reset wipes the volatile DDR image, so "reset" == rerun this):

   ```sh
   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh            # uses the built ELFs
   JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-run.sh --build    # rebuild first
   ```

   The loader checks probe ownership; stop a session you own before running
   it and do not terminate another user's session. The FT232 must be attached
   as `/dev/ttyUSB0` (override with
   `SCI_PORT=`). Quit by exiting both tmux panes (picocom `Ctrl-A Ctrl-X`, nc
   `Ctrl-C`), which stops the bridge and releases the probe. tmux prefix is
   `Ctrl-b` (switch panes `Ctrl-b o`). Use `--no-tmux` to instead get the RTT
   console in the current terminal and open CR8-0 SCI4 yourself.

2. Screen-record the one tmux window, then run the relay+ack across the panes —
   e.g. CR8-1 (RTT, right) displays, CR8-0 (SCI4, left) sends:

   ```sh
   # CR8-1 (RTT pane)
   ipctest --recover -d /dev/ipcc1
   ipctest --sink    -d /dev/ipcc1

   # CR8-0 (SCI4 pane)
   ipctest --say "hello core1" -d /dev/ipcc1
   ipctest --heartbeat -d /dev/ipcc1 -n 5 --interval 1000
   ```

   The output lines are identical to the all-RTT recipe — only the transport
   each console rides on differs. Swap `--sink`/`--say` between the two panes to
   film the reverse direction.

**Manual / step-by-step alternative.** When you want to drive each stage
yourself (or debug one), use the split scripts instead of `run.sh`:

```sh
# build both images only (ELFs -> nuttx-<config>.elf)
JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-build-and-load.sh --build-only
# silent load + auto-verify both, then exit (frees the probe)
JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-auto.sh <cr8_0-sci4-elf> <cr8_1-elf>
# guided steps: load | verify | reset <0|1> | rtt | sci  (see `guide`)
JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-load-both-manual.sh guide
./rzv2h-ipc-demo-load-both-manual.sh rtt          # CR8-1 RTT bridge -> :19021
./rzv2h-ipc-demo-load-both-manual.sh sci /dev/ttyUSB0
```

**Automated regression (RTT only, no UART).** One command RAM-loads both cores
(RTT-console images `ipcc-raw-cr8_0` + `ipcc-raw-cr8_1`), drives CR8-0 NSH over
RTT (`ipctest --recover`, `--ping -n 100 -s 64`), then switches the RTT bridge to
CR8-1 and reads the `mode=auto-echo` result its boot task printed. Exit 0 = PASS;
1 IPC check failed, 2 usage/preflight, 3 load failed, 4 RTT transport dead.
Transcripts go to `rzv2h-ipc/logs/autotest-<ts>/` (gitignored, serial masked).

```sh
JLINK_SERIAL=<probe-sn> ./rzv2h-ipc-demo-autotest.sh [cr8_0-rtt-elf] [cr8_1-elf]
```

It uses the generic `platforms/nuttx/Debug/nuttx-rtt-bridge.sh` (JLinkExe RTT
bridge, no reset/halt) and `nsh_console_exec.py` (scripted NSH over RTT or UART),
which work for any NuttX/PX4 image.

### Optional console variant: SCI4 display on CR8-1

The transport split above puts SCI4 on **CR8-0** (`ipcc-raw-cr8_0-sci4`).
Showing the relayed text on a physical UART owned by **CR8-1** instead is still a
separate physical-qualification task: SCI4 (P70/P71) is a single physical UART with no multi-core
arbitration, and both the flight `default.px4board` and the `ipcc-raw-cr8_0-sci4`
image already assign it to CR8-0. Handing SCI4 to CR8-1 means rebuilding the
CR8-1 image with `CONFIG_RZV_SCI4` **and** taking it out of the CR8-0 image to
avoid a two-master pin conflict. Not required for the demos above. The
`115200` setting in the split-console profile is explicit to that test image;
it does not change native telemetry's 57600 default or silently adopt the
reference startup's 115200 setting.

## Interpreting failures

| Symptom | Likely cause |
|---|---|
| `--recover` returns `ETIMEDOUT` (116), link `degraded=1` | Responder never adopted — check load order (CR8-0 before CR8-1) and that both images carry the convergence fix. |
| Echo prints `echo transport error` and exits | Poll returned `POLLERR` — the link diverged in a way that is not a clean recovery. Re-run `--recover` on the initiator. |
| Unexpected-IRQ panic on a core | MHU SPI not retargeted to the local core. Confirm with `rzv2h-ipc-hil-verify-resume.gdb` that the SPI target bytes (INTID 347/348/359/360) hold the local CPU mask, not `0x01`. |
| Data abort / `User Stack pointer is not within the stack` on `--ping` | Demo task stack too small. `CONFIG_EXAMPLES_RZV_IPC_DEMO_STACKSIZE` must be 4096 for the two-buffer ping frame. |

## Safety

Treat the target as live hardware: verify the address contract before any load,
attach read-only first, and never issue `monitor reset` after an image is
resident until the reset scope is measured. Follow the measured, approved detach/run
contract for that session; the J-Link metadata alone does not prove detach state. Do not copy ELF contents, memory dumps, RTT buffers, or probe
serial numbers outside the workspace.
