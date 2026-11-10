# 1KW-Px4-Nuttx

[![License](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE.md)
[![VS Code](https://img.shields.io/badge/VS%20Code-%5E1.85.0-007ACC.svg?logo=visual-studio-code)](package.json)
[![Branding](https://img.shields.io/badge/Style-OneKiwi%20(%2316163F%20%7C%20%23ED6C00)-orange.svg)](https://onekiwi.com.vn/)
[![Hardware](https://img.shields.io/badge/Renesas-RZ%2FV2H%20%7C%20RA8P1%20%7C%20RA8E1-orange.svg)](profiles/devices.json)

VS Code extension integrating PX4 Autopilot and NuttX RTOS development for Renesas **RZ/V2H**, **RA8P1**, and **RA8E1** hardware with official [OneKiwi](https://onekiwi.com.vn/) design system styling. Provides unified target discovery, host prerequisite diagnostics, guarded volatile RAM loading and Cortex-Debug attach routing. An RTT Monitor panel traces both CR8 consoles (RTT, or a host UART relay for serial-console cores) next to the editor.

---

## OneKiwi Styling & Brand Themes

The extension incorporates the visual styling and brand tokens of [OneKiwi Technology](https://onekiwi.com.vn/):

| Brand Token | Hex / Value | Semantic Role in Extension & Workbench |
|-------------|-------------|----------------------------------------|
| **Deep Navy (Primary)** | `#16163F` | Activity bar, title bar, status bar, and container header backgrounds |
| **OneKiwi Orange (Accent)** | `#ED6C00` | Primary CTAs, active focus borders, activity badges, cursor, progress bars |
| **Deep Indigo (Secondary)** | `#200066` / `#2A3882` | Circuit trace accents, secondary buttons, subtle glow gradients |
| **Success Green** | `#61CE70` | Ready targets, passed doctor prerequisites, verified image pairs |
| **Electric / Sky Blue** | `#6EC1E4` | Subtitle badges, info indicators, tech nodes, active functions |
| **Peach / Soft Warm** | `#FFBC7D` | Section headers, warnings, queued/transitional states |
| **Light Surface** | `#F8F9FF` / `#FBFCFC` | Light theme sidebar, card background, panel surfaces |
| **Card Borders** | `#E8E8E8` / `#222254` | Card dividers, widget borders, tree item separators |

### Bundled Color Themes
The extension contributes two official color themes that can be selected in VS Code via **Preferences: Color Theme** (`Ctrl+K Ctrl+T`):
- **`1KW Dark (OneKiwi)`**: High-contrast, deep navy midnight theme with signature OneKiwi Orange highlights and rich syntax coloring.
- **`1KW Light (OneKiwi)`**: Clean, crisp light theme with Deep Navy headers, `#F8F9FF` surfaces, and `#ED6C00` action accents.

---

## Architecture Overview

```
+-------------------------------------------------------------------------------+
|                       VS Code Workspace Extension Host                        |
|                                                                               |
|  +--------------------+  +--------------------+  +-------------------------+  |
|  | Native Tree Views  |  | Status Bar Item    |  | Cortex-Debug Provider   |  |
|  | - Selection & Profile | Active Setup/Profile  | In-memory configuration |  |
|  | - Readiness/Doctor |  | Target Core & Probe| Owned J-Link wrapper       |  |
|  | - Artifacts/Receipt|  +--------------------+  Halt-only overrides       |  |
|  | - Actions & Target |                                                       |
|  | - Firmware Setup   |                                                       |
|  +---------+----------+                                                       |
|            |                                                                  |
|            v                                                                  |
|  +--------------------+  +--------------------+                               |
|  |  SelectionStore    |  | BackendClient      |                               |
|  |  - Active profile  |  | - Subprocess exec  |                               |
|  |  - Setup variants  |  | - JSON streams     |                               |
|  |  - State cache     |  | - Flocks & Leases  |                               |
|  +---------+----------+  +---------+----------+                               |
+------------|-----------------------|------------------------------------------+
             |                       |
             v                       v
+-------------------------------------------------------------------------------+
|                      Repository Backend Tools & Hardware                      |
|                                                                               |
|  Tools/firmware-workspace.py <-----------------+                              |
|  - catalog, doctor, build, load, debug, console|                              |
|                                                |                              |
|  Target Hardware & Probes:                     |                              |
|  - Renesas RDK-RZ/V2H (CR8-0, CR8-1, CM33)     |                              |
|  - Renesas EVK-RA8P1 (CM85, CM33)              |                              |
|  - Renesas FPB-RA8E1 (CM85)                    |                              |
|  - SEGGER J-Link Debug Probes (SWD/JTAG)       |                              |
+-------------------------------------------------------------------------------+
```

---

## Key Features

- **Profile & Target Discovery**: Interactive QuickPick for complete PX4 autopilot targets, standalone NuttX configurations, and multicore pair groups discovered directly from the workspace.
- **Readiness & Doctor Diagnostics**: Host-only prerequisite checking for ARM GCC toolchain, CMake (>= 3.20), Ninja, Make, Python dependencies (`kconfiglib`, `jsonschema`), NuttX submodule state, and connected SEGGER J-Link probes.
- **Guarded Target Loading**: Safe volatile RAM loading for Renesas RZ/V2H Cortex-R8 cores (`cr8_0` at `0x081A0000`, `cr8_1` at `0x081E0000`) with ELF address allowlist checking and host journal recovery tracking. Direct attach to RZ/V2H CM33 (which triggers SoC cold reset) and unverified flash routes are strictly gated.
- **Cortex-Debug Integration**: Dynamically generates in-memory debug attach configurations with halt-only commands and SVD symbol mappings. Existing user `launch.json` files are never overwritten.
- **Consoles**: **Trace in RTT Monitor** opens the bottom-panel RTT Monitor. Two RTT cores trace side by side from one probe session; a UART-console core shows as a serial pane. **Build, Load & Trace** builds both cores, loads the pair and starts the trace in one action, and **Stop RTT Bridge** frees the probe; see [Consoles](#consoles).
- **Firmware Setup Variants**: Manage named setups of fixed RDK-RZ/V2H CR8 groups, allowing independent image preparation, per-core builds, atomic SHA-256 pair validation, and explicit Build & Load workflows.
- **Shared Build Mutex**: Cooperative file locking across VS Code editor tasks, root `./build.sh`, and `make` preventing concurrent modification of the NuttX source tree.

---

## Quick Start

1. **Open Workspace**: Open the repository root in VS Code. Click **Trust Workspace** when prompted.
2. **Run Doctor**: Open the **1KW-Px4-Nuttx** in the Activity Bar. In the **Readiness & Doctor** view, click **Run Doctor Check** (or press `Ctrl+Alt+K D`).
3. **Select Profile / Setup**: In the **Selection & Profiles** view, click **Target** (or press `Ctrl+Alt+K P`) to choose a PX4 target (e.g. `rdk-rzv2h_default`), NuttX configuration, or multicore group.
4. **Build & Debug**:
   - Press `Ctrl+Alt+K B` to build the active target.
   - Connect your SEGGER J-Link probe to the board.
   - Click **Guarded Load (RAM)** (`Ctrl+Alt+K L`) to stage and flash to RAM.
   - Click **Attach Debugger** (`Ctrl+Alt+K A`) to launch Cortex-Debug.

---

## Native Sidebar Views

The Activity Bar container contributes 5 dedicated tree views:

| View | Purpose | Key Actions |
|------|---------|-------------|
| **Selection & Profiles** | Active target profile, board, execution core, build mode, debug probe, and console transport. | Select Profile (`Ctrl+Alt+K P`), Change Core, Select Probe, Refresh (`Ctrl+Alt+K R`). |
| **Readiness & Doctor** | Prerequisite validation for compilers, build systems, Python packages, submodules, and probes. | Run Doctor (`Ctrl+Alt+K D`), View Remediation Guides. |
| **Artifacts & Receipts** | Inspect committed build receipts, staged ELF binaries, SHA-256 digests, entry points, and RTT addresses. | Refresh Receipts, Build Target (`Ctrl+Alt+K B`). |
| **Actions & Target Control** | Target execution center with availability gating based on capabilities and prerequisites. | Build (`Ctrl+Alt+K B`), Clean Rebuild (`Ctrl+Alt+K C`), Guarded Load (`Ctrl+Alt+K L`), Attach Debug (`Ctrl+Alt+K A`). |
| **Firmware Setup** | Advanced dual-core image setup for RZ/V2H CR8 pairs with variant management and atomic validation. | Select Setup, Save As, Build Core, Build All, Build & Load, Validate Images, Load Both, Recover Both. |

---

## Commands & Keyboard Shortcuts

Press `Ctrl+Alt+K`, release the keys, then press the action letter. Chords are
enabled only in an initialized, trusted firmware workspace, outside text inputs
and terminals. Load and attach chords apply to single-core profiles;
use the explicit Firmware Setup actions for saved dual-core setups.

| Shortcut | Command ID | Title | Description |
|----------|------------|-------|-------------|
| `Ctrl+Alt+K B` | `px4Nuttx.build` | **Build Active Target** | Incremental build of active selection using shared flock; a NuttX config switch reconfigures the shared tree first. |
| `Ctrl+Alt+K C` | `px4Nuttx.cleanRebuild` | **Clean Rebuild Active Target** | Distclean and full rebuild. |
| `Ctrl+Alt+K D` | `px4Nuttx.checkDoctor` | **Check Prerequisites (Doctor)** | Evaluates host toolchain, submodules, and J-Link probes. |
| `Ctrl+Alt+K P` | `px4Nuttx.selectProfile` | **Select Firmware Target / Profile** | QuickPick for PX4 targets, NuttX configs, and multicore groups. |
| `Ctrl+Alt+K R` | `px4Nuttx.refresh` | **Refresh Workspace & Profiles** | Reloads catalog, receipts, and view states. |
| `Ctrl+Alt+K L` | `px4Nuttx.load` | **Guarded Target Load (RAM)** | Loads committed receipt ELF to target volatile RAM. |
| `Ctrl+Alt+K A` | `px4Nuttx.attach` | **Attach Cortex-Debug** | In-memory Cortex-Debug attach without resetting the target. |

---

## Extension Settings

Configure via **Settings** (`Ctrl+,` or `Cmd+,` -> search for `PX4-NuttX`):

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `px4Nuttx.pythonPath` | `string` | `"python3"` | Path to Python 3 interpreter (>=3.9) with `jsonschema` and `kconfiglib` installed. |
| `px4Nuttx.jlinkSerial` | `string` | `""` | Specific SEGGER J-Link probe serial number. If empty, auto-detected probe is used. |
| `px4Nuttx.gdbPath` | `string` | `"gdb-multiarch"` | Path to GDB executable for target debug sessions (`gdb-multiarch` or `arm-none-eabi-gdb`). |

---

## Guarded Loading & Safety Boundaries

When working with Renesas multicore targets (especially RZ/V2H), observe these hardware safety principles:

1. **Volatile RAM Loading Only**: All managed target loads write to SRAM addresses (`0x081A0000` for CR8-0, `0x081E0000` for CR8-1). Flash routes remain unadmitted.
2. **RZ/V2H CM33 Attach Prevention**: Connecting J-Link directly to the RZ/V2H CM33 core triggers an immediate SoC cold reset. Direct attach to CM33 is strictly blocked.
3. **Exit Code 3 (Recovery Protocol)**: If a target load fails or is interrupted, the backend marks the target state as requiring recovery (`exit code 3`). Blind retries are rejected. Use **Recover Target Load** / **Recover Both** to clear recovery state.
4. **Single Probe Ownership**: J-Link probes cannot bridge RTT and GDB simultaneously on CR8 cores. A probe lease guards every load and debug session; a running RTT bridge makes the probe busy, and the refusal says to stop it first.

### Consoles

The **RTT Monitor** (bottom panel, **Show RTT Monitor**) is the console. After a verified **Load Both**, run **Trace in RTT Monitor** (or click a **Console R8-0/R8-1** row), or use **Build, Load & Trace** to do all three steps.

- **Both cores on RTT** (`px4Nuttx.rtt.mode` = `dual`, the default): one backend bridge reads both CR8 RTT control blocks through the system bus (AXI-AP) of one J-Link session and serves CR8-0 on `127.0.0.1:19021` and CR8-1 on `127.0.0.1:19031`. The monitor shows the two cores in split panes, each with its own input line, Clear, Copy and Save Log. No core is halted. Builds started while the dual bridge runs use `nice -n 19`, because host load slows the raw bus reads. When the firmware's RTT up buffer overflows, the pane badge shows `output dropped: N B` (bytes lost since attach).
- **One core at a time** (`px4Nuttx.rtt.mode` = `switch`): the classic JLinkExe bridge traces one core; the R8-0/R8-1 switch in the monitor stops it and starts it on the other core.
- **Serial + RTT split groups**: the RTT core gets an RTT pane and the UART core (for example R8-0 on SCI5) gets a serial pane fed by a host relay on `127.0.0.1:19041` (R8-0) or `19042` (R8-1). The first start asks for the host device (`/dev/serial/by-id/...`) and the setup keeps it. The relay holds the same device lease as other serial clients, so a UART already open in another tool is refused. It does not use the J-Link and keeps streaming through Load, Recover and Debug.
- **Probe hand-off**: **Load**, **Recover** and **Debug** pause the RTT panes, stop the bridge, run, then start the bridge again on the same target. A debug session resumes the trace when it ends. A failed job or a changed setup does not resume. A bridge that fails to start (a failed J-Link connect can reset the board) is never retried; the error offers **Recover Both**.
- **Save Log** writes `logs/rtt/<setup>-<core>-<yymmdd-hhmmss>.log` without a dialog.
- External terminals still work: connect μScope or a telnet client to `127.0.0.1:19021`/`19031` while the monitor is closed (each port takes one client). A manual bridge (`platforms/nuttx/Debug/nuttx-rtt-bridge.sh start <cr8_0|cr8_1> <elf>`) also works; stop it with `nuttx-rtt-bridge.sh stop`, because **Stop RTT Bridge** stops only the bridge the extension started.
- **PX4 demo heartbeat pair (`rzv-px4-demo`)**: Build All builds `renesas_rdk-rzv2h_demo` (CR8-0) and `renesas_rdk-rzv2h-io-cr8_1_demo` (CR8-1); Load Both RAM-loads them. The cores exchange only `rzv2h_heartbeat` frames over raw `/dev/ipcc1`. Check CR8-0 through the MAVLink shell on SCI5 (`/dev/ttyUSB0` at 57600; SCI5 is MAVLink, not NSH, in PX4 images) and CR8-1 through the RTT console, with `rzv2h_heartbeat status` on each. `platforms/nuttx/Debug/rzv2h-ipc/rzv2h-px4-demo-heartbeat-check.sh` runs both checks plus a loss and recovery test that holds CR8-1 halted for 15 s.

**Stop Sessions** stops this extension's debugger session, the RTT bridge and the serial relay the extension started; it never touches a serial terminal of another tool or a manually started bridge.

---

## AI Agent & Automation Integration

The extension provides structured schemas and machine-readable contracts for AI coding assistants:

- **`llms.txt`**: Curated API overview and CLI reference for coding agents.
- **`llms-full.txt`**: Comprehensive specification covering subcommands, JSON schemas, IPC protocols, and error codes.
- **`schemas/`**: JSON Schema Draft 7 definitions for device capabilities, firmware selections, artifact receipts, operation results, and firmware imports.

---

## Build, Install or Update

Run from the repository root. For Remote WSL, use the WSL terminal in the VS Code workspace so installation targets the WSL extension host. The build script type-checks, bundles, packages and tests the extension:

```bash
Tools/vscode_extension/build.sh
code --install-extension Tools/vscode_extension/1kw-px4-nuttx-0.1.0.vsix --force
```

`--force` replaces an installed copy with the same version. Run **Developer: Reload Window** afterwards to load it.

If the VSIX has already been rebuilt, run only the `code --install-extension` command above. You can also open the Extensions view, choose **… → Install from VSIX…**, and select `Tools/vscode_extension/1kw-px4-nuttx-0.1.0.vsix` (or `px4-nuttx-dashboard-0.1.0.vsix`), then reload the window.

---

## License

This extension is licensed under the [BSD-3-Clause License](LICENSE.md).
