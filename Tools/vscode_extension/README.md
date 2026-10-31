# PX4-NuttX: Dashboard

[![License](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE.md)
[![VS Code](https://img.shields.io/badge/VS%20Code-%5E1.85.0-007ACC.svg?logo=visual-studio-code)](package.json)
[![Hardware](https://img.shields.io/badge/Renesas-RZ%2FV2H%20%7C%20RA8P1%20%7C%20RA8E1-orange.svg)](profiles/devices.json)

VS Code extension integrating PX4 Autopilot and NuttX RTOS development for Renesas **RZ/V2H**, **RA8P1**, and **RA8E1** hardware. Provides unified target discovery, host prerequisite diagnostics, guarded volatile RAM loading and Cortex-Debug attach routing. Consoles (RTT, SCI4) are started manually outside the extension.

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
- **Manual Consoles**: The extension starts no console. Firmware Setup shows each core's transport as a read-only row (`Manual · SCI4 115200 8N1` or `Manual · RTT 127.0.0.1:19021`) with the command to open it; see [Consoles are manual](#consoles-are-manual).
- **Firmware Setup Variants**: Manage named setups of fixed RDK-RZ/V2H CR8 groups, allowing independent image preparation, per-core builds, atomic SHA-256 pair validation, and explicit Build & Load workflows.
- **Shared Build Mutex**: Cooperative file locking across VS Code editor tasks, root `./build.sh`, and `make` preventing concurrent modification of the NuttX source tree.

---

## Quick Start

1. **Open Workspace**: Open the repository root in VS Code. Click **Trust Workspace** when prompted.
2. **Run Doctor**: Open the **PX4-NuttX: Dashboard** in the Activity Bar. In the **Readiness & Doctor** view, click **Run Doctor Check** (or press `Ctrl+Alt+K D`).
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
| `Ctrl+Alt+K B` | `px4Nuttx.build` | **Build Active Target** | Incremental build of active selection using shared flock. |
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
4. **Single Probe Ownership**: J-Link probes cannot bridge RTT and GDB simultaneously on CR8 cores. A probe lease guards every load and debug session; a running manual RTT bridge makes the probe busy, and the refusal says to stop it first.

### Consoles are manual

The extension does not open, stop or hand off consoles. Open them yourself:

- **SCI4 (R8-0 in the SCI4 groups)**: any serial terminal (for example μScope or picocom) on the board UART at 115200 8N1. SCI4 does not use the J-Link, so it may stay open during load and debug.
- **RTT**: `platforms/nuttx/Debug/nuttx-rtt-bridge.sh start <cr8_0|cr8_1> <elf>`, then connect a terminal to `127.0.0.1:19021` (μScope can send input). One J-Link owner at a time: run `platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop` before **Load**, **Debug** or **Load Both**, and restart it afterwards.

**Stop Sessions** stops only this extension's debugger session; it never touches a manual console.

---

## AI Agent & Automation Integration

The extension provides structured schemas and machine-readable contracts for AI coding assistants:

- **`llms.txt`**: Curated API overview and CLI reference for coding agents.
- **`llms-full.txt`**: Comprehensive specification covering subcommands, JSON schemas, IPC protocols, and error codes.
- **`schemas/`**: JSON Schema Draft 7 definitions for device capabilities, firmware selections, artifact receipts, operation results, and firmware imports.

---

## License

This extension is licensed under the [BSD-3-Clause License](LICENSE.md).
