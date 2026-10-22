# J-Link CLI and connect safety

Load this when a script does not cover the job and you must call JLinkExe or
JLinkGDBServerCLExe directly, or when a J-Link log needs interpreting. Tool
versions seen on this host: J-Link V8.94, `/opt/SEGGER/JLink/`.

## Probe discovery (no probe access)

`platforms/nuttx/Debug/jlink-debug-preflight.py` reads sysfs (USB vendor
`1366`) and prints `JLINK_SERIAL=<sn>` with the zero padding removed, which
is the form both tools expect. Do not use these to discover the probe:

- `JLinkExe -ShowEmuList` → "Unknown command line option". It is not a CLI
  option.
- `JLinkExe -?` / `-help` → prints the DLL version, then exits 1. It does not
  list probes.
- `lsusb` shows the probe but not its serial; preflight shows both.

## Selecting the probe: the two tools differ

| Tool | Probe selection | Wrong form |
|---|---|---|
| JLinkExe | `-USB <sn>` (or `-SelectEmuBySN <sn>`) | `-select usb=<sn>` exits "Unknown command line option" |
| JLinkGDBServerCLExe | `-select usb=<sn>` | `-USB <sn>` |

## JLinkExe (J-Link Commander)

Valid CLI options (V8.94): `-AutoConnect -CommandFile -CommanderScript
-Device -ExitOnError -If -JLinkScriptFile -JTAGConf -Log -NoGui
-RTTTelnetPort -SelectEmuBySN -SettingsFile -Speed -USB`.

Command-file lines used in this tree: `exec <command string>`, `connect`,
`h` (halt), `g` (go), `regs`, `mem32 <addr> <n>`, `savebin <file> <addr>
<n>`, `Sleep <ms>`, `qc`. `rtt start` is **not** a command in V8.94
("Unknown command"). RTT starts on its own once `exec SetRTTAddr` is set
and the session is connected.

Command-file lines run in order. A line that needs a connection, placed
before `connect` (with `-AutoConnect 1`, the connect happens after the
script), fails with "J-Link connection not established yet". Put command
strings that must apply to the connect (`InhibitConnectRetries`) **before**
`connect`, and everything that talks to the core after it.

The safe attach file that `nuttx-rtt-bridge.sh` writes:

```text
exec InhibitConnectRetries = 1
exec SetRTTAddr 0x081a2400
exec SetRTTTelnetPort 19021
connect
```

## JLinkGDBServerCLExe

The server **halts the core and resets it by default on connect** (`-halt`
and `-ir` are defaults). For a read on a running image always pass:

```text
-select usb=<sn> -device R9A09G057H44_R8_0 -if SWD -speed auto
-LocalhostOnly 1 -singlerun -timeout 15000 -powertarget 0
-noreset -noir -port 50000 -nogui
```

| Option | Why |
|---|---|
| `-noreset` | no reset on connect (still halts) |
| `-noir` | do not initialise CPU registers on connect |
| `-singlerun` | the server exits when GDB disconnects, so nothing is left owning the probe |
| `-LocalhostOnly 1` | no network exposure of the debug port |
| `-powertarget 0` | never drive target power from the probe |

Readiness: the shared loaders require their server to own a LISTEN socket
and print "Waiting for GDB connection" before GDB starts. They use `stdbuf`
to expose native output promptly. Never test-connect a `-singlerun` port:
the test connection ends the server. Use `jlink-gdb-oneshot.py --attempts 1`
for read snapshots. If the handshake fails, assess its logs and ownership
before starting another invocation; use the main skill's recovery sequence.

The server cannot take command strings before it connects, so
`InhibitConnectRetries` cannot be set through it. The only pre-connect hook
is `-jlinkscriptfile`, which may replace the device's own connect script.
It is not used here. The server scripts therefore detect a reset after the
fact: they scan the log and fail loudly, but cannot prevent it.

## Why a connect can reset a running board

Sequence seen on RZ/V2H CR8-0 (JLinkExe V8.94, 2026-10-13) while attaching to
a running dualcr8 image:

1. "R8 already up & running. Skipping connect sequence."
2. "Found Cortex-R8 r1p0, 1 code breakpoints, 1 data breakpoints". These IDs
   are wrong; a good read shows r0p3 with 6 code and 4 data breakpoints.
3. "Connect failed. Resetting via Reset pin and trying again."
4. "Perform cold reset sequence!"
5. "Core internal signal DBGEN is not asserted."

The image was gone afterwards. The DLL's default connect-retry strategy is
the reset. `InhibitConnectRetries = 1` (command string since V7.92k) turns it
off for JLinkExe sessions. Board-checked on 2026-10-13 with V8.94: the
bridge log shows `exec InhibitConnectRetries = 1` accepted (no "Unknown
command"), then "R8 already up & running", "Found Cortex-R8 r0p3" and RTT
in stop mode, with no reset. If a later J-Link version ever logs "Unknown
command" for it, report that.

Log markers and what they mean:

| Marker | Meaning |
|---|---|
| `Resetting via Reset pin`, `cold reset sequence` | the DLL reset the device: every core's RAM image is suspect |
| `DBGEN is not asserted` | no running image on that core; DBGEN alone does not prove reset. Shared loaders stop on this marker. |
| `Connect failed`, `Cannot connect`, `Could not connect` | the attach failed. Inspect the log and host state before a separate recovery attempt. |
| `Enabling CR8 clocks...` then `InitTarget() returned with error code -1` (~60 s later) | the J-Link R8 script found the core stopped and tried to start it; same meaning as DBGEN |

JLinkExe opens the RTT telnet port *before* its `connect` has a result
(board-observed, V8.94): an open port proves nothing. Judge the connect only
after "Script processing completed" appears in the log; the bridge does this.
JLinkExe ignores SIGTERM while InitTarget runs, so stop it by process group
and escalate to SIGKILL (the bridge does this too).

## CM33 on RZ/V2H

SEGGER documents that a CM33 connect performs a device-specific reset
(toggles the reset pin and runs the full init) and that attach is not
supported. Treat any CM33 session as a full SoC reset: the CR8 images die.
The supported CR8 helpers refuse CM33. Standing board authorization does not
make attach supported; use an alternate CM33 boot/observation route rather
than bypassing that refusal.

## Sources

- J-Link command strings, incl. InhibitConnectRetries: <https://kb.segger.com/J-Link_Command_Strings>
- RZ/V2H device support (R8 warm reset, CM33 reset/attach): <https://kb.segger.com/Renesas_RZ/V2H>
- GDB server options (`-noreset`, `-noir`, `-halt`, `-ir`, `-singlerun`): <https://kb.segger.com/J-Link_GDB_Server>
- Reset-pin fallback on failed connect: <https://forum.segger.com/thread/9831-jlink-intermittently-resetting-device-via-reset-pin>
- Local release notes: `/opt/SEGGER/JLink/Doc/ReleaseNotes/ReleaseNotes.html` (V7.92k entry)
