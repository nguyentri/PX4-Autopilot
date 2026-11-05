# RZ/V2H repository tooling and scripts

Load this first in the PX4/NuttX RZ/V2H repository (signals: `rzv2h.svd`,
`platforms/nuttx/Debug/`, `boards/renesas/rdk-rzv2h*`). Every step below has a
script in `platforms/nuttx/Debug/` (`$D`); use them instead of composing
JLinkExe / JLinkGDBServer command lines by hand. Paths are relative to the
repository root.

**Authorization.** This repository's `AGENTS.md` grants standing board
authorization for the local RDK board. The RZ/V2H references below assume that
grant; if it is absent or narrower, fall back to the main skill's default of
asking before each reset, load, run-control action or target write.

## RZ/V2H rules

- **Never connect to the CM33** while CR8 images matter: SEGGER's RZ/V2H
  support resets and re-initialises the SoC on every CM33 connect (attach is
  unsupported). The scripts refuse `cm33`.
- **Not armed.** A CR8-0 halt stops the flight stack and its PWM updates; on
  dual-CR8 PX4 it also starves the CR8-1 output lease (50 ms), and a CR8-1
  halt stops the IO health CR8-0 relies on. Never attach while armed or with
  propellers on.
- The guarded scripts set `InhibitConnectRetries` / `-noreset -noir` and exit
  3 (bridge) or 5 (oneshot) when the J-Link log still shows
  `Resetting via Reset pin|cold reset sequence|DBGEN is not asserted`
  (reset-on-failed-connect observed on CR8-0 with JLinkExe V8.94).

## What do you want? → command

`D=platforms/nuttx/Debug`, run from the repository root. Each script's
`--help` or header documents options and exit codes.

| Goal | Command | Touches board |
|---|---|---|
| Host preflight (`$D/jlink-debug-preflight.py`): probe, owners, ports, ELF/core/RTT | `$D/jlink-debug-preflight.py [elf...]` | no |
| Probe serial into the env | `export JLINK_SERIAL=$($D/jlink-debug-preflight.py --print-serial)` | no |
| RTT bridge on a running core (`$D/nuttx-rtt-bridge.sh`) | `$D/nuttx-rtt-bridge.sh start cr8_0 <elf>` → `$D/nsh_console_exec.py --marker 'ps' 'free'` → `$D/nuttx-rtt-bridge.sh stop` | attach; CR8 RTT can use stop mode |
| NSH client over SCI4 UART | `$D/nsh_console_exec.py --serial /dev/ttyUSB0 'ps'` | no probe |
| Read-only GDB snapshot (`$D/jlink-gdb-oneshot.py`) | `$D/jlink-gdb-oneshot.py cr8_0 <elf> --attempts 1 -ex 'bt' -ex 'p g_x'` (or `-x file.gdb`) | halts 1-3 s |
| Load one CR8 image | `$D/rzv2h-ipc/rzv2h-load-one-core.sh cr8_0 <elf>` | RAM load + run |
| Load a dual-CR8 pair | `$D/rzv2h-ipc/rzv2h-ipc-demo-load-both-auto.sh <cr8_0.elf> <cr8_1.elf>` | loads CR8-0 then CR8-1 |
| IPC end-to-end autotest | `$D/rzv2h-ipc/rzv2h-ipc-demo-autotest.sh <cr8_0-rtt.elf> <cr8_1-rtt.elf>` | loads both, RTT only |
| SVD register decoder | `$D/svd_register_tool.py --svd rzv2h.svd addr 0x12801c1c` / `decode R.REG 0x..` | no |
| VS Code stepping (`.vscode/launch.json`) | `IPC RZV2H — load BOTH, attach CR8-x`; its preLaunchTask reloads both cores and its server omits `-noreset` | loads + halts |

All probe-touching commands need `JLINK_SERIAL`. Other env: `JLINK_SPEED`
(auto), `GDB_PORT` (50000), `RTT_PORT` (19021).

## RZ/V2H workflow details

- **NSH over RTT.** Start the bridge with the ELF so it reads `_SEGGER_RTT`
  (PX4 CR8-0 is `0x081a2400`, not the NuttX `0x081a0000` alias default). Use
  `--marker` on PX4 or any image whose tasks log while the shell idles; plain
  prompt mode times out there. On images without `CONFIG_SCHED_WAITPID` (the
  NuttX IPC demos) builtins print after the prompt: wait with
  `--until 'REGEX'`.
- **GDB read.** `jlink-gdb-oneshot.py` starts the server with
  `-noreset -noir -singlerun`, detaches, and refuses mutation by default. Pass
  `--attempts 1`. Use `--allow-mutation` only for task-required operations;
  keep read-only mode for read requests.
- **Load.** Single-core PX4 bring-up: `rzv2h-load-one-core.sh cr8_0`. Dual
  CR8: always CR8-0 then CR8-1 (the pair script does this). The loaders
  RAM-load, start at `__start` with CPSR `0x1d3` and perform a bounded PC
  sanity check, without `monitor reset`. A verify FAIL that mentions a reset
  means peer images are suspect too.
- Helper messages asking for renewed approval are satisfied by the project
  grant when it covers the action.

## IPC shell-script routes

Scripts live in `platforms/nuttx/Debug/rzv2h-ipc/`. Read a script's header or
help before running it; a filename containing `reset` or `--no-connect` does
not establish its effects.

| Script (`rzv2h-ipc-demo-*` unless noted) | When to use it |
|---|---|
| `build-and-load.sh` | Build then load; `--build-only` skips the board. Defaults to SCI4 CR8-0 plus RTT CR8-1; set `CR8_0_CONFIG=rdk-rzv2h:ipcc-raw-cr8_0` for an RTT initiator. |
| `autotest.sh` | Reload exact RTT images and require 100 byte-exact echoes plus CR8-1's independent report. Use a fresh `LOG_DIR`. |
| `run.sh` | Load/verify both images and open SCI4 plus CR8-1 RTT consoles; `--build` builds first. `--no-connect` still loads both and starts the bridge; it only skips the console client. |
| `load-both-auto.sh` | Load explicit ELF paths in CR8-0/CR8-1 order and verify both PCs. |
| `rzv2h-load-one-core.sh` (no `demo-` prefix) | Load and verify one selected CR8 image. |
| `load-both-manual.sh` | Use `guide`, `load`, `verify`, `reset <0\|1> <elf>`, `rtt <exact-cr8_1-elf>` or `sci`. `reset` reloads/restarts that image without a SoC reset. |
| `type-cr8_0-sci4.sh` | Interactive SCI4 terminal; bounded scripted send uses `<port> -- <command...>`. Requires the SCI4 image and working UART wiring. |
| `load-both.sh` | Compatibility entry that delegates to the guarded auto loader. |
| `jlink-lib.sh` | Shared implementation, sourced by wrappers. Inspect connection readiness, `stdbuf`, ownership and logs here; do not execute it as a loader. |

For commands and per-core evidence, read
[IPC recipes](rzv2h-nsh-rtt-svd-recipes.md#recipe-6--ipc-autotest-rtt-only-one-probe).

## Exit codes worth acting on

| Tool | Code | Meaning → next step |
|---|---|---|
| `nuttx-rtt-bridge.sh start` | 1 | probe busy / port used / no RTT block → preflight, check the ELF has `_SEGGER_RTT` |
| | 1 + "connect not finished" | no connect result in `CONNECT_TIMEOUT` (90 s) → report; JLinkExe was killed |
| | 3 | bridge stopped on reset/failed connect → inspect logs and recover per the main skill. DBGEN means no running image on that core; it does not itself prove reset. |
| `nsh_console_exec.py` | 1 | no prompt/marker in `--timeout` → core halted, crashed, wrong console, or log spam (try `--marker`) |
| `jlink-gdb-oneshot.py` | 2 | refused command or usage → fix the invocation; use `--allow-mutation` only when the task requires mutation |
| | 3 | no attach within the selected attempt count → preflight owners, power, cable, `usbipd` |
| | 4 | gdb did not detach → the server restores run state on exit; preflight to confirm nothing is left |
| | 5 | reset or DBGEN marker → inspect the log; actual reset invalidates image execution, while DBGEN alone does not prove reset or erased RAM |
| | 6 | detached, but gdb printed errors (unknown symbol/member, unreadable memory; a `-x` file stops at its first error) → the read is incomplete; fix the expression against this ELF |
| loaders | 1 | load or verify failed → read `$D/rzv2h-ipc/logs/load-*.log` |

The shared loader stops on DBGEN/connect/reset markers even if its port opens;
it does not perform an automatic retry. Check every affected core after an
actual reset. Its native output is unbuffered with `stdbuf` so readiness and
failure markers reach the log before GDB starts.
