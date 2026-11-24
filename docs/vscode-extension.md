# Px4-DB Extension Guide

The native VS Code extension in `Tools/vscode_extension/px4-db/` delegates discovery, checks, builds, RAM loading and configuration resolution to `Tools/firmware-workspace.py`. Existing CLI entry points and manually maintained `.vscode/launch.json` remain available.

The companion ground station for running firmware, `Tools/vscode_extension/px4-gcs/` (MAVLink over serial or UDP: telemetry, parameters, guarded control, NSH console, logs and session report), is described in the [Px4-GCS guide](vscode-gcs-extension.md). Both extensions install side by side.

## Installation and host

From the repository root, run `./Tools/vscode_extension/px4-db/build.sh`. The script installs locked dependencies with `npm ci` when `node_modules` is absent, then typechecks, builds and packages `Tools/vscode_extension/px4-db/px4-db-<version>.vsix` using the version in `package.json`. It runs the tests against that package and also works from another directory. Install the resulting local VSIX with VS Code. The VSIX contains the extension, profiles, themes and schemas; the backend stays in the compatible repository checkout. Marketplace publication is separate.

The extension runs on the workspace extension host. Linux and Remote WSL are the intended initial hosts; Python, compiler, J-Link, GDB and USB-forwarded probes must be visible there. Native Windows and macOS hardware workflows have not been validated. Use the current usbipd-win instructions when forwarding a Windows USB probe into WSL; Doctor enumerates SEGGER USB devices through sysfs without connecting to a core.

Cortex-Debug (`marus25.cortex-debug`) must be installed on the same host for managed debugging. Host resolution checks were compared with the locally installed Cortex-Debug 1.13.0-pre8 attribute schema; a real adapter session remains a hardware acceptance gate.

Restricted Mode displays static guidance and schema information. It runs no repository code, tasks, console/debug operation or workspace-file write. Trust is checked again at execution boundaries.

## Select and check readiness

When several eligible repositories are open, select the owning workspace folder. Settings, saved selections, receipts, paths and task execution are scoped to that folder; an unrelated first folder is never the implicit target.

Select Firmware Profile offers all discovered PX4 targets, standalone NuttX configs for RZ/V2H and RA8P1, and fixed multicore groups. Select a physical J-Link separately from board, SoC and core. Group debug operations use a selected concrete member core. Catalog discovery uses the current checkout rather than a copied target list.

Firmware Setup is the primary surface for saved RDK dual-CR8 groups. Selection & Profiles and Actions remain available for single-core and build-only selections. Readiness & Doctor reports compiler/build tools, Python packages, submodules, GDB, J-Link server and USB probes with remediation. Missing target tools do not prevent a build-only selection. No probe is attached or reset by discovery/Doctor.

Firmware shortcuts use a `Ctrl+Alt+K` chord followed by an action letter: B build,
C clean rebuild, D Doctor, P profile, R refresh, L load and A attach.
They require an initialized, trusted firmware workspace and are inactive in text
inputs and terminals. L/A are for single-core profiles; saved setups use their
explicit per-core debug actions and Load Both. Bare Alt+R remains available
for VS Code's normal search behavior.

## Build and artifacts

Build uses the saved clean/incremental mode. Clean Rebuild overrides one invocation without rewriting the saved selection. Existing scripts retain target-switch cleanup protections. Root `make renesas_*`, root `build.sh`, standalone builders, dual helpers and editor builds share the physical NuttX tree lock. Inheritance requires a live lock descriptor and matching process generation; an environment token alone cannot bypass it.

Build Target, Clean Rebuild and per-core builds do not start J-Link, load firmware or attach a debugger. Choosing **Build Target** from a missing-receipt Load or Attach prompt completes only the build; choose the target action again afterwards. **Build & Load** and **Load and Debug** remain explicit combined actions when their required images are ready.

For standalone NuttX targets, Build Target reuses the tree only when its configuration marker, saved defconfig and Make.defs match the selected board/config. If a PX4 build or CMake configuration replaced those files, it reconfigures automatically before building. Repeated builds of an intact configuration remain incremental.

Group members build sequentially. Each output is staged before the next member can overwrite the shared NuttX output; the group receipt is committed only after all members succeed. A cancelled/failed group never publishes a complete receipt. Build progress streams during execution and cancellation terminates/reaps the owned child group.

Artifacts & Receipts and target commands share a per-selection committed receipt binding, restored from per-folder workspace state. Selecting another profile cannot silently reuse an incompatible receipt. Backend checks compare board, core, family, target/config, group and selection ID, then validate every artifact size/hash and complete core membership. Group receipts also bind the authoritative member/operation definition digest; older group receipts without it require a rebuild. Build compatibility and a successful receipt do not qualify an image pair for hardware operation.

**Artifacts & Receipts** shows each captured ELF filename with its full absolute path beside it. **Firmware Setup** shows the captured ELF filename on each core row and its full path on the **R8-0 ELF** / **R8-1 ELF** row. These are the immutable files used for target operations; original sources and receipt details remain in the tooltips.

## Saved Firmware Setup

Select one of the three RDK-RZ/V2H CR8 groups, then open **Firmware Setup** (the former Dual-Core Loader view keeps its existing layout ID). Use **Save As** to keep named image variants such as “IPC known working” and “IPC driver changes”; **Setup** switches between those variants or opens the complete target catalog. Names are local labels: fixed members, recipes and backend selection IDs remain authoritative. Arbitrary new core combinations are not supported.

Each variant retains independent sources, exact captured bytes/receipts, pending request, history and per-core UART preferences. **Rename** changes only its label. Save As waits for preparation to finish and cannot clone a pending request. Stop owned sessions before changing the setup, profile, probe, core or build mode. The fixed R8-0 and R8-1 rows act on the clicked core without changing the legacy global core selection.

1. Choose **Browse ELF**, **Choose Build Folder**, or **Use Build Receipt** for each row. Folder selection lists ELF-magic candidates, including suffixless `nuttx`, and always asks for the exact file. Scans are cancellable and stop with an explanation if the folder exceeds 10,000 entries; choose a narrower folder. Folder symlinks are excluded; Browse ELF can explicitly select their final file target.
2. For a loose image, confirm its declared core and selected target/config. The first image is captured and checked immediately, before choosing or building the other core. Its provisional receipt preserves the bytes even if the shared NuttX output is overwritten. **Build All** delegates the existing sequential group builder and captures its exact returned receipt. **Build R8-0/R8-1** builds only that fixed member and carries the peer from its immutable capture, so the shared `nuttx` output cannot overwrite the peer. A first per-core build may leave a partial, unloadable setup.
3. Use **Validate Images** to check captured hashes, startup compatibility and original-source changes without hardware access. A changed/deleted original requires **Keep Captured** or **Import Updated**. Keeping the snapshot leaves an “Original source outdated” notice; a subsequent change needs another choice. A changed captured image or receipt cannot be acknowledged and requires new preparation.
4. Select the physical J-Link, then **Load Both to RAM**. This action uses the pinned complete pair and never builds implicitly. **Recover Both** explicitly reloads the pair after a failed/interrupted operation has been diagnosed. Progress reports the actual R8-0/R8-1 load and verify steps; each operation retains separate logs.
5. **Build & Load** explicitly builds and captures a new pair, then loads only that pair. It holds no probe lease during building. Failed/cancelled builds never load a previous pair; once preparation is pending, use its exact **Resume Preparation** before loading. **Load Both to RAM** never builds implicitly.
6. Choose **Debug R8-0** or **Debug R8-1**. These actions require verified load history matching both image hashes and the current group definition. A new receipt containing identical bytes can reuse that history. Switching cores stops the exact owned debugger first; only one managed session uses the probe.

**Last load verified** describes recorded history, not live execution. A new debug attach halts the chosen core. The PX4 `dualcr8` + `io-cr8_1_default` group remains a build-clean software candidate without an admitted actuator pair.

Preparation persists the exact pending request before starting the backend. After an interruption or a failed workspace-state write, **Resume Preparation** uses that request ID and completed captures; it never searches for the newest receipt. Incomplete copies remain unready. Successful assignments survive extension reload and are scoped by workspace folder and saved setup. Profile/probe/image mutations are blocked during target transitions. Refresh never replaces an explicitly captured pair with a newer build.

The Pair row uses a static pause icon for idle pending preparation. Its spinner
indicates live image preparation, a firmware workflow, or a target transition.

An exact-request resume retains its recorded ELF metadata when optional symbol tools become available or disappear. Start a new preparation to refresh that metadata. Validation and history updates preserve newer image choices, and target actions wait until pending image-selection saves finish.

Existing builders still write receipt v1. Imports write v2 with nullable Git/compiler origin and per-image evidence: `developer-declared`, `receipt-reported`, or `unknown`. Receipt metadata is a report, not independent build attestation. SHA-256, address admission and the retained ARM-state `__start` startup checks establish separate facts; local TCM compatibility cannot establish the intended core or firmware role. Import requires Python/jsonschema and `arm-none-eabi-readelf`, independently of compiler/build/probe readiness. Update the VSIX and checkout together if the view reports an incompatible backend capability.

Startup admission rejects explicit Cortex-M/M-profile or non-ARM ISA attributes even if mapping symbols were stripped. Valid ARM entry code may contain Thumb helper functions; Thumb support elsewhere in an image does not itself make its startup incompatible.

## Load and recover

Managed loading is volatile RAM loading on admitted RZ/V2H CR8 routes. Persistent flash is unsupported. RA8P1/RA8E1 managed loading remains blocked pending adapter qualification; RZ/V2H CM33 direct connection remains prohibited because it can reset the SoC. Existing manual tooling retains its documented restrictions.

Load resolves exact immutable private ELF copies, runs the canonical checker with exact device/hash, then invokes the existing guarded single-core or paired loader. Pair order remains owned by the existing loader. A missing checker, malformed ELF, wrong core/range/hash, incomplete group or incompatible receipt fails before a target command.

A private user runtime directory holds a durable journal for each physical probe/core. A started/interrupted or failed operation blocks ordinary retry and attach. Diagnose the failure, then choose Recover Target Load explicitly; recovery re-admits the exact images before loading. A failed connection can invalidate sibling RAM images too. Do not erase a journal to bypass the gate.

Load and Debug waits for the exact operation's successful verified load before attaching. Failed, blocked, cancelled and indeterminate outcomes cannot advance to debug.

## Consoles and Cortex-Debug

The RTT Monitor (bottom panel) is the console. **Trace in RTT Monitor** (`px4Nuttx.setup.startRtt`, also on each **Console R8-0/R8-1** row) requires a validated pair, a selected probe and no extension debug session, then chooses a trace plan from each core's console transport:

- Both cores RTT, `px4Nuttx.rtt.mode` = `dual` (default): `console --action start --dual`. The backend runs `platforms/nuttx/Debug/rzv2h-dual-rtt-bridge.py`, one J-Link session that reads both control blocks over the AXI-AP and serves CR8-0 on `127.0.0.1:19021` and CR8-1 on `127.0.0.1:19031`; the result's `data.endpoints` maps each core to its port. The monitor shows split panes, input goes only to the addressed core, and builds run under `nice -n 19` while it runs (`build --low-priority`).
- Both cores RTT, `px4Nuttx.rtt.mode` = `switch`: `console --action start --core <core>` with the JLinkExe bridge (`nuttx-rtt-bridge.sh`); the monitor's core switch restarts it on the other core.
- One RTT core and one UART core: the RTT core as above, plus `python3 -m firmware_workspace.serial_console --device <dev> --tcp <port>` for the UART core (`19041` for CR8-0, `19042` for CR8-1). The device comes from the setup's `consoleDevices`, or a picker over `/dev/serial/by-id` saves it there. The relay holds the serial device lease (exit 4 when another client holds the UART).

**Build, Load & Trace** (`px4Nuttx.setup.buildLoadTrace`) builds both cores, loads the pair, and keeps the resumed trace or starts the plan above. **Stop RTT Bridge** calls `console --action stop`, stops the serial relay and frees the probe; it does not stop a manually started bridge.

Load, Recover and Debug pause the RTT panes around the probe job and resume on the same target when the job succeeded and the setup is unchanged; a debug session resumes the trace when it ends. The serial pane keeps streaming. A failed bridge start is reported with the backend text and a **Recover Both** action and is never retried.

- Serial outside the monitor: any terminal on the board UART (SCI5 at 115200 8N1). Stop the monitor's serial pane first, since the relay holds the device lease.
- RTT outside the monitor: run `platforms/nuttx/Debug/nuttx-rtt-bridge.sh start <core> <elf>` manually and connect a terminal to `127.0.0.1:19021`. Stop it before Load, Recover, Debug or Load Both. A running bridge makes the probe busy; the `PROBE_BUSY` refusal names **Stop RTT Bridge** when the extension's bridge owns the probe.

A probe supervisor holds the reservation for each load/debug lifetime; a composite Load and Debug keeps one reservation across both steps, so another window cannot take the probe in between. **Stop Sessions** stops this extension's debugger session, its RTT bridge and its serial relay, so the probe is free; it never touches another tool's serial terminal or a bridge started manually with `nuttx-rtt-bridge.sh`.

The extension calls the backend `console` CLI for the RTT bridge and `firmware_workspace.serial_console --tcp` for serial panes.

Cortex-Debug configurations are generated in memory with exact core/device, retained immutable symbols, selected probe, configured GDB and RZ/V2H SVD. Attach/reset/restart overrides request halt without an intentional reset/load. These commands can halt firmware, and a failed J-Link connection may still reset hardware; no claim of reset immunity is made. Confirm safe actuator outputs before halting an image. A startup failure marks RAM state uncertain before the lease ends.

A backend server wrapper supervises the actual J-Link GDB server under the same lease, including cleanup when the adapter wrapper dies. Its private arguments are stripped before invoking SEGGER. Existing manual configurations keep their original server behavior.

The extension does not edit `.vscode/launch.json` or its JSONC customizations. The existing CMake-generated `.vscode/launch.generated.json` is a candidate file owned by its generator, not a managed extension launch entry. Specialized health/HIL tools remain manual CLI tools rather than bypassing the managed probe/receipt contract through editor shell tasks.

## Configuration ownership and CLI

Tracked schemas and capabilities live under `Tools/vscode_extension/px4-db/{schemas,profiles}/`. The selection has `schemaVersion`, `id`, `board`, `core`, `build.{family,target|config,mode}`, optional `group`, `load.{recipe}` and `debug.{mode}`. Probe/tool paths belong to folder-scoped `px4Nuttx` settings or saved local state. The backend schema validates syntax; resolution and operation admission validate compatibility.

`.vscode/active-selection.json` is the extension's local projection, written only at a trusted operation/selection boundary. Content-addressed `.vscode/firmware-selection-*.json` freezes operation input so a later selection change cannot retarget an in-progress command. Preserve developer-owned `firmware-workspace.json`; generated projections and build artifacts can be regenerated. Receipts are under `build/workspace-artifacts/<run-id>/`; debug symbols retain a private snapshot there for the session. The runtime directory is private to the current host/user, keyed by probe serial hash; SCI4 uses a separate `uart/` device-identity namespace.

Saved variants live in an adjacent version-2 workspace-state key (`px4Nuttx.folderState.<root>.setups.v2`). Legacy assignments migrate only after their group is confirmed by the catalog. Unknown group data is preserved without becoming executable. The original key remains a derived compatibility projection for older extensions; an old writer cannot erase the canonical variants. If the projection fails, variants remain durable and the UI asks you to retry initialization/Refresh before downgrading. Future or malformed canonical state remains read-only and preserved; do not clear it to bypass the warning. Saved setups are local workspace state, not an exported target catalog.

```bash
python3 Tools/firmware-workspace.py catalog --json
python3 Tools/firmware-workspace.py doctor --json
python3 Tools/firmware-workspace.py doctor --serial <jlink-serial> --json
python3 Tools/firmware-workspace.py import-images --input <request.firmware-import.json> --json
python3 Tools/firmware-workspace.py resolve --selection .vscode/active-selection.json --operation build --json
python3 Tools/firmware-workspace.py build --selection .vscode/active-selection.json --clean --json
python3 Tools/firmware-workspace.py load --selection .vscode/active-selection.json --receipt <receipt.json> --serial <jlink-serial> --json
python3 Tools/firmware-workspace.py debug-config --selection .vscode/active-selection.json --receipt <receipt.json> --core cr8_0 --serial <jlink-serial> --json
python3 Tools/firmware-workspace.py console --selection .vscode/active-selection.json --receipt <receipt.json> --core cr8_0 --serial <jlink-serial> --action start --json
```

Use `load --recover` only after diagnosis to request recovery. `debug-config --gdb <executable>` accepts an explicit tool override. All commands support `--help`; `--serial` is the probe flag. Result fields and exit/status meanings are documented in the [agent guide](../Tools/vscode_extension/px4-db/llms.txt), with offline schemas as the source of truth.

The new view passes `--expect-receipt-id` and `--expect-pair-sha256` to load/debug admission, plus `debug-config --require-loaded`. These options reject mismatched prepared/loaded identities. Legacy calls omitting them retain their defaults. `doctor --serial` reads the existing per-probe journal without creating a runtime directory or connecting to hardware. `import-images` accepts the offline import schema, validates the embedded selection through the existing resolver, and writes private snapshots under `build/workspace-artifacts/import-<requestId>/`.

## Verification boundaries

Run every `test/firmware-workspace-*-test.py` script directly (their hyphenated names are not discovered by default unittest patterns), then extension typecheck/build/behavioral tests and local packaging. The importer tests use real binutils with small ELF fixtures; controller tests cover persistence, source choices, pinned identity and trust. Host tests also cover saved-state migration/rollback, exact per-core adoption, build/load guards, PTY SCI4 input/output, kernel-lock aliases, child/supervisor cancellation and recovery with temporary fixtures. Run `python3 test/firmware-workspace-serial-console-test.py` for the backend console CLI gate. Existing J-Link host suites use fake servers rather than a board.

Real workbench keyboard/focus, narrow-sidebar/zoom, Restricted Mode integration and adapter teardown still need a native Extension Development Host. Representative single/pair RAM loading, manual-bridge PROBE_BUSY refusal, failed-connect recovery and safe outputs need named on-target transcripts. Host checks and a packaged VSIX do not establish those passes or flight qualification.
