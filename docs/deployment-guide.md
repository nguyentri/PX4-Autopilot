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

The generated RZ/V2H debug profile is a read-only attach. Use the exact ELF
for the profile and the user-provided probe serial. The profile may halt the
core; reset, load, and continue require explicit authorization. Stop PWMOut
and confirm inactive outputs before halting a running actuator image because
software timeouts do not run while the core is stopped.

The generated profile is in `.vscode/launch.json` after a target build. The
RZ/V2H configuration uses `request: "attach"` and `monitor halt`; it does not
include reset, load, or continue commands.

For a bounded command-line backtrace, bind the probe serial explicitly:

```bash
JLINK_SERIAL=<probe-serial> \
  cmake --build build/renesas_rdk-rzv2h_simple \
  --target jlink_gdb_backtrace
```

The build does not provide a raw-binary flash target. One J-Link probe has one
owner at a time; stop the RTT bridge before a GDB session.

## 5. Serial Console (UART Debug)

The integrated RZ/V2H PX4 images use RTT for text diagnostics. Standalone
NuttX shell profiles may expose SCI4; payload serial roles are owned by the
selected board profile. Use the board source and resolved configuration for
the current port assignment rather than treating a console route as a
payload validation result.

## 6. Real-Time Transfer (RTT) Console

`JLinkGDBServer` does not bridge RTT on the CR8 cores. Use JLinkExe through the
repository bridge, which attaches without reset or halt and serves RTT channel
0 on `127.0.0.1:19021`:

```bash
JLINK_SERIAL=<probe-serial> \
  platforms/nuttx/Debug/nuttx-rtt-bridge.sh start cr8_0 <elf>
platforms/nuttx/Debug/nsh_console_exec.py 'uname -a' 'free' 'dmesg'
platforms/nuttx/Debug/nuttx-rtt-bridge.sh stop
```

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

To inspect an SVD register definition on the host:

```bash
platforms/nuttx/Debug/svd_register_tool.py --svd rzv2h.svd info R_SCI4
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
