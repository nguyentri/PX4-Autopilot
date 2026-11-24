# RZ/V2H Raw IPC — HIL Test Guide (`/dev/ipcc1` CR8-0 ↔ CR8-1)

Repeatable hardware-in-the-loop procedure to qualify the CR8-0 ↔ CR8-1 native
raw IPC link and run the `ipctest` ping/echo acceptance (100/100, both
directions) on live silicon. Companion to the address-contract proof in
[rzv2h-three-core-ipc-artifacts.md](../evidence/rzv2h-three-core-ipc-artifacts.md) and the
probe/reset rules in
[rzv2h-three-core-jlink-contract.md](../rzv2h-three-core-jlink-contract.md).

## What the link does

- `/dev/ipcc1` = raw MHU-B-NS doorbell IPC, Link 1, CR8-0 ↔ CR8-1.
  CR8-0 owns blocks 15 (TX, rings 28) and 34 (RX); CR8-1 owns blocks 40
  (TX, rings 34) and 28 (RX), per FSP `bsp_mhu_b.h` pairing. Transcripts
  recorded before the 2026-11-09 route change (blocks 4/9) must be
  repeated on these blocks.
- CR8-0 is the **initiator** (owns the recovery epoch), CR8-1 the **responder**
  (adopts the initiator epoch). The responder converges automatically on the
  doorbell/poll path — no manual `--recover` on CR8-1.
- Boot auto-echo waits for a ready, non-degraded link before echoing. CR8-1
  performs bounded responder recovery while quarantined so it can adopt the
  initiator's epoch; reading statistics alone cannot complete that handshake.
  CR8-0 does not create recovery epochs in its boot wait. A running echo test
  still terminates on transport errors instead of silently recovering.

This guide qualifies the native raw IPC ABI-v2 owned by
`rzv_ipc_channels.h`. It is separate from the reference CA55 RPMsg/RPC/uXRCE
path and from the optional CA55 profile. A missing target transcript leaves a
physical qualification gate open; it does not block source-backed standalone
CR8 software work.

The [2026-10-22 hardware retry](../../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md)
records two consecutive complete warm loads of the repaired RTT pair. Each
passes 100 byte-exact 64-byte echoes with zero timeouts, an independent CR8-1
completion report, responder-task exit and responsive consoles on both cores.
CR8-0 reports zero invalid headers; CR8-1 increments `invalid_headers` once per
warm recovery/traffic run. The increment site was not instrumented. The
byte-exact result does not establish zero diagnostic counters on both cores.
Cold boot, long-run soak and the serial variant remain separate gates.

## Prerequisites

- Built images for both cores, verified against the address contract first
  (see the artifacts doc's Repro Commands). Load order matters — verify both
  before touching the target.
- `gdb-multiarch` on the host. Do **not** use `arm-none-eabi-gdb` here; its
  bundled Python is broken in this environment.
- SEGGER J-Link tools: `JLinkGDBServerCLExe` (for the volatile load) and
  `JLinkExe` (for RTT bridging). Know your probe serial number and use SWD.
- GNU `stdbuf` on the host. The loader disables native server output buffering
  so redirected logs expose connection failure and readiness messages promptly.
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

The initiator publishes the recovery headers before the responder boots. With
explicit RAM-load approval, use the guarded pair loader:

```sh
JLINK_SERIAL=<probe-sn> platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh <cr8_0-elf> <cr8_1-elf>
```

### 3. Verify both cores

The pair loader starts CR8-0, then CR8-1, and performs a brief halt/PC/resume
check of each. It uses one connection attempt per operation, always with
`-noreset -noir`. A core held in reset (DBGEN with no reset marker, so no image
runs there) is started once by a plain J-Link connect, which runs the DLL's CR8
start sequence; its guarded load then runs once more. Any other failed-connect
or reset marker, including one from that start connect, stops the batch; another
attempt requires renewed approval. `LOAD_ATTEMPTS`, if provided, must be `1`.
The compatibility `load-both.sh` entry delegates to this same loader.

The loader waits for both its server's listening socket and the target-ready
message before starting GDB. A listening socket alone does not prove target
connection; buffered server output can otherwise cause a false startup timeout.

The loader supplies the endpoint from `GDB_PORT` (default 50000) to its
`loadstart.gdb` and `verify-resume.gdb` command files. These files require an
already connected session; invoke the shell wrapper instead of starting an
unguarded GDB server. Running PC evidence alone does not qualify IPC traffic.

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

The raw sample driver allows 30 seconds for a recovery ioctl; the autotest
allows 35 seconds including console overhead. A timeout leaves completion
unresolved and stops the sequence before ping.

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

CR8-0 final stats: `epoch=2 ready=1 degraded=0 tx=100 rx=100 invalid_headers=0
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
last). For simultaneous consoles with one probe, use the dual RTT bridge
(`platforms/nuttx/Debug/rzv2h-dual-rtt-bridge.py start`, or `console --action
start --dual` / the VS Code RTT Monitor): one J-Link session reads both control
blocks over the AXI-AP and serves CR8-0 on 19021 and CR8-1 on 19031 without
halting either core (board gate:
`docs/renesas/evidence/dual-rtt-single-probe-axi-ap-gate-261110.md`). Do not
start two JLinkExe RTT bridges on one probe: on 2026-11-09 both attached
without a reset, but input typed in the second session reached the first core.
The serial + RTT split below and switching one bridge between cores remain
fallbacks.

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

### Single-probe transport split (serial + RTT), one screen recording

The two-console recipe above needs one RTT session per core, but a single
physical J-Link can bridge only **one** RTT control block at a time. To film
both cores of the link with one probe, split the console transports: keep CR8-1
on RTT and move CR8-0's NSH to the board serial UART (SCI5, P72/P73). That UART is a plain
UART independent of the MHU IPC link, so the 100/100 `/dev/ipcc1` path is
untouched — only where CR8-0's console prints changes.

**Images** — build CR8-0 from the serial-console variant, CR8-1 unchanged:

| Core | Build config | Console |
|---|---|---|
| CR8-0 (initiator) | `rdk-rzv2h:ipcc-raw-cr8_0-serial` | Serial UART (SCI5), 115200 8N1 |
| CR8-1 (responder) | `rdk-rzv2h:ipcc-raw-cr8_1` | RTT block `0x081E0000` |

`ipcc-raw-cr8_0-serial` is `ipcc-raw-cr8_0` with the NSH console moved from RTT to
the board serial UART; role, loopback, and the 64-B raw ABI are identical.

**Wiring** — one J-Link to the board (SWD) for CR8-1 RTT, plus an FT232
USB-serial adapter on the board serial UART pins (SCI5: P72 TXD / P73 RXD, GND common) at 115200
8N1 for CR8-0. Under WSL, `usbipd attach --wsl --busid <id>` both the J-Link and
the FT232; the FT232 then enumerates as e.g. `/dev/ttyUSB0`.

**Run** (scripts in `platforms/nuttx/Debug/rzv2h-ipc/`). One command does everything and
opens **both** NSH consoles side by side in a single `tmux` window:

1. **One command.** Loads **both** cores to DDR (CR8-0 first), verifies each is
   running, opens the CR8-1 RTT bridge on `127.0.0.1:19021`, then launches a
   `tmux` window with the CR8-0 serial console (left, `picocom` on `/dev/ttyUSB0`)
   and the CR8-1 RTT console (right, `nc`/`telnet` on `:19021`). Add `--build`
   to rebuild both images first; it reloads both cores every launch (a board
   reset invalidates the running images and requires a fresh load):

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
   console in the current terminal and open CR8-0 serial yourself.

2. On the already-loaded pair, complete the bounded 100-message test commands
   below first, skipping its build/load/console setup. This leaves no boot
   echo task competing for replies. Then run the relay+ack across the panes —
   CR8-1 (RTT, right) displays, CR8-0 (serial, left) sends:

   ```sh
   # CR8-1 (RTT pane)
   ipctest --sink    -d /dev/ipcc1

   # CR8-0 (serial pane)
   ipctest --say "hello core1" -d /dev/ipcc1
   ipctest --heartbeat -d /dev/ipcc1 -n 5 --interval 1000
   ```

   The output lines are identical to the all-RTT recipe — only the transport
   each console rides on differs. Swap `--sink`/`--say` between the two panes to
   film the reverse direction.

**Manual / step-by-step alternative.** When you want to drive each stage
yourself, run from the repository root:

```sh
D=platforms/nuttx/Debug
N=platforms/nuttx/NuttX/nuttx
source ./build_setup.sh

# Preserve each ELF before the next build overwrites the shared nuttx output.
"$D/rzv2h-ipc/rzv2h-ipc-demo-build-and-load.sh" --build-only
export JLINK_SERIAL="$("$D/jlink-debug-preflight.py" --print-serial)"

# Load saved CR8-0 serial + CR8-1 RTT images and verify both, without rebuilding.
"$D/rzv2h-ipc/rzv2h-ipc-demo-build-and-load.sh" --load-only

# After successful verification, start CR8-1 RTT in this terminal.
C1="$N/nuttx-ipcc-raw-cr8_1.elf"
"$D/nuttx-rtt-bridge.sh" start cr8_1 "$C1"
nc 127.0.0.1 19021
```

Open CR8-0 serial in a second terminal, substituting the actual UART path:

```sh
platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-demo-type-cr8_0-serial.sh /dev/ttyUSB0
```

`--load-only` uses the saved `nuttx-ipcc-raw-cr8_0-serial.elf` and
`nuttx-ipcc-raw-cr8_1.elf` files, checks both exist before invoking the guarded
loader, and returns only after its load/verify operation finishes. It retains
the shared build lock so this helper cannot overwrite those files concurrently.
`OUT_DIR`, `CR8_0_CONFIG` and `CR8_1_CONFIG` retain their existing meanings;
use the same overrides when building and loading, and pass the matching saved
ELF to RTT. Do not externally overwrite images during a load. A failure stops
the sequence; inspect its logs before a deliberate recovery attempt.
`--build-only` and `--load-only` cannot be combined. With neither flag, the
existing build-then-load behavior is unchanged. None of these modes starts a
console; `--help` prints the options and manual console commands.

On **CR8-0 serial**, run `ps`. Both configurations start an `ipc-auto-echo` task;
stop only that task on CR8-0 with `kill <pid>` using its actual numeric PID,
and confirm it disappears before sending test traffic. The killed task prints
`mode=auto-echo status=error echoed=0 expected=100`: a bounded auto-echo
stopped before its count is never reported as a pass, so this line is expected
here and is not a demo failure. Leave CR8-1's boot
auto-echo running. Run these commands sequentially on CR8-0, waiting up to
35 seconds for recovery to finish before ping:

```text
ipctest --recover -d /dev/ipcc1
ipctest --ping -d /dev/ipcc1 -n 100 -s 64
```

Require CR8-0 `mode=ping status=pass pass=100 expected=100 timeouts=0` and
CR8-1 `mode=auto-echo status=pass echoed=100`. Confirm CR8-1's `ipc-auto-echo`
task has exited before starting `--sink` for the text/heartbeat demo above.
The sample commands run asynchronously on these configurations: wait for their
result lines, not just the next NSH prompt. Reload the pair for another bounded
boot-echo test, or explicitly start one new echo peer when no reader remains.

Exit picocom with `Ctrl-A Ctrl-X`, leave `nc` with `Ctrl-C`, then stop the RTT
bridge from the first terminal:

```sh
"$D/nuttx-rtt-bridge.sh" stop
```

**VS Code workspace images + μScope viewer.** The firmware-workspace group
`rzv-native-ipc-serial` stages the same pair as
`build/workspace-artifacts/<receipt-id>/rzv-native-ipc-serial-cr8_{0,1}.elf`. After
loading that pair (`rzv2h-ipc-demo-load-both-auto.sh <cr8_0-elf> <cr8_1-elf>`),
bridge CR8-1 RTT with the matching staged ELF; CR8-0 has no RTT block in this
variant, so its console stays on the serial UART:

```sh
export JLINK_SERIAL=$(platforms/nuttx/Debug/jlink-debug-preflight.py --print-serial)
A=build/workspace-artifacts/<receipt-id>
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_1 "$A/rzv-native-ipc-serial-cr8_1.elf"
platforms/nuttx/Debug/nuttx-rtt-bridge.sh status
# expect: RTT bridge up: cr8_1 (R9A09G057H44_R8_1) _SEGGER_RTT=0x081e0000 -> 127.0.0.1:19021
```

Connect μScope (or `nc`) to `127.0.0.1:19021`; do not start JLinkGDBServer for
it. The port serves one client at a time. Stop with `nuttx-rtt-bridge.sh stop`.

Keep GDB/Cortex-Debug stopped while RTT owns the probe. The older guided
`rzv2h-ipc-demo-load-both-manual.sh guide` route remains available.

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

On 2026-11-09 the autotest passed all seven checks with images built after the
MHU block-pairing change: recovery passed, ping returned 100/100 with 0
timeouts, and CR8-1 echoed 100/100
([run](../evidence/rtt-hil-demo-hardware-run-261109.md)).

### Optional console variant: serial display on CR8-1

The transport split above puts the serial console on **CR8-0** (`ipcc-raw-cr8_0-serial`).
Showing the relayed text on a physical UART owned by **CR8-1** instead is still a
separate physical-qualification task: the board serial UART (SCI5, P72/P73) is a single physical UART with no multi-core
arbitration, and both the flight `default.px4board` (MAVLink telemetry) and the `ipcc-raw-cr8_0-serial`
image already assign it to CR8-0. Handing it to CR8-1 means rebuilding the
CR8-1 image with `CONFIG_RZV_SCI5` **and** taking it out of the CR8-0 image to
avoid a two-master pin conflict. Not required for the demos above. The
`115200` setting in the split-console profile is explicit to that test image
and independent of the native telemetry default (also 115200).

## Interpreting failures

| Symptom | Likely cause |
|---|---|
| `--recover` returns `ETIMEDOUT` (116), link `degraded=1` | Responder never adopted — check load order (CR8-0 before CR8-1) and that both images carry the convergence fix. |
| Echo prints `echo transport error` and exits | Poll returned `POLLERR` — the link diverged in a way that is not a clean recovery. Re-run `--recover` on the initiator. |
| Unexpected-IRQ panic on a core | MHU SPI not retargeted to the local core. Confirm with `rzv2h-ipc-hil-verify-resume.gdb` that the SPI target bytes (INTID 354/355/362/368 for `/dev/ipcc1`) hold the local CPU mask, not `0x01`. |
| Data abort / `User Stack pointer is not within the stack` on `--ping` | Demo task stack too small. `CONFIG_EXAMPLES_RZV_IPC_DEMO_STACKSIZE` must be 4096 for the two-buffer ping frame. |

## Safety

Treat the target as live hardware: verify the address contract before any load,
attach read-only first, and never issue `monitor reset` after an image is
resident until the reset scope is measured. Follow the measured, approved detach/run
contract for that session; the J-Link metadata alone does not prove detach state. Do not copy ELF contents, memory dumps, RTT buffers, or probe
serial numbers outside the workspace.

## Debug helper limits

`run.sh` and manual `rtt` use `nuttx-rtt-bridge.sh` with the exact loaded ELF.
The old fixed-address `cr8_1-rtt.jlink` and GDB `rtt-hold.gdb` entry points exit
without connecting: JLinkGDBServer cannot bridge CR8 RTT and the installed
Commander does not support `rtt start`. Use the managed bridge.

The crash/frame/readonly GDB files are manual diagnostic recipes for an
already controlled debug session. The frame recipe contains a historical
address that must be replaced with the fault frame from the exact image;
never treat it as a current frame. PX4 health snippets require their matching
PX4 ELFs and cannot qualify these NuttX raw-demo images.

## Customer IPC showcase (`ipcdemo`)

A two-console customer demo on `/dev/ipcc1`: ping and text messages in both
directions, each acknowledged by the peer application, plus a heartbeat every
20 s (`CONFIG_EXAMPLES_RZV_IPC_DEMO_HEARTBEAT_MS`). Images: `ipcc-demo-cr8_0-serial` (CR8-0, NSH on the serial UART, link initiator) and
`ipcc-demo-cr8_1` (CR8-1, NSH on RTT, responder). Both start the `ipcdemo`
daemon at boot (`CONFIG_EXAMPLES_RZV_IPC_DEMO_BOOT_SHOWCASE`); it waits for the
device, brings the link up and recovers it on its own. `ipctest` stays
available for the raw-transport checks above.

Commands (either core):

| Command | Effect |
|---------|--------|
| `ipcdemo status` | Daemon/link/peer state, counters, driver `ready/degraded/epoch` |
| `ipcdemo ping [-n count] [-i interval_ms]` | Ping the other core; each ping waits for its ACK (500 ms) |
| `ipcdemo say <text>` | Send up to 60 bytes of text; the peer prints it and ACKs |
| `ipcdemo recover` | CR8-0: force a link recovery. CR8-1 only adopts the initiator's recovery |
| `ipcdemo stop` / `ipcdemo start` | Stop or restart the daemon on this core |

### Build and load

From the repository root, reusing the raw demo's build/load wrapper with the
showcase configs:

```sh
D=platforms/nuttx/Debug
N=platforms/nuttx/NuttX/nuttx
export CR8_0_CONFIG=rdk-rzv2h:ipcc-demo-cr8_0-serial CR8_1_CONFIG=rdk-rzv2h:ipcc-demo-cr8_1
"$D/rzv2h-ipc/rzv2h-ipc-demo-build-and-load.sh" --build-only
export JLINK_SERIAL="$("$D/jlink-debug-preflight.py" --print-serial)"
"$D/rzv2h-ipc/rzv2h-ipc-demo-build-and-load.sh" --load-only
```

VS Code alternative: select the **RZ/V2H IPC Showcase Demo (Serial / RTT)**
group in Firmware Setup and use Build Both, then Load Both. The extension opens
no console (see `docs/vscode-extension.md`).

Open both consoles yourself:

```sh
# CR8-1 on RTT (stop it again before any later load or debug)
"$D/nuttx-rtt-bridge.sh" start cr8_1 "$N/nuttx-ipcc-demo-cr8_1.elf"
# then connect μScope or `nc 127.0.0.1 19021`
# CR8-0 on the serial UART: any terminal on the board UART, 115200 8N1
```

### Demo script

1. `ipcdemo status` on both cores: `link up, peer ok`.
2. CR8-0 `ipcdemo ping -n 5`, then CR8-1 `ipcdemo ping -n 5`.
3. CR8-0 `ipcdemo say hello from CR8-0`, then the reverse from CR8-1.
4. Wait 40–60 s and show the heartbeat lines on both consoles.
5. Optional resilience: reload CR8-1 only (`rzv2h-load-one-core.sh cr8_1 <elf>`
   with the bridge stopped), restart the bridge, and show CR8-0 reporting
   `peer lost` then `link up` / `peer back` without intervention.

Each core sends its own heartbeat with its own counter, so each console
shows two unrelated sequences:

- `heartbeat #N sent -> <peer> replied in <t> us`: this core's heartbeat and
  the round trip to the peer's reply, measured on this core's clock. A steady
  value (about 70–100 µs) is healthy; it does not grow over time.
- `heartbeat #N received <- <peer>, interval <t> s (expected <p> s)`: the
  peer's heartbeat and the gap since its previous one, measured
  on this core's clock. `<p>` is the configured period; both images use the
  same `CONFIG_EXAMPLES_RZV_IPC_DEMO_HEARTBEAT_MS`.

While the RTT bridge is attached, J-Link halts CR8-1 for every RTT read
(stop mode on Cortex-R8). CR8-1's clock pauses during each halt, so its
timers run slow. CR8-0 therefore sees CR8-1's heartbeats arrive later than
expected (24–27 s measured at the 20 s setting), and CR8-1 sees CR8-0's arrive
early (about 15 s). With no bridge attached both cores report 20.0 s. Neither
is a link fault. The CR8-0 figure is the real
spacing. CR8-0 ping round trips can reach about 250 ms. The demo images therefore use a 400 ms raw TX-ACK
timeout (`CONFIG_RZV_IPC_TX_TIMEOUT_MS`), and CR8-1 uses a non-blocking RTT
up-buffer (`CONFIG_SEGGER_RTT_UP_MODE_TRIM`), so the link stays up with or
without a host draining RTT.

Board transcript (2026-11-07, RDK-RZ/V2H, 20 s heartbeat). CR8-1 was on
RTT and CR8-0 on serial; ping and say were sent from CR8-1. Numbers vary
between runs.

Before the RTT bridge attached (no halts, so both clocks agree):

```text
[CR8-1] ipcdemo up: responder /dev/ipcc1, heartbeat 20000 ms
[CR8-1] link up epoch=172
[CR8-1] heartbeat #1 received <- CR8-0, interval 20.0 s (expected 20.0 s)
[CR8-1] heartbeat #1 sent -> CR8-0 replied in 65 us
[CR8-0] heartbeat #4 sent -> CR8-1 replied in 65 us
[CR8-0] heartbeat #4 received <- CR8-1, interval 20.0 s (expected 20.0 s)
```

With the bridge attached, from the CR8-1 console:

```text
[CR8-1] ping #11 acked, rtt 113 us
[CR8-1] ping: 5/5 acked, rtt min/avg/max = 75/97/127 us
[CR8-1] message #16 delivered, rtt 112 us
[CR8-1] heartbeat #18 sent -> CR8-0 replied in 99 us
[CR8-1] heartbeat #13 received <- CR8-0, interval 14.9 s (expected 20.0 s)
```

The same exchange on the CR8-0 console:

```text
[CR8-0] ping #11 from CR8-1 -> ack
[CR8-0] message #16: "hello from CR8-1" -> ack
[CR8-0] heartbeat #12 sent -> CR8-1 replied in 71 us
[CR8-0] heartbeat #18 received <- CR8-1, interval 26.7 s (expected 20.0 s)
```

Ping, say and heartbeat share one sequence counter per core, so a heartbeat
number jumps after a ping burst (CR8-1 sent `#10`, then `#17`). The resilience step
adds `peer lost (3 heartbeats unacknowledged)` and then `peer back` on CR8-0.

### Recovery runbook

| Symptom | Fix |
|---------|-----|
| `link down` / `peer lost` with both daemons alive | Wait about 3–10 s: CR8-0 retries recovery every ~3 s (1 s retry + up to 2 s wait) and CR8-1 adopts it. Check `ipcdemo status` on both. To force it: CR8-0 `ipcdemo recover`. |
| CR8-1 daemon not running (`ps` shows no ipcdemo) | CR8-1 `ipcdemo start`, then CR8-0 `ipcdemo recover`. |
| Daemon wedged | `ipcdemo stop` then `ipcdemo start` on that core. |
| Raw pair (`ipctest`) after auto-echo ended | CR8-1 `ipctest --echo -d /dev/ipcc1`; within 30 s CR8-0 `ipctest --recover -d /dev/ipcc1`; then `--ping`. |
| μScope silent | `nuttx-rtt-bridge.sh status`; `stop`; `jlink-debug-preflight.py` (owners); `start cr8_1 <exact elf>`. Close other RTT viewers and Cortex-Debug. |
| Bridge exit 3 | Do not retry. Read `/tmp/nuttx-rtt-bridge/jlinkexe.log`. Reset logged: the images are lost, so reload the pair. DBGEN message: no image on that core, so reload. |
| Serial console no prompt | `lsof /dev/ttyUSB0` (close a second picocom or serial terminal); press Enter. |
| VS Code load refused with `PROBE_BUSY` | Your manual bridge holds the probe: `nuttx-rtt-bridge.sh stop`, retry the load, then restart the bridge. |
| Last resort | Stop the bridge and reload both (`rzv2h-ipc-demo-load-both-auto.sh <cr8_0.elf> <cr8_1.elf>` or VS Code Load Both); restart the bridge. |

## PX4 demosih heartbeat pair (`rzv2h_heartbeat`)

The PX4 `demosih` image and its CR8-1 peer use the same raw `/dev/ipcc1`
link, but only for liveness. CR8-0 `renesas_rdk-rzv2h_demosih` is the
initiator and CR8-1 `renesas_rdk-rzv2h-io-cr8_1_demo` is the responder. CR8-0 sends one v3
heartbeat every 100 ms; CR8-1 replies to each one it accepts, because a raw
write blocks until the peer reads and two timer-driven writers time out. Each
side reports its peer lost after 500 ms. Neither
publishes uORB or drives outputs. CR8-0 also boots and flies the SIH demo
without CR8-1; its heartbeat then stays `lost`. The `demo` drone image is
single-core (no raw IPC, no heartbeat) and is not part of this pair.

Build both (`./build.sh renesas_rdk-rzv2h_demosih`,
`./build.sh renesas_rdk-rzv2h-io-cr8_1_demo`), or select the `rzv-px4-demo`
group in the VS Code extension and run Build All and Load Both. Then:

```sh
# --load RAM-loads both images first; omit it when they are already resident.
JLINK_SERIAL=<probe-sn> platforms/nuttx/Debug/rzv2h-ipc/rzv2h-px4-demo-heartbeat-check.sh --load
```

The check queries CR8-0 only through the MAVLink shell on SCI5
(`platforms/nuttx/Debug/rzv2h-mavlink-shell-exec.py`, `/dev/ttyUSB0` at
115200, the demosih `SER_TEL1_BAUD`; PX4 images run MAVLink, not NSH, on SCI5). It queries CR8-1 through
one RTT bridge. It then holds CR8-1 halted for `HOLD_S` seconds (default 15)
with `rzv2h-core-halt-resume.sh cr8_1 hold <s>` (no reset), expects CR8-0 to
report `peer: lost` inside that window while its MAVLink shell still answers,
and expects `peer: alive` again after the hold ends. The hold stays inside one
JLinkExe session because a CR8 core halted by JLinkExe runs again as soon as
JLinkExe disconnects. Exit codes: 0 pass, 1 evidence failed,
2 usage or preflight, 3 load or J-Link connect failed (diagnose, never
blind-retry), 4 console not answering.

For a manual check, run `rzv2h_heartbeat status` on each console. A GDB
attach halts the sampled core for 1-3 s, so its peer legitimately reports
`lost` during the sample
(`rzv2h-ipc/rzv2h-px4-demo-heartbeat-health.gdb`).
