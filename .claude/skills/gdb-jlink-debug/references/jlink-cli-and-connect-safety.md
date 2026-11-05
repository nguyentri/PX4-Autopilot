# J-Link CLI and connect safety

Load this when a script does not cover the job and you must call JLinkExe or
JLinkGDBServerCLExe directly, or when a J-Link log needs interpreting.
Behavior below was observed with J-Link V8.94 (Linux install
`/opt/SEGGER/JLink/`); recheck a claim when the version banner differs.

## Probe discovery (no probe access)

Read sysfs: a USB device with `idVendor` `1366` under `/sys/bus/usb/devices/`
exposes its `serial`; strip the zero padding, which gives the form both tools
expect. (The RZ/V2H repository's `platforms/nuttx/Debug/jlink-debug-preflight.py`
does this and prints `JLINK_SERIAL=<sn>`.) Do not use these to discover the
probe:

- `JLinkExe -ShowEmuList` → "Unknown command line option". It is not a CLI
  option.
- `JLinkExe -?` / `-help` → prints the DLL version, then exits 1. It does not
  list probes.
- `lsusb` shows the probe but not its serial; sysfs shows both.

## Selecting the probe: the two tools differ

| Tool | Probe selection | Wrong form |
|---|---|---|
| JLinkExe | `-USB <sn>` (or `-SelectEmuBySN <sn>`) | `-select usb=<sn>` exits "Unknown command line option" |
| JLinkGDBServerCLExe | `-select usb=<sn>` | `-USB <sn>` |

## JLinkExe (J-Link Commander)

Valid CLI options (V8.94): `-AutoConnect -CommandFile -CommanderScript
-Device -ExitOnError -If -JLinkScriptFile -JTAGConf -Log -NoGui
-RTTTelnetPort -SelectEmuBySN -SettingsFile -Speed -USB`.

Common command-file lines: `exec <command string>`, `connect`,
`h` (halt), `g` (go), `regs`, `mem32 <addr> <n>`, `savebin <file> <addr>
<n>`, `Sleep <ms>`, `qc`. `rtt start` is **not** a command in V8.94
("Unknown command"). RTT starts on its own once `exec SetRTTAddr` is set
and the session is connected.

Command-file lines run in order. A line that needs a connection, placed
before `connect` (with `-AutoConnect 1`, the connect happens after the
script), fails with "J-Link connection not established yet". Put command
strings that must apply to the connect (`InhibitConnectRetries`) **before**
`connect`, and everything that talks to the core after it.

A safe attach command file (the RTT address shown is the RZ/V2H PX4 CR8-0
example; take yours from the ELF with `nm <elf> | grep _SEGGER_RTT`):

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
-select usb=<sn> -device <jlink-device> -if SWD -speed auto
-LocalhostOnly 1 -singlerun -timeout 15000 -powertarget 0
-noreset -noir -port 50000 -nogui
```

`<jlink-device>` is SEGGER's device name, for example `STM32F429ZI` or
`R9A09G057H44_R8_0` (RZ/V2H CR8-0).

| Option | Why |
|---|---|
| `-noreset` | no reset on connect (still halts) |
| `-noir` | do not initialise CPU registers on connect |
| `-singlerun` | the server exits when GDB disconnects, so nothing is left owning the probe |
| `-LocalhostOnly 1` | no network exposure of the debug port |
| `-powertarget 0` | never drive target power from the probe |

Readiness: a loader should wait until its server owns a LISTEN socket and
prints "Waiting for GDB connection" before GDB starts; run the server under
`stdbuf -oL` to expose native output promptly. Never test-connect a
`-singlerun` port: the test connection ends the server. Take read snapshots
with one GDB attempt (in the RZ/V2H repository,
`jlink-gdb-oneshot.py --attempts 1`). If the handshake fails, assess its logs
and ownership before another invocation; use the main skill's recovery
sequence.

The server cannot take command strings before it connects, so
`InhibitConnectRetries` cannot be set through it. The only pre-connect hook
is `-jlinkscriptfile`, which may replace the device's own connect script;
avoid it unless you own that script. Server-based tooling can therefore only
detect a reset after the fact: scan the log and fail loudly.

## Why a connect can reset a running board

Example sequence seen on RZ/V2H CR8-0 (JLinkExe V8.94, 2026-10-13) while
attaching to a running image:

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
| `DBGEN is not asserted` | no running image on that core; DBGEN alone does not prove reset. Loaders should stop on this marker. |
| `Connect failed`, `Cannot connect`, `Could not connect` | the attach failed. Inspect the log and host state before a separate recovery attempt. |
| `Enabling CR8 clocks...` then `InitTarget() returned with error code -1` (~60 s later) | RZ/V2H: the J-Link R8 script found the core stopped and tried to start it; same meaning as DBGEN |

JLinkExe opens the RTT telnet port *before* its `connect` has a result
(board-observed, V8.94): an open port proves nothing. Judge the connect only
after "Script processing completed" appears in the log. JLinkExe ignores
SIGTERM while InitTarget runs, so stop it by process group and escalate to
SIGKILL. (The RZ/V2H `nuttx-rtt-bridge.sh` does both.)

## Cores whose connect always resets

Some devices perform a device-specific reset on every connect of a given core.
Example: on RZ/V2H, SEGGER documents that a CM33 connect toggles the reset pin
and runs the full init, and that attach is not supported. Treat any such
session as a full SoC reset: the other cores' images die. No authorization
makes an unsupported attach safe; use an alternate boot/observation route
rather than bypassing a helper's refusal.

## Sources

- J-Link command strings, incl. InhibitConnectRetries: <https://kb.segger.com/J-Link_Command_Strings>
- Example device page, RZ/V2H (R8 warm reset, CM33 reset/attach): <https://kb.segger.com/Renesas_RZ/V2H>
- GDB server options (`-noreset`, `-noir`, `-halt`, `-ir`, `-singlerun`): <https://kb.segger.com/J-Link_GDB_Server>
- Reset-pin fallback on failed connect: <https://forum.segger.com/thread/9831-jlink-intermittently-resetting-device-via-reset-pin>
- Local release notes: `/opt/SEGGER/JLink/Doc/ReleaseNotes/ReleaseNotes.html` (V7.92k entry)
