# PX4/NuttX Firmware Workspace Extension Guide

The native VS Code extension in `Tools/vscode_extension/` delegates discovery, checks, builds, RAM loading and configuration resolution to `Tools/firmware-workspace.py`. Existing CLI entry points and manually maintained `.vscode/launch.json` remain available.

## Installation and host

From `Tools/vscode_extension/`, run `npm run typecheck`, `npm run build`, `npm test` and `npm run package` using the installed project dependencies. Install the resulting local VSIX with VS Code. The VSIX contains the extension, profiles and schemas; the backend stays in the compatible repository checkout. Marketplace publication is separate.

The extension runs on the workspace extension host. Linux and Remote WSL are the intended initial hosts; Python, compiler, J-Link, GDB and USB-forwarded probes must be visible there. Native Windows and macOS hardware workflows have not been validated. Use the current usbipd-win instructions when forwarding a Windows USB probe into WSL; Doctor enumerates SEGGER USB devices through sysfs without connecting to a core.

Cortex-Debug (`marus25.cortex-debug`) must be installed on the same host for managed debugging. Host resolution checks were compared with the locally installed Cortex-Debug 1.13.0-pre8 attribute schema; a real adapter session remains a hardware acceptance gate.

Restricted Mode displays static guidance and schema information. It runs no repository code, tasks, console/debug operation or workspace-file write. Trust is checked again at execution boundaries.

## Select and check readiness

When several eligible repositories are open, select the owning workspace folder. Settings, saved selections, receipts, paths and task execution are scoped to that folder; an unrelated first folder is never the implicit target.

Select Firmware Profile offers all discovered PX4 targets, standalone NuttX configs for RZ/V2H and RA8P1, and fixed multicore groups. Select a physical J-Link separately from board, SoC and core. Group console/debug operations use a selected concrete member core. Catalog discovery uses the current checkout rather than a copied target list.

Selection & Profiles shows the current choice. Readiness & Doctor reports compiler/build tools, Python packages, submodules, GDB, J-Link server and USB probes with remediation. Missing target tools do not prevent a build-only selection. No probe is attached or reset by discovery/Doctor.

## Build and artifacts

Build uses the saved clean/incremental mode. Clean Rebuild overrides one invocation without rewriting the saved selection. Existing scripts retain target-switch cleanup protections. Root `make renesas_*`, root `build.sh`, standalone builders, dual helpers and editor builds share the physical NuttX tree lock. Inheritance requires a live lock descriptor and matching process generation; an environment token alone cannot bypass it.

Group members build sequentially. Each output is staged before the next member can overwrite the shared NuttX output; the group receipt is committed only after all members succeed. A cancelled/failed group never publishes a complete receipt. Build progress streams during execution and cancellation terminates/reaps the owned child group.

Artifacts & Receipts and target commands share a per-selection committed receipt binding, restored from per-folder workspace state. Selecting another profile cannot silently reuse an incompatible receipt. Backend checks compare board, core, family, target/config, group and selection ID, then validate every artifact size/hash and complete core membership. Group receipts also bind the authoritative member/operation definition digest; older group receipts without it require a rebuild. Build compatibility and a successful receipt do not qualify an image pair for hardware operation.

## Load and recover

Managed loading is volatile RAM loading on admitted RZ/V2H CR8 routes. Persistent flash is unsupported. RA8P1/RA8E1 managed loading remains blocked pending adapter qualification; RZ/V2H CM33 direct connection remains prohibited because it can reset the SoC. Existing manual tooling retains its documented restrictions.

Load resolves exact immutable private ELF copies, runs the canonical checker with exact device/hash, then invokes the existing guarded single-core or paired loader. Pair order remains owned by the existing loader. A missing checker, malformed ELF, wrong core/range/hash, incomplete group or incompatible receipt fails before a target command.

A private user runtime directory holds a durable journal for each physical probe/core. A started/interrupted or failed operation blocks ordinary retry, console and attach. Diagnose the failure, then choose Recover Target Load explicitly; recovery re-admits the exact images before loading. A failed connection can invalidate sibling RAM images too. Do not erase a journal to bypass the gate.

Load and Debug waits for the exact operation's successful verified load before attaching. Failed, blocked, cancelled and indeterminate outcomes cannot advance to debug.

## Console and Cortex-Debug

Managed console supports RTT on admitted RDK-RZ/V2H CR8 cores. UART/SCI4 selections explain that a managed transport is unavailable; use the existing `nsh_console_exec.py --serial <device>` CLI for UART. The J-Link probe serial and UART device path are different inputs.

A probe supervisor holds the reservation for the console/debug lifetime. Before managed attach, the extension stops its own RTT bridge and waits for acknowledged teardown while retaining that reservation. Another window cannot acquire the probe in the handoff gap. Stop failure retains ownership and reports failure. Shutdown stops only exact owned processes and debug sessions, preserving unrelated manual sessions.

Cortex-Debug configurations are generated in memory with exact core/device, retained immutable symbols, selected probe, configured GDB and RZ/V2H SVD. Attach/reset/restart overrides request halt without an intentional reset/load. These commands can halt firmware, and a failed J-Link connection may still reset hardware; no claim of reset immunity is made. Confirm safe actuator outputs before halting an image. A startup failure marks RAM state uncertain before the lease ends.

A backend server wrapper supervises the actual J-Link GDB server under the same lease, including cleanup when the adapter wrapper dies. Its private arguments are stripped before invoking SEGGER. Existing manual configurations keep their original server behavior.

The extension does not edit `.vscode/launch.json` or its JSONC customizations. The existing CMake-generated `.vscode/launch.generated.json` is a candidate file owned by its generator, not a managed extension launch entry. Specialized health/HIL tools remain manual CLI tools rather than bypassing the managed probe/receipt contract through editor shell tasks.

## Configuration ownership and CLI

Tracked schemas and capabilities live under `Tools/vscode_extension/{schemas,profiles}/`. The selection has `schemaVersion`, `id`, `board`, `core`, `build.{family,target|config,mode}`, optional `group`, `load.{recipe}` and `debug.{mode}`. Probe/tool paths belong to folder-scoped `px4Nuttx` settings or saved local state. The backend schema validates syntax; resolution and operation admission validate compatibility.

`.vscode/active-selection.json` is the extension's local projection, written only at a trusted operation/selection boundary. Content-addressed `.vscode/firmware-selection-*.json` freezes operation input so a later selection change cannot retarget an in-progress command. Preserve developer-owned `firmware-workspace.json`; generated projections and build artifacts can be regenerated. Receipts are under `build/workspace-artifacts/<run-id>/`; debug symbols retain a private snapshot there for the session. The runtime directory is private to the current host/user, keyed by probe serial hash.

```bash
python3 Tools/firmware-workspace.py catalog --json
python3 Tools/firmware-workspace.py doctor --json
python3 Tools/firmware-workspace.py resolve --selection .vscode/active-selection.json --operation build --json
python3 Tools/firmware-workspace.py build --selection .vscode/active-selection.json --clean --json
python3 Tools/firmware-workspace.py load --selection .vscode/active-selection.json --receipt <receipt.json> --serial <jlink-serial> --json
python3 Tools/firmware-workspace.py debug-config --selection .vscode/active-selection.json --receipt <receipt.json> --core cr8_0 --serial <jlink-serial> --json
python3 Tools/firmware-workspace.py console --selection .vscode/active-selection.json --receipt <receipt.json> --core cr8_0 --serial <jlink-serial> --action start --json
```

Use `load --recover` only after diagnosis to request recovery. `debug-config --gdb <executable>` accepts an explicit tool override. All commands support `--help`; `--serial` is the probe flag. Result fields and exit/status meanings are documented in the [agent guide](../Tools/vscode_extension/llms.txt), with offline schemas as the source of truth.

## Verification boundaries

Run the six `test/firmware-workspace-*-test.py` scripts directly (their hyphenated names are not discovered by default unittest patterns), then extension typecheck/build/behavioral tests and local packaging. Host tests cover trust, receipt binding, immutable inputs, CLI arguments, locks, cancellation, recovery and session ownership with temporary fixtures. Existing J-Link host suites use fake servers rather than a board.

Real workbench keyboard/focus, narrow-sidebar/zoom, Restricted Mode integration and adapter teardown still need a native Extension Development Host. Representative single/pair RAM loading, RTT-to-debug handoff, failed-connect recovery and safe outputs need named on-target transcripts. Host checks and a packaged VSIX do not establish those passes or flight qualification.
