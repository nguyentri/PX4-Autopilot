# 1KW-Px4-GCS Extension Guide

`Tools/vscode_extension/1kw-px4-gcs/` is a small MAVLink ground station for
PX4 that runs inside VS Code. It covers what happens once the firmware is
running: connect, watch, edit parameters, use the NSH console and send
guarded commands. Build, load and debug stay in the sibling extension
`1KW-Px4-Nuttx` ([guide](vscode-extension.md)). Both extensions install side
by side and do not share any command, view or setting id.

The extension is not QGroundControl. It has no mission planner, no map tiles,
no joystick, no video and no firmware upload.

## Install and requirements

| Need | Detail |
|------|--------|
| VS Code | 1.85 or newer. Linux and Remote WSL are the tested hosts. |
| Python | 3.8 or newer on the extension host, with `pymavlink` and `pyserial` (`python3 -m pip install pymavlink pyserial`). |
| Workspace trust | Connecting starts a Python sidecar, so the workspace must be trusted. |
| Serial on WSL | Forward the FTDI cable with usbipd-win; the device then appears as `/dev/ttyUSB0`. |

Build: `./Tools/vscode_extension/1kw-px4-gcs/build.sh` runs `npm ci` (pinned
versions), both typechecks, the esbuild bundles, `vsce package` and every
test suite. Output: `Tools/vscode_extension/1kw-px4-gcs/1kw-px4-gcs-<version>.vsix`.
Install it with `code --install-extension <file>.vsix`. The VSIX carries the
bundled host and webview code, the Python sidecar (`python/px4_gcs_bridge/`),
the protocol schema and the media. It carries no sources, tests or bytecode.

Run **PX4 GCS: Run Doctor** first. It reports the interpreter, its version
and whether `pymavlink` and `pyserial` import.

## Connect

- **Quick Connect** (welcome view, connection bar, palette) uses the settings.
  On serial it reuses the last port and baud that worked. Otherwise it picks
  the only candidate port or asks with a QuickPick. It probes the baud list
  **listen-only**, so the probe writes nothing before the first heartbeat and
  cannot disturb an NSH prompt on the same port.
- **Connect...** asks for every choice: serial (port, baud) or UDP
  (bind host, port).
- The sidecar pins the vehicle to the first autopilot heartbeat (component 1):
  its system id and, on UDP, its source address. Frames from other systems are
  dropped and counted in the Vehicle tree as "Ignored traffic". An
  acknowledgement counts only when its command, source and target match.
- **Link watchdog**: no frame for 3 s changes the state to `lost`. Any frame
  counts, including LOG_DATA during a download. The state returns to
  `connected` when frames resume.
- **Serial ownership**: the sidecar takes the same lease as the sibling
  extension's serial console (an `flock` on `<runtime root>/uart/<major>-<minor>.lock`
  plus a metadata file) and opens the device with `exclusive=True`. Whichever
  tool connects second gets `PORT_BUSY` naming the owner. Disconnect, sidecar
  exit and editor shutdown release both.
- Binding UDP to a non-loopback address asks first, because any host that
  reaches it can then send MAVLink to the station.

RDK images: SCI5 (TEL1) carries MAVLink at **57600** on `demo` and **115200**
on `demosih`. The default candidates `[57600, 115200]` cover both.

## Dashboard tabs

Open with **PX4 GCS: Open Dashboard**. Closing or reloading the page keeps
the session: history lives in the extension host and is replayed.

| Tab | Shows |
|-----|-------|
| Fly | Attitude indicator, altitude, speeds, battery, GPS, mode, armed state, status messages, and the guarded Arm, Disarm, Mode and Reboot buttons. |
| Parameters | Full list with search, metadata (description, unit, range, default), a diff against the metadata default, edit, `.params` import and export. |
| Console | NSH over MAVLink `SERIAL_CONTROL` (xterm). See the console exception below. |
| Inspector | Every received message id with rate and last field values; subscribe to one to watch it. |
| Sensors | IMU (HIGHRES_IMU, SCALED_IMU, RAW_IMU), magnetometer, barometer, distance sensor, GPS and the NAMED_VALUE table (for example `ADS_A0..A3`). Visible cards raise the stream rates; the previous interval is restored afterwards. |
| Plots | uPlot strips (attitude, altitude, speeds, battery, local position, named values) over a 30 s, 2 min or 10 min window. History: 10 Hz, 6000 samples per series. |
| Track | Tile-free top view of the trajectory: local NED first, GPS after the first real fix. North up, scale bar, Follow, fit. No map tiles, no network request. |
| Logs | Onboard log list, one download at a time with bytes, percent, rate and Cancel, and the Session Report button. |

The connection bar holds Quick Connect, Disconnect and the **Record** /
**Stop Recording** toggle. The activity bar view **Vehicle** lists link,
identity, mode, armed state, battery, GPS and recording.

## Guarded control

Arm, disarm, mode change, reboot, parameter writes and parameter import are
checked in the extension host. The page can only ask for them.

1. **Refusals without a dialog**: control disabled
   (`px4Gcs.control.enabled = false`); no connected link; last heartbeat older
   than 2 s; reboot while armed or with an unknown armed state; a mode that the
   vehicle's AVAILABLE_MODES does not list.
2. **Modal confirmation** (Cancel is the default). It names the action, system
   and component, transport, armed state, current mode and the consequence.
3. **Second check** after the modal closes, because the vehicle may have
   changed meanwhile.
4. **Acknowledgement**: the result (`ACCEPTED`, `DENIED`, `TEMPORARILY_REJECTED`,
   timeout) is shown with the vehicle's STATUSTEXT that explains it, and is
   written to the session journal.

The buttons have no force path. A DENIED arm is reported, never retried with
force.

### The console exception

The NSH console is an unguarded shell: `commander arm -f` forces arming, and
any command runs at once. It opens behind one warning modal per connection.
Every line sent is written to the session journal and appears in the report.
`px4Gcs.control.enabled = false` also disables console input.

### Operation without an RC transmitter

In the reference setup no RC receiver is attached (`COM_RC_IN_MODE 4`) and
the extension is the only controller. It sends commands and mode changes,
never MANUAL_CONTROL.

- **There is no kill switch.** The ways to stop a vehicle are **Hold**,
  **Land** and **Return**. `commander disarm` in the console is the last
  resort; it is journaled.
- An automatic mode (Takeoff, Mission, Return, Land, Hold) acts as soon as the
  vehicle is armed. The arm dialog says so when the current mode is
  automatic.
- Modes that need sticks (Manual, Stabilized, Acro, Altitude, Position) are
  not usable without RC; the dialog states that the extension sends no stick
  input.
- PX4 disarms by itself 10 s after arming without take-off
  (`COM_DISARM_PRFLT`) and 2 s after landing (`COM_DISARM_LAND`). Both are
  normal.

### Parameter confirmation policy

A parameter edit applies directly unless one of these holds; then a modal
lists every reason:

- no metadata is loaded, the name is not in it, or its type differs from the
  vehicle's type;
- the value is outside the metadata range;
- the parameter needs a reboot to take effect;
- the vehicle is armed or its armed state is unknown;
- the name belongs to a safety family (prefix followed by a digit or `_`):

| Class | Families |
|-------|----------|
| protections | `CBRK COM NAV GF FD BAT RTL MAN` |
| actuators | `CA PWM DSHOT HIL UAVCAN` |
| link and system | `MAV SER SYS` |
| radio | `RC` |
| sensors and estimator | `SENS CAL TC EKF2 LPE ATT` |

The list is a reviewed judgement, not a PX4 classification. Names starting
with `_` (for example `_HASH_CHECK`) are never written. Every write is read
back by name and journaled with old, requested and resulting value. **Import**
(`.params`, QGC format) takes a snapshot first, shows the full preview
(changed, unchanged, unknown, refused) and confirms once. **Export** writes
the QGC format. The "default" column comes from the metadata file. It is the
compile-time default, which can differ from the board's `rc.board_defaults`.

Metadata: `px4Gcs.parameters.metadataPath` or the newest
`build/*/parameters.json` in the workspace.

## Logs, recording and the session report

- **Onboard logs**: Refresh sends LOG_REQUEST_LIST. The tab keeps three
  outcomes apart:
  - the list itself;
  - **"The vehicle reported no logs"**: PX4 stays silent for 3 s while
    heartbeats continue (PX4 does not answer this request when it has no
    logs);
  - the link error, when the link is lost.

  A download asks for the save location and refuses before any
  LOG_REQUEST_DATA when the folder has less free space than the log (both
  byte counts are shown). Missing chunks are re-requested. The file is written
  as `<file>.part` and renamed only when complete. Cancel removes the partial
  file and sends LOG_REQUEST_END. The SHA-256 goes to the journal. The RDK
  images run no logger, so they always report no logs.
- **Recording** (`.tlog`): only when the operator starts it (Record button,
  Vehicle tree, palette). The file is named `px4-gcs-<UTC>.tlog` and holds
  every frame received from and sent to the pinned vehicle, with timestamps.
  It closes on Stop, on disconnect and when the sidecar exits. When a
  recording stops, the extension offers the session report.
- **Session report**: a self-contained HTML file. It has:
  - a summary: session length, vehicle, link, counts of status messages,
    guarded commands and parameter writes, dropped journal entries;
  - extremes: highest altitude above home, fastest ground speed, lowest
    battery charge and voltage;
  - the timeline of connections, modes, arming, commands, parameter writes,
    status texts and console lines;
  - the track as inline SVG.

  The CSP is `default-src 'none'` with inline style only. It has no script and
  no remote reference. Every vehicle-supplied text is escaped.

### Privacy

Recordings and reports hold positions. By default they go to the extension's
global storage, never to the workspace. **Reveal Sessions Folder** opens it.
`px4Gcs.recording.directory` (user or machine scope only) moves them. Keep
them out of the repository. Downloaded logs go only where the save dialog
points.

## Settings

| Setting | Scope | Default | Notes |
|---------|-------|---------|-------|
| `px4Gcs.pythonPath` | machine | `python3` | Interpreter for the sidecar |
| `px4Gcs.transport` | window | `serial` | `serial` or `udp` |
| `px4Gcs.serial.port` | window | empty | Empty: auto-detect |
| `px4Gcs.serial.baud` | window | `57600` | First baud the probe tries |
| `px4Gcs.serial.baudCandidates` | window | `[57600, 115200]` | Probe order |
| `px4Gcs.udp.host` | machine | `127.0.0.1` | Bind address; non-loopback asks first |
| `px4Gcs.udp.port` | window | `14550` | Bind port |
| `px4Gcs.control.enabled` | window | `true` | `false`: telemetry only, no console input |
| `px4Gcs.parameters.metadataPath` | machine | empty | Empty: newest `build/*/parameters.json` |
| `px4Gcs.recording.directory` | machine | empty | Empty: extension global storage |

**Workspace trust**: the manifest declares `untrustedWorkspaces: limited`. In
an untrusted workspace no sidecar starts. The four machine-scoped settings
are read from user or machine settings only, so a checked-out repository
cannot choose the interpreter, a bind address or a write path.

## Sidecar protocol

The host starts `python -m px4_gcs_bridge` from the VSIX and talks to it over
JSON lines on stdin and stdout, at protocol version 1.
`schemas/bridge-protocol.schema.json` is the only contract; the tests check
every sidecar line against it with `ajv`.

- **Commands** (host to sidecar, each with an `id`):
  - session: `hello`, `doctor`, `list_ports`, `connect`, `disconnect`,
    `cancel`;
  - parameters: `param_list`, `param_read`, `param_set`;
  - control: `arm`, `disarm`, `set_mode`, `reboot`;
  - streams: `stream_request`, `stream_release`;
  - console: `shell_open`, `shell_write`, `shell_close`;
  - inspector: `inspector_subscribe`, `inspector_unsubscribe`;
  - logs and recording: `log_list`, `log_download`, `record_start`,
    `record_stop`.
- **Replies**: `ok: true` with data, or `ok: false` with an error code such as
  `PORT_BUSY`, `NO_HEARTBEAT`, `NOT_CONNECTED`, `CANCELLED` or `DENIED`.
  Long commands (parameter download, log download) report progress events
  and can be cancelled.
- **Events**: link state, heartbeat, modes, statustext, telemetry, sensors,
  named values, shell output, inspector, progress and recording.
- **Threads**: one I/O thread owns the link. The stdin reader only queues
  commands, and stdout drains a bounded queue. Stdin EOF, SIGTERM and a
  broken pipe all lead to the same shutdown: disconnect, release the lease,
  close the recording, exit.
- `px4_modes.py` is the only flight-mode table. `hello` returns it, and the
  host only displays it.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Doctor: `pymavlink` missing | Install into the interpreter in `px4Gcs.pythonPath` (machine setting). |
| `PORT_NOT_FOUND`, no `/dev/ttyUSB0` on WSL | `usbipd.exe list` on Windows: the FTDI cable must be attached to WSL, not only "Persisted". |
| `PORT_BUSY` | Another tool holds the port; the message names it. Close the sibling extension's serial pane or the other session. |
| `NO_HEARTBEAT` after the probe | Wrong baud list, the wrong UART, or the image does not run MAVLink on that port. |
| Link flips to `lost` | No frame for 3 s; on WSL also check FTDI overruns caused by usbipd stalls. |
| Mode button greyed | The vehicle's AVAILABLE_MODES does not list it. |
| Arm DENIED | Read the STATUSTEXT in the result; a preflight check failed. No force path by design. |
| Logs: "reported no logs" | Normal on images without a logger. |

## Design notes

- The host owns state and policy (guards, journal, history, report). The
  webview only renders and requests, and renders all vehicle text as text
  nodes. Its CSP names no remote origin.
- The session journal (`src/session/session-journal.ts`) is the only audit
  sink. The report is built from it.
- Stream rates are raised per tab while visible and restored to the
  vehicle's previous interval. A stream PX4 reports as not configured (0)
  or unlimited (negative) is refused and left alone, because sending that
  value back would not restore it.
- Tests run the real sidecar against a Python vehicle peer over real UDP and
  pseudo-terminals. They cover the probe, lease, guards, parameters, console,
  log download with 5 % loss, recording and report escaping.

## Verification boundaries

Host and peer tests do not prove behaviour on a vehicle. RDK evidence on the
`demosih` and `demo` images is recorded under `docs/renesas/evidence/` when
captured. Until then the board criterion of the plan stays open. These are
not proven against a real PX4:

- a log list or download (the RDK images have no logger);
- UDP;
- a denied reboot.

## Backlog

Mission upload and download, a geofence view, joystick/MANUAL_CONTROL,
firmware upload, multiple vehicles, paged history replay (the history reply
is unpaged; with many NAMED_VALUE keys it can reach tens of MB).
