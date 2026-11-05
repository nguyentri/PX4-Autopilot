# RZ/V2H NSH / RTT / SVD Recipes

Fast, mostly non-halting triage for RZ/V2H CR8 NuttX images. Generic tools live
in `platforms/nuttx/Debug/` (abbreviated `$D` below); RZ/V2H IPC demo/HIL
scripts in `$D/rzv2h-ipc/`.

Use the [IPC shell-script routes](rzv2h-repo-tooling-and-scripts.md#ipc-shell-script-routes)
to choose build, load, autotest or interactive helpers. Board access and
task-required recovery are covered by the project's standing authorization;
these recipes do not require a new permission question.

## Host hardware map (WSL2)

| USB ID | Device | Host path | Use |
|---|---|---|---|
| `1366:1020` | SEGGER J-Link | usbipd → WSL | GDB server, JLinkExe RTT bridge |
| `0403:6001` | FTDI FT232 (optional) | `/dev/ttyUSB0` (group `dialout`) | CR8-0 SCI4 NSH, 115200 8N1 — not needed for RTT flows |

If either is missing in `lsusb`, ask the user to `usbipd attach --wsl --busid <id>`
from an admin PowerShell (see comment in `.vscode/launch.json`). Do not guess.

## Which console is where

| Image | Core | NSH console | `_SEGGER_RTT` |
|---|---|---|---|
| PX4 `build/renesas_rdk-rzv2h_*/…elf` | CR8-0 | RTT ch0 | `0x081a2400` |
| PX4 `build/renesas_rdk-rzv2h-io-cr8_1_default/…elf` | CR8-1 | none (log in `g_sci1port.xmit`) | none |
| NuttX `nuttx-ipcc-raw-cr8_0-sci4.elf` | CR8-0 | SCI4 → `/dev/ttyUSB0` | none |
| NuttX `nuttx-ipcc-raw-cr8_0.elf` | CR8-0 | RTT ch0 | `0x081A0000` |
| NuttX `nuttx-ipcc-raw-cr8_1.elf` | CR8-1 | RTT ch0 | `0x081E0000` |

`$D/jlink-debug-preflight.py` lists every ELF in the tree with its core and
RTT address. Always pass the ELF to the bridge: the `cr8_0` alias default is
the NuttX address, which is wrong for PX4.

## Recipe 1 — NSH over SCI4 serial (optional, no probe needed)

```bash
$D/nsh_console_exec.py --serial /dev/ttyUSB0 'uname -a' 'ps' 'free' 'dmesg'
$D/nsh_console_exec.py --serial /dev/ttyUSB0 --log /tmp/nsh.log -f cmds.txt
```

Interactive alternative: `picocom -b 115200 /dev/ttyUSB0` (exit Ctrl-A Ctrl-X).
Only one process may own the tty: close picocom before running the script.

## Recipe 2 — NSH over RTT (single probe)

```bash
JLINK_SERIAL=<probe-sn> $D/nuttx-rtt-bridge.sh start cr8_1 platforms/nuttx/NuttX/nuttx/nuttx-ipcc-raw-cr8_1.elf
$D/nsh_console_exec.py 'ps' 'ipctest --recover -d /dev/ipcc1'    # --rtt is default
$D/nuttx-rtt-bridge.sh stop    # MUST stop before JLinkGDBServer / VS Code attach
```

The bridge attaches without reset or halt **only when its first connect
succeeds**. It sets `InhibitConnectRetries` and exits 3 if the J-Link log
still shows a reset or failed connect. Preserve the log and report whether an
actual reset was observed; failed connect alone does not prove lost execution.
Use the main skill's recovery sequence. The core keeps running after
`stop`. On PX4 images add `--marker` to `nsh_console_exec.py`.
JLinkGDBServer cannot serve RTT on this target — use the bridge, not port 50002.
If cortex-debug's RTT terminal stays empty, detach and use the bridge instead.

## Recipe 3 — register read, CPU view (authoritative, non-halting)

NSH `mw`/`mh`/`mb` performs the load from the CR8 itself, with its MPU
attributes — this is the value firmware sees, never debug-port fill.

```bash
$D/svd_register_tool.py cmd nsh R_SCI4.CCR0 R_SCI4.CESR R_CPG.CPG_BUS_11_MSTOP \
  | $D/nsh_console_exec.py -f - | $D/svd_register_tool.py decode-log
```

`mw addr=value` writes memory. Use it only when the requested debug task needs
a write; the project grant does not turn a read request into a write.
A read of an unclocked/MSTOP'd peripheral can data-abort the core: check the
module's MSTOP bit first (`decode R_CPG.CPG_BUS_<n>_MSTOP <val>`).

## Recipe 4 — register read, debug view (halts the core)

```bash
$D/svd_register_tool.py cmd gdb R_SCI4 > <scratch>/regs.gdb   # printf + x/ reads only
JLINK_SERIAL=<probe-sn> $D/jlink-gdb-oneshot.py cr8_0 <elf> --attempts 1 -x <scratch>/regs.gdb 2>&1 \
  | $D/svd_register_tool.py decode-log
```

`jlink-gdb-oneshot.py` adds the attach and the detach itself and refuses
any line that could write.

Compare with Recipe 3. Mismatch, or `0xaa`/`0xaaaaaaaa` here only → debug
access path (AP / MPU / bus) problem, not the peripheral value.
`detach` resumes the core; reads of read-to-clear registers (status/FIFO data)
have side effects in both views — skip `RDR`-like registers unless asked.

## Recipe 5 — name a fault address

```bash
$D/svd_register_tool.py addr 0x12801c1c       # DFAR/DFSR context -> R_SCI4.CESR
$D/svd_register_tool.py find 'GIC|MHU.*MSG'   # regex search across 41k regs
$D/svd_register_tool.py info R_MHU_NS0        # full register map of a block
```

`rzv2h.svd` has no Cortex-R8 core/GIC registers (GIC dist base `0x12C10100`);
use the existing `platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-hil-readonly.gdb` for those.

## Recipe 6 — IPC autotest (RTT only, one probe)

Proves CR8-0 ↔ CR8-1 over `/dev/ipcc1` with evidence from BOTH cores, no UART.
Mutating: RAM-loads both images (no reset with peer resident) — state ELFs,
`<probe-sn>`, devices before running.

```bash
JLINK_SERIAL=<probe-sn> $D/rzv2h-ipc/rzv2h-ipc-demo-autotest.sh \
  [nuttx-ipcc-raw-cr8_0.elf] [nuttx-ipcc-raw-cr8_1.elf]   # defaults: NuttX tree
```

Flow: load both → bridge CR8-0 → `uname`, `ipctest --recover`, `--ping -n 100
-s 64`, `free` → bridge stop → bridge CR8-1 → listen-only `--monitor` drain of
its RTT up-buffer → `uname`, `ps`, `free` → crash scan → verdict. Bridge
stopped and probe serial masked in logs on every exit path (incl. Ctrl-C).
Logs: `platforms/nuttx/Debug/rzv2h-ipc/logs/autotest-<ts>/` (gitignored; `LOG_DIR` must be new/empty).

| Check | Source | Pattern |
|---|---|---|
| recover | CR8-0 RTT | `mode=recover … status=pass`, `IPCTEST_STATS … ready=1` |
| ping | CR8-0 RTT | `mode=ping status=pass pass=100 expected=100 timeouts=0`, `IPCTEST_STATS … rx=100` |
| CR8-1 own proof | CR8-1 RTT drain | `mode=auto-echo … status=pass echoed=100 expected=` |
| task done | CR8-1 `ps` | no `ipc-auto-echo` (FAIL if `ps` itself fails) |
| liveness | both | `free` returns `nsh>`; no `data abort` / stack-pointer / assert |

Exit: 0 pass · 1 IPC/liveness check failed · 2 usage/preflight (no
JLINK_SERIAL, missing ELF, bridge already up, non-empty LOG_DIR) · 3 load
failed · 4 RTT console transport dead (bridge or NSH) — not an IPC verdict.

Why the CR8-1 line survives the bridge switch: CR8-1's boot `ipc-auto-echo`
task is bounded (`CONFIG_EXAMPLES_RZV_IPC_DEMO_DEFAULT_COUNT=100`) and prints
its own `IPCTEST_RESULT` when done, while the bridge is on CR8-0. Nobody reads
CR8-1's 8 KB up-buffer until the bridge moves, so the line is still there.
Consequences: ping count must stay 100; one-shot per load (echo task exits;
rerun = reload). CR8-0 image needs `CONFIG_NSH_MAXARGUMENTS=16` (ping = 8 tokens).

## Symptom → first move

| Symptom | First move |
|---|---|
| NSH answers, feature misbehaves | Recipe 1/2 (`ps`, `dmesg`, app cmd) + Recipe 3 for the peripheral |
| No NSH prompt (`nsh_console_exec` exits "no prompt") | core halted by a debugger, crashed, or wrong console → Recipe 4 attach, `bt`, check `arm_dataabort` |
| Register value "impossible" | Recipe 3 vs 4; then MSTOP / clock / MPU region |
| Data abort, DFAR set | Recipe 5 on DFAR, then abort workflow in `rzv2h-cr8-playbook.md` |
| "Does the IPC demo still work?" / regression check | Recipe 6; exit 4 → fix RTT transport (probe/usbipd, bridge log) before blaming IPC |
| Need a variable / backtrace from a running core | `jlink-gdb-oneshot.py <core> <elf> --attempts 1 -ex 'bt' -ex 'p var'` (halts 1-3 s) |
| Need source-level stepping / live watch | VS Code `IPC RZV2H — load BOTH, attach CR8-x`; its preLaunchTask reloads both cores; preserve a read-only request with oneshot instead |

## Gotchas

- NSH `CONFIG_NSH_MAXARGUMENTS` is 16 on the NuttX IPC demos, 15 on PX4
  drone/dualcr8, 7 elsewhere; long commands get "too many arguments".
- RTT input is polled every 1 ms; `nsh_console_exec.py` paces bytes 2 ms apart.
- `nsh_console_exec.py` exit 1 = timeout without prompt; raise `--timeout` for
  long commands (e.g. `ipctest --ping -n 1000`). On PX4 images a log line
  after the prompt causes the same timeout: use `--marker`.
- NuttX IPC demo images: no `CONFIG_SCHED_WAITPID` → NSH runs builtins in background (`app [pid:prio]`,
  prompt returns at once, output after it). Use `--until 'REGEX'` to wait for
  the app's final line; otherwise the next command races the still-running app.
- Prompt is `nsh> ESC[K` (VT100); the tool strips CSI before matching.
- JLinkExe (V8.94) selects the probe with `-USB <sn>`; `-select usb=<sn>` is
  JLinkGDBServer-only and makes JLinkExe exit ("Unknown command line option").
- JLinkExe RTT telnet serves ONE client; a second gets "already is an active
  connection" (the tool retries ~5 s). Its banner prints the probe serial —
  the tool drops it; raw `nc` sessions do not.
- Probe is effectively single-owner: bridge OR GDB server, not both.
