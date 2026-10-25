# PX4/NuttX Firmware Workspace for Renesas

VS Code extension integrating PX4 Autopilot and NuttX RTOS development for Renesas RZ/V2H, RA8P1, and RA8E1 hardware.

## Features

- **Profile & Target Selection**: Interactive QuickPick for PX4 targets, NuttX sample configurations, and multicore pair groups.
- **Readiness & Doctor**: Host-only prerequisite checking for ARM GCC (>= 9), CMake (>= 3.20), Python (>= 3.9 with kconfiglib and jsonschema), Make, Ninja, GDB, and connected SEGGER J-Link probes.
- **Guarded Target Loading**: Safe volatile RAM loading on RZ/V2H CR8 cores with ELF address allowlist checking and durable per-probe/core recovery journaling. Direct attach to RZ/V2H CM33 (SoC reset) and unadmitted flash routes are prevented.
- **Cortex-Debug Integration**: Generates verified in-memory attach configurations with explicit halt-only override commands and SVD symbol mappings. Existing user `launch.json` configurations are never modified.
- **Console Session Management**: Integration with the SEGGER RTT bridge on admitted CR8 cores, with explicit lifetime controls. UART/SCI4 consoles remain manual.
- **Shared Concurrency & Lock**: Shared build mutex across editor tasks, `./build.sh`, and root `make` preventing concurrent mutation of the NuttX source tree.

## Supported Hardware

- **Renesas RDK-RZ/V2H**: Cortex-R8 Core 0 (flight core), Cortex-R8 Core 1 (IO core), CM33 (build only; direct attach gated).
- **Renesas EVK-RA8P1**: Cortex-M85 / Cortex-M33 (build supported; target loading gated pending ARMv8-M adapter qualification).
- **Renesas FPB-RA8E1**: Cortex-M85 (build supported).

## Requirements

- Python 3.9+ with `jsonschema` and `kconfiglib`
- ARM GNU Toolchain (`arm-none-eabi-gcc` >= 9)
- CMake 3.20+ and Ninja
- SEGGER J-Link Software and Documentation Pack
- Cortex-Debug extension (`marus25.cortex-debug`) for target debugging

## Workflow and scope

Select the repository folder, firmware profile and physical J-Link probe in the native sidebar. PX4 and complete standalone NuttX catalogs are discovered from this checkout. Build and Clean Rebuild produce receipts bound to the selected profile. Group debug and console actions require a concrete member core. Load and Debug attaches only after a verified load; failed operations require diagnosis and explicit Recover Target Load.

Restricted Mode displays static guidance and schemas without running workspace code or writing workspace files. Build/load operations stream progress and support cancellation. The extension runs on the workspace extension host; Linux and Remote WSL paths/tools/probes must exist there. Native Windows/macOS hardware workflows have not been validated.

The local VSIX includes the extension and schemas; it requires a compatible repository checkout containing `Tools/firmware-workspace.py`. See the [workspace guide](../../docs/vscode-extension.md) for CLI examples, state ownership and qualification boundaries. Host regression tests do not qualify hardware routes.
