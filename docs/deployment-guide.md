# Deployment Guide: Build, Flash, Debug

**Scope:** Build and target-operation procedures for the RDK-RZ/V2H PX4 and
NuttX port.

The documented target routes are volatile RAM loading and read-only debug
attachment. Execution still requires the permissions stated below. A persistent
flash route and cold-boot deployment sequence require a
separately verified boot-consumer, address, recovery, and hardware contract.

## 1. Build Tools & Environment Setup

From the repository root, source the setup script before building:

```bash
source ./build_setup.sh
```

The script checks the host dependencies, initializes submodules, and removes
e2studio `CMAKE_*` variables that can break the compiler probe. The build
scripts are the owners of configuration, cleanup, and stale-architecture-link
handling; do not replace them with a hand-run `tools/configure.sh` plus `make`
sequence.

`refs/` is local, gitignored reference material. It is not required for every
host build; use [reference-source-map.md](./renesas/reference-source-map.md)
when a driver audit needs it.

## 2. Build Targets

Discover the current PX4 targets with `./build.sh --list` and the NuttX
profiles with `platforms/nuttx/NuttX/build.sh --list`. Build RZ/V2H targets
sequentially because their shared NuttX build tree is regenerated between
profiles.

### NuttX-only builds

```bash
platforms/nuttx/NuttX/build.sh --list
platforms/nuttx/NuttX/build.sh nsh-rtt
platforms/nuttx/NuttX/build.sh --no-clean nsh-rtt
```

The resulting NuttX ELF is under
`platforms/nuttx/NuttX/nuttx/nuttx`; the script also owns the associated binary
and map outputs.

### PX4 builds

```bash
./build.sh renesas_rdk-rzv2h_default
./build.sh --no-clean renesas_rdk-rzv2h_default
```

Use `--no-clean` only while iterating on the same profile. The simple bench,
drone extension, SIH, and DShot profiles select their own board manifest and
NuttX configuration; the board source and [system architecture](./system-architecture.md)
describe their boundaries. The retired core-only material is historical and
has no deployment target.

Build artifacts are written below `build/<target>/`. An ELF or binary artifact
is not a flashing contract.

## 3. Load Routes

The supported target route is a volatile RAM load over J-Link/GDB. It does not
survive power loss. For the NuttX IPC HIL route, the configured GDB script is:

```bash
gdb-multiarch -q -batch <elf> \
  -x platforms/nuttx/Debug/rzv2h-ipc/rzv2h-ipc-hil-loadstart.gdb
```

The [IPC HIL guide](./renesas/validation/rzv2h-ipc-hil-test-guide.md) owns the exact
two-core order and the image-specific load contract.

The load script and the VS Code launch configurations can start an image on
a core that was halted while running a previous image. After the load they
set `$pc` to the entry point and `$cpsr = 0x1d3` (SVC mode, ARM state, IRQ,
FIQ and asynchronous aborts masked), so the new image never starts in the
halted image's mode or with its interrupts enabled.

The current `renesas_rdk-rzv2h_dualcr8` image is exact-BOM sensor bring-up
with CR8-0 motor outputs and the legacy bridge disabled. It is not qualified
with `renesas_rdk-rzv2h-io-cr8_1_default`. The older dual-CR8 bridge captures
apply only to their recorded image hashes. Follow the
[active plan](../plans/261021-0230-rzv2h-dualcr8-sensor-demo/plan.md) for the
pending compatible actuator pair; no current two-image deployment command is
provided before that gate closes.

J-Link reset, image load, and target memory writes require explicit user
authorization. No raw `.bin` or xSPI flashing command is approved. The boot
package checker below performs host-only structural validation and does not
change that boundary.

### Host validation of a boot candidate

The opt-in `renesas_rdk-rzv2h_drone` profile can be checked on the host:

```bash
./build.sh renesas_rdk-rzv2h_drone
python3 test/rzv2h-boot-package-test.py
python3 platforms/nuttx/Debug/rzv2h-boot-package.py \
  --elf build/renesas_rdk-rzv2h_drone/renesas_rdk-rzv2h_drone.elf \
  --image build/renesas_rdk-rzv2h_drone/renesas_rdk-rzv2h_drone.bin \
  --layout boards/renesas/rdk-rzv2h/boot-layout.json \
  --output /tmp/rzv2h-boot-candidate
```

The output directory must be new. The checker validates the ARM32 ELF and
native split-image descriptors, bounds, coverage, entry point, and supported
address layout. It performs no target I/O and does not establish loader
ownership, persistent boot, reset re-entry, or cryptographic authenticity.

`image_base` rebases descriptor source addresses and complements; destinations
and payload bytes remain tied to the ELF. The default is the native linker
address. The postbuild SREC address `0x60200000` is a separate loader alias;
the boot owner must resolve the loader's address view before selecting it.
Marker/signature checks verify structure only.

The candidate and hash manifest retain `deployment_enabled: false`. Before
deployment, verify loader ownership, DDR/TCM/clocks, cache maintenance, the
`0x1234FEDC` handoff/reset sequence and recovery. Initialized data must be
copied before entry; native startup clears BSS, while this package does not
initialize retained `.noinit`. These remain separate from host validation.
See the [checker](../platforms/nuttx/Debug/rzv2h-boot-package.py) and
[layout](../boards/renesas/rdk-rzv2h/boot-layout.json) for the executable contract.

## 4. Debug: J-Link + VS Code

The generated RZ/V2H debug profile requests attach without reset/load commands. Use the exact ELF
for the profile and the user-provided probe serial. The profile may halt the
core; reset, load, and continue require explicit authorization. Stop PWMOut
and confirm inactive outputs before halting a running actuator image because
software timeouts do not run while the core is stopped.

The generated candidate debug profile is emitted to `.vscode/launch.generated.json`
after a target build, preserving any existing `.vscode/launch.json` file.
The native PX4/NuttX Firmware Workspace extension (`Tools/vscode_extension/`) and
the shared backend (`Tools/firmware-workspace.py debug-config`) generate
in-memory Cortex-Debug configurations dynamically. The RZ/V2H configuration uses
`request: "attach"` and `monitor halt`; it does not include reset or load
commands in attach mode. A failed J-Link connection can still reset the board and invalidate RAM images; diagnose and use guarded recovery rather than retrying blindly.

For a bounded command-line backtrace, bind the probe serial explicitly:

```bash
JLINK_SERIAL=<probe-serial> \
  cmake --build build/renesas_rdk-rzv2h_simple \
  --target jlink_gdb_backtrace
```

The build does not provide a raw-binary flash target. One J-Link probe has one
owner at a time; stop the RTT bridge before a GDB session.

`./flash.sh <target> [<cr8_1-target>]` wraps the guarded loaders: a CR8-0 or
CR8-1 target goes through `rzv2h-load-one-core.sh`, a CR8-0 + CR8-1 pair
through `rzv2h-ipc-demo-load-both-auto.sh`, and RA8 targets are programmed
from the ELF with JLinkExe, then reset and run. It first shuts down any RTT
console holding the probe (`platforms/nuttx/Debug/rtt-console-stop.sh`: the
managed bridge, other JLinkExe bridges on port 19021 and SEGGER RTT client,
logger and viewer tools) and never restarts it; open RTT manually afterwards. It
auto-detects `JLINK_SERIAL` when one probe is attached and refuses
`renesas_rdk-rzv2h-io-cm33_*`. Loading a pair is mechanical only; it does not
qualify an actuator pair.

`./flash_dual.sh <cr8_0-target> [<cr8_1-target>]` is the dual-core shortcut. It
resolves both names through `./flash.sh --resolve` (a bare config name such as
`demosih` or `pwm` is tried on that core's board first), then runs the same
pair load. With only the CR8-0 target it adds the default CR8-1 partner:

| CR8-0 target | Default CR8-1 partner |
|--------------|-----------------------|
| `renesas_rdk-rzv2h_demo`, `renesas_rdk-rzv2h_demosih` | `renesas_rdk-rzv2h-io-cr8_1_demo` (heartbeat responder) |
| `renesas_rdk-rzv2h_dualcr8` | `renesas_rdk-rzv2h-io-cr8_1_pwm` (supervisor candidate) |

Any other CR8-0 target needs the CR8-1 target named explicitly.
`./flash_dual.sh --list` prints the pairs and whether both ELFs are built. Exit
codes match `./flash.sh`: 0 both cores verified running, 1 load failed, 2 usage
or target refused. A load also fails when J-Link answers a monitor command
with `ERROR:` (for example `CPU is not halted` at `go`, seen on a board that had
not settled after a USB re-attach). It is not retried, and the CR8-1 load is
skipped; reset the board and load again.

`platforms/nuttx/NuttX/flash.sh [<elf> [<cr8_1-elf>]]` does the same for NuttX
samples. With no argument it loads the last build, `nuttx/nuttx`, on the core
its `nuttx/.config` names (RZ/V2H CR8-0/CR8-1, EVK-RA8P1, FPB-RA8E1), and
refuses when `.config` is newer than the ELF. An explicit ELF is mapped by its
entry address (CR8-0 `0x408xxxxx`, CR8-1 `0x418xxxxx`) or file name;
`--core cr8_0|cr8_1|ra8p1|ra8e1` overrides. Two ELFs load as a CR8-0 + CR8-1
pair, e.g. `nuttx/nuttx-ipcc-demo-cr8_0-serial.elf nuttx/nuttx-ipcc-demo-cr8_1.elf`.
Both scripts share `platforms/nuttx/Debug/jlink-flash-ra8.sh` for RA8 flashing.

## 5. Serial Console (UART Debug)

The integrated RZ/V2H PX4 images use RTT for text diagnostics. Standalone
NuttX shell profiles may expose SCI4; payload serial roles are owned by the
selected board profile. Use the board source and resolved configuration for
the current port assignment rather than treating a console route as a
payload validation result.

## 6. Real-Time Transfer (RTT) Console

`JLinkGDBServer` does not bridge RTT on the CR8 cores. Use JLinkExe through the
repository bridge, which serves RTT channel 0 on `127.0.0.1:19021`. Start with
the host-only preflight, which prints the probe serial, current probe owners,
busy ports and the core and `_SEGGER_RTT` address of each ELF:

```bash
platforms/nuttx/Debug/jlink-debug-preflight.py
export JLINK_SERIAL=$(platforms/nuttx/Debug/jlink-debug-preflight.py --print-serial)
platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 <elf>
platforms/nuttx/Debug/nsh_console_exec.py --marker 'uname -a' 'free' 'dmesg'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

The bridge attaches without reset or halt only when the first connect
succeeds. By default the J-Link DLL answers a failed connect with a reset-pin
pulse and a cold reset, which removes the RAM images (observed on CR8-0 with
JLinkExe V8.94). The bridge sets `InhibitConnectRetries = 1` before `connect`
and exits 3 when its log still shows a reset or a failed connect. After exit
3, report that the images are gone; do not retry or reload without approval.
JLinkExe opens the RTT port before its connect has a result, so the bridge
waits for the end of its command file (up to `CONNECT_TIMEOUT`, 90 s: on a
stopped CR8 the J-Link start sequence takes about 60 s to fail). Exit 3 with
"held in reset or was never started" means the core runs no image (DBGEN not
asserted); no reset was logged.

Use `--marker` on PX4 images: their tasks log while the shell is idle, which
hides the NSH prompt that the default mode waits for. Pass the ELF to the
bridge: PX4 CR8-0 images place `_SEGGER_RTT` at a different address than the
NuttX demo default.

For a read-only GDB snapshot of a running core, use the oneshot helper. It
starts the server with `-noreset -noir -singlerun`, refuses commands that
could change the target, always detaches, exits 5 if the server log shows
a reset, and exits 6 if gdb reported errors (unknown symbol or unreadable
memory), because the read is then incomplete. The core halts for 1-3 s
during the read:

```bash
platforms/nuttx/Debug/jlink-gdb-oneshot.py cr8_0 <elf> -ex 'bt' -ex 'info registers pc cpsr'
platforms/nuttx/Debug/jlink-gdb-oneshot.py cr8_1 <cr8_1-elf> \
  -x platforms/nuttx/Debug/rzv2h-ipc/rzv2h-px4-cr8_1-io-health.gdb
```

To load one CR8 image (approval required), use
`platforms/nuttx/Debug/rzv2h-ipc/rzv2h-load-one-core.sh <cr8_0|cr8_1> <elf>`.
Never connect to the CM33: SEGGER's RZ/V2H support resets the SoC on a CM33
connect.

The bridge records the group leader's start time, command file, probe and core
identity. A stale or legacy numeric PID record is retired without signalling
another process. The IPC loaders retain and reap their own server children;
an occupied GDB port is an error that requires releasing its existing owner.
The uploader retries GDB without terminating external J-Link servers.

Discover `_SEGGER_RTT` from the exact loaded ELF:

```bash
arm-none-eabi-nm <elf>
```

Historical addresses are not a substitute for symbol discovery. Keep NSH
commands short because the configured argument limit and RTT input path can
drop long lines.

RTT has two side effects on the target:

- J-Link reaches CR8 RTT only in stop mode. Every RTT poll halts the core
  (about a quarter of wall time with the bridge attached). The NuttX tick
  loses that time; the GTM-based HRT does not. Inter-core timeouts,
  lease expiries and fault counters measured with the bridge attached are
  skewed: CR8-1 keeps running while CR8-0 is halted. Detach the probe for
  timing or link-loss measurements and read counters afterwards. A GDB
  attach halts the core in the same way.
- The rdk-rzv2h PX4 profiles select `CONFIG_SEGGER_RTT_UP_MODE_TRIM`: a full
  up-buffer drops the excess output instead of spinning with interrupts
  masked until a host drains it. Output written while no probe is attached
  is lost once the buffer fills; the NuttX-only configurations keep the
  stock blocking mode.

To inspect an SVD register definition on the host:

```bash
platforms/nuttx/Debug/svd_register_tool.py --svd rzv2h.svd info R_SCI4
```

`rzv2h.svd` is generated from the CR8 view of the FSP 4.2.0 CMSIS headers in
`refs/rz-fsp-4.2.0/` (local only). Regenerate it after an FSP update, or check
that it is current, with:

```bash
./generate-rzv2h-svd.py           # rewrite rzv2h.svd; -v lists header warnings
./generate-rzv2h-svd.py --check   # exit 1 when rzv2h.svd is stale
python3 test/rzv2h-svd-generator-test.py
```

## 7. Storage and Logs

During bring-up, `/fs/params` is volatile TMPFS state and resets on reboot.
The current simple image does not provide a persistent SDHI/ULog route. The
parameter-storage and xSPI ownership decision remains a qualification item;
do not infer persistence from a successful within-boot parameter change.

Read the system ring buffer through RTT:

```text
nsh> dmesg
```

The configured `CONFIG_SYSLOG_BUFFER_SIZE` controls the ring capacity.

## 8. Common Troubleshooting

### Missing `_SEGGER_RTT`

Confirm the symbol in the exact profile ELF, then rebuild that profile through
`./build.sh`; do not substitute an ELF from another target.

### Submodule desynchronization

Inspect the submodule state and reinitialize it through Git before rebuilding:

```bash
git submodule status
git submodule update --init --recursive
./build.sh renesas_rdk-rzv2h_default
```

### J-Link connection timeout

Verify the probe is visible and stop only the J-Link server owned by the
current terminal. Re-run the serial-bound helper after the server exits:

```bash
lsusb | grep Segger
JLINK_SERIAL=<probe-serial> \
  cmake --build build/renesas_rdk-rzv2h_simple \
  --target jlink_gdb_backtrace
```

Do not kill an unowned server or use an unbound probe when multiple targets
are connected.

## 9. Validation Checklist

Before a target or driver is promoted, use the relevant status table and
validation guide. A build-clean result is not on-target evidence. For the
simple bench, the remaining target checks include read-only attach, RTT
diagnostics, raw sensor topics, FIFO/DRDY behavior, and independent PWM
waveform measurement. Keep actuator outputs inactive except during an explicit
finite test and record physical evidence separately from host contract tests.

## Related Docs

- [System Architecture](system-architecture.md) — current core boundaries and
  build relationships.
- [Code Standards](code-standards.md) — coding and contribution rules.
- [NuttX Port Status](renesas/port-status-nuttx.md) — driver evidence by core.
- [PX4 HAL Port Status](renesas/port-status-px4-hal.md) — HAL evidence.
- [Validation route](renesas/README.md) — board-specific validation guides.
