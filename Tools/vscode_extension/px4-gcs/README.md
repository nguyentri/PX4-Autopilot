# Px4-GCS

A minimal MAVLink ground station for PX4 that runs inside VS Code. It is the
companion of `Px4-DB` (build, load, debug) for the moment the firmware is
running: connect over serial or UDP, watch the vehicle, edit parameters, use the
NSH console and send guarded commands.

## Features

- Quick Connect over serial (listen-only baud probe, shared port lease with
  `Px4-DB`) or UDP; the first autopilot heartbeat pins the vehicle.
- Fly: attitude indicator, altitude, speeds, battery, GPS, mode, status
  messages; guarded Arm, Disarm, Mode and Reboot with modal confirmation and
  the vehicle's acknowledgement. No force path.
- Parameters: metadata, diff against defaults, confirmation for
  safety-relevant families, QGC `.params` import (preview) and export.
- NSH console over MAVLink, behind one warning per connection; every line is
  journaled.
- Inspector (message rates and fields) and Sensor Bench (IMU, mag, baro,
  distance, GPS, NAMED_VALUE).
- Plots and a tile-free trajectory view. The dashboard makes no network
  request.
- Onboard log list and download (gap retry, cancel, free-space check),
  `.tlog` recording, and a self-contained HTML session report.

Recordings and reports contain positions. They go to the extension's global
storage unless `px4Gcs.recording.directory` points elsewhere; keep them out
of repositories.

The full guide is `docs/vscode-gcs-extension.md` in the PX4-Autopilot
repository.

## Requirements

- VS Code 1.85 or newer.
- Python 3.8 or newer with `pymavlink` and `pyserial`:
  `python3 -m pip install pymavlink pyserial`.
- Workspace trust: connecting starts a Python sidecar, so it needs a trusted
  workspace.

## Quick start

1. Install the VSIX: `code --install-extension px4-gcs-0.1.0.vsix`.
2. Open the Px4-GCS view in the activity bar.
3. Run **PX4 GCS: Run Doctor** to check the Python interpreter and modules.

## Settings

| Setting | Default | Notes |
|---------|---------|-------|
| `px4Gcs.pythonPath` | `python3` | User or machine settings only |
| `px4Gcs.transport` | `serial` | `serial` or `udp` |
| `px4Gcs.serial.port` | empty | Empty means auto-detect |
| `px4Gcs.serial.baud` | `57600` | First baud the listen-only probe tries |
| `px4Gcs.serial.baudCandidates` | `[57600, 115200]` | Probe order |
| `px4Gcs.udp.host` | `127.0.0.1` | Bind address; user or machine settings only |
| `px4Gcs.udp.port` | `14550` | |
| `px4Gcs.control.enabled` | `true` | `false` makes the station telemetry-only |
| `px4Gcs.parameters.metadataPath` | empty | PX4 `parameters.json`; user or machine settings only |
| `px4Gcs.recording.directory` | empty | Recordings and reports; user or machine settings only |

## Build

`./build.sh` installs the pinned development dependencies with `npm ci`,
typechecks, bundles, packages `px4-gcs-<version>.vsix` and runs the tests.

## License

BSD-3-Clause, see `LICENSE.md`.
