# 1KW-Px4-Nuttx

[![License](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE.md)
[![VS Code](https://img.shields.io/badge/VS%20Code-%5E1.85.0-007ACC.svg?logo=visual-studio-code)](package.json)
[![Branding](https://img.shields.io/badge/Style-OneKiwi%20(%2316163F%20%7C%20%23ED6C00)-orange.svg)](https://onekiwi.com.vn/)
[![Hardware](https://img.shields.io/badge/Renesas-RZ%2FV2H%20%7C%20RA8P1%20%7C%20RA8E1-orange.svg)](profiles/devices.json)

VS Code extension integrating PX4 Autopilot and NuttX RTOS development for Renesas **RZ/V2H**, **RA8P1**, and **RA8E1** hardware with official [OneKiwi](https://onekiwi.com.vn/) design system styling. Provides unified target discovery, host prerequisite diagnostics, guarded volatile RAM loading and Cortex-Debug attach routing. Serial UART consoles are opened outside the extension; an RTT console bridge can be started from Firmware Setup for any terminal to connect to.

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
- **Consoles**: The extension opens no terminal. A UART console row is read-only (`Manual · SCI5 115200 8N1`). An RTT console row (`RTT · Start bridge on 127.0.0.1:19021`) starts the guarded RTT bridge for that core, and **Stop RTT Bridge** frees the probe; see [Consoles](#consoles).
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

The extension opens no terminal of its own. Connect your own terminal:

- **Serial (R8-0 in the serial groups)**: any serial terminal (for example μScope or picocom) on the board serial UART (SCI5, P72/P73) at 115200 8N1. The serial console does not use the J-Link, so it may stay open during load and debug.
- **RTT**: after a verified **Load Both**, click the **Console R8-0** or **Console R8-1** row (`RTT · Start bridge on 127.0.0.1:19021`), then connect a terminal to `127.0.0.1:19021` (μScope can send input). The backend bridge holds the probe while it runs, so click **Stop RTT Bridge** before **Load**, **Recover** or **Debug**, and start it again afterwards. One bridge per probe: start R8-1 or R8-0, not both. A manual bridge (`platforms/nuttx/Debug/nuttx-rtt-bridge.sh start <cr8_0|cr8_1> <elf>`) also works; stop it with `nuttx-rtt-bridge.sh stop`, because **Stop RTT Bridge** stops only the bridge the extension started.

**Stop Sessions** stops this extension's debugger session and the RTT bridge the extension started; it never touches a serial console or a manually started bridge.

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
