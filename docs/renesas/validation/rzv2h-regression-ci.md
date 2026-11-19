# Run RZ/V2H regression checks in CI

Use the repository-owned [script catalog](../../../Tools/rzv2h-regression-catalog.json)
to choose a stage. The commands below work from the checkout root and require
no campaign directory. The catalog retains existing script locations, including
imported helpers and legacy HIL fragments; listing a tool does not run it.

## Prepare a Linux runner

Initialize both NuttX/apps submodules. Host checks use Python 3, GCC/G++, Bash
and ordinary Linux process/socket tools. The CI-tool snapshot fixtures also
require `rsync`. Install the Python requirements from
[pinned sample requirements](../../../Tools/requirements-rzv2h-samples.txt); the sample
host group specifically needs `empy>=3.3,<4` and `pyros-genmsg`. Kconfig coverage
in the broader host group also needs `kconfiglib`. SCI layout/FSP authority is
a separate `reference-host` check; portable host snapshots do not copy `refs/`.

Firmware builds additionally require `rsync`, GNU Make, `unzip`, `curl`, the
NuttX build dependencies and the ARM cross-toolchain on `PATH`. The pipeline
was exercised with GNU Arm 13.2.Rel1. The xSPI admission check intentionally
accepts the inspected compiled default-denial body; a different compiler may
need source/build review before that check is broadened.

## Select checks

```sh
python3 Tools/rzv2h-regression.py check
python3 Tools/rzv2h-regression.py list --group sample-host
python3 Tools/rzv2h-regression.py list --json
```

| Catalog group | Inputs and effect |
|---|---|
| `sample-host` | Default bounded driver/parser/CI-tool regressions; no board or firmware output required |
| `port-host` | Broader portable PX4/NuttX source and native C/C++ checks; includes sample checks |
| `debug-host` | Fake local J-Link/GDB process and socket fixtures; no probe connection |
| `policy-host` | Formatter adapter/source-preservation fixtures; does not qualify all legacy source |
| `reference-host` | Local ignored CMSIS authority for all three cores and ten SCI layouts, including CSDIV/SYSC layout parity; missing files fail admission |
| `sci-mode-host` | Focused manual-derived SCI SPI/I2C timing, transfer, interrupt and cleanup regressions; no board access |
| `vendor-host` | Native RTT buffer tests; requires the downloaded SEGGER source in the checkout |
| `native-sample-artifacts` | All discovered native ELF/config/linker receipts and rehashed semantic negative controls |
| `driver-instance-artifacts` | ARM instance case/provider and selector controls; the selected archive must include a RIIC image and all seven SDHI/WDT instance images |
| `sample-artifacts` | Actual sample ELF/config/map/archive/receipt checks after building the full sample matrix |
| `px4-artifacts` | Existing PX4 artifact/ROMFS/package or offline GDB type checks; requires the named complete builds |
| `px4-archive-artifacts` | Full sealed PX4 matrix admission and rehashed negative controls; requires `--px4-archive` |
| `build`, `offline-tools`, `hardware-tools`, `legacy-hardware`, `support` | Catalog/reference entries; the host test runner refuses to execute these groups |

Use repeated `--group` or `--test <exact-id>` to select a union. A bad ID or an
empty selection fails. The catalog splits RTT source checks from vendor buffer
execution, and splits fake debug fixtures from real-ELF GDB type checks. A host
suite named `runtime` runs native production code against host boundaries; it
is not a board transcript.

## Run the host gate

Use a new or empty output directory for every job:

```sh
python3 Tools/rzv2h-regression.py run \
  --group sample-host --output build/rzv2h-ci-host
```

Run the broader set when its owning port/PX4 code changes:

```sh
python3 Tools/rzv2h-regression.py run \
  --group port-host --output build/rzv2h-ci-port
```

The runner executes scripts sequentially and writes `results.json`,
`junit.xml` and one log per script. JUnit has one testcase per scheduled script;
JSON also reports the unittest method count. Nonzero exit, missing dependencies,
any skipped check, zero tests, missing Python completion summary or timeout
makes the job fail. The default timeout is 180 seconds per script; use
`--timeout <seconds>` for a measured need. Interruption/timeout stops owned
process groups, including descendants whose parent has already exited. After
a five-second SIGTERM grace period, remaining members receive SIGKILL. On
cancellation, the active check fails, pending checks remain
`NOT-RUN` (JUnit skipped), and the runner exits 130. Publish all three output
forms even when the job fails.

## Build all native samples

The [native inventory](../../../platforms/nuttx/Debug/rzv2h-all-sample-configs.json)
contains 128 configs: the original 55 and 73 fixed controller-instance profiles,
including boot-only, serial and peer images.
It records explicit versus Kconfig-default core identity, console/entry route,
bounded commands, fixture requirements, hazards and evidence class. CM33 and
unclassified peer/output/recovery routes can be built but remain blocked for
the local executor.

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-inventory.py --json > <candidate-inventory.json>
NUTTX_BUILD_JOBS=8 python3 platforms/nuttx/Debug/rzv2h-sample-build.py \
  --all-configs --cache-dir <verified-download-cache> --output <new-native-archive>
python3 Tools/rzv2h-regression.py run --group native-sample-artifacts \
  --sample-builds <new-native-archive>/builds \
  --sample-source-state <new-native-archive>/source-state.json \
  --output <new-native-check-results>
```

`--json` emits the full deterministic inventory; compare the candidate before
replacing policy. Coverage dimensions and explicit blockers live in
[`rzv2h-driver-coverage.json`](../../../platforms/nuttx/Debug/rzv2h-driver-coverage.json).
Archives bind the selected inventory, legacy case contract and driver catalogue
by digest for build, resume, artifact admission and results.
The GBETH additions are `ether0-board-rtt` and `ether1-board-rtt`. Admission
requires the selected port enabled, its sibling disabled, late network-device
initialization, and automatic netinit/DHCP off. These are registration checks;
the existing Ethernet function profiles retain their separate operation gates.
SDHI0–2 profiles require the lower-only selector and exclude MMCSD/FAT;
CM33 is rejected. WDT0–3 profiles select exactly one counter, disable
automonitor/test threads and interrupt mode, and require a pre-existing
stopped-counter handoff. Artifact checks enforce these requirements separately
from archived catalogue declarations.

Every native config gets an independent work copy of the frozen source snapshot.
A failed image remains in JSON/JUnit while later configs are attempted.
`--profile <name>` selects a subset; `--timeout` bounds each build.
`--resume` requires identical source, manifest, toolchain, tool and cache inputs
and rechecks successful receipts before reuse. Replaced failed directories are
retained with a timestamp. No build configures the shared source tree.

Native receipts additionally bind the original defconfig and exact linker script,
declared/resolved core entry, real builtin pointer and primary console.
Primary CR8 RTT must occupy its private noncache SRAM; optional RTT diagnostics
on serial-primary profiles are recorded separately. Boot-only HIL images keep
their native entrypoint and use noncache SRAM, 8 KiB RTT capture and trim mode.

The [GitHub workflow](../../../.github/workflows/rzv2h-nuttx-samples.yml) runs
`sample-host` on relevant pull requests. Manual/default-branch and scheduled
builds use the `rzv2h-host-build` environment, GNU Arm 13.2.Rel1 and hash-checked
RTT/LittleFS archives. Configure environment protection in repository settings
before enabling its protected job. Submodule checkout must be accessible to
the runner; missing access fails the job. No job installs probe software or
executes target commands. Local validation does not establish that GitHub ran
the workflow. The workflow pins Ubuntu Noble's
[compiler package](https://packages.ubuntu.com/noble/gcc-arm-none-eabi).

The [current machine snapshot](../../../plans/261022-1849-rzv2h-jlink-retry/all-sample-results.json)
and [remaining actions](../../../plans/261022-1849-rzv2h-jlink-retry/remaining-samples.md)
are the coverage and follow-up owners for the approved local campaign. Its
[retry report](../../../plans/reports/hardware-261022-1849-rzv2h-jlink-retry.md)
records the current host gate and bounded warm-load results; hosted GitHub CI is
NOT-RUN for this campaign. The retry report records the host-check result and
the skipped legacy PX4 symbol check. The earlier
[all-sample build/host baseline](../../../plans/reports/execution-261022-rzv2h-all-samples.md)
is historical.

## Build the compatible 14-profile RTT matrix

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-build.py --list
python3 platforms/nuttx/Debug/rzv2h-sample-build.py \
  --output build/rzv2h-ci-samples
```

The default is every profile in the
[executable manifest](../../../platforms/nuttx/Debug/rzv2h-sample-profiles.json).
Repeat `--profile` to select a smaller build. Each job copies working sources,
including uncommitted board/app changes, into a disposable isolated tree. It
calls the existing NuttX `build.sh` sequentially and never configures/builds in
the shared source output tree. Generated architecture/board links and context
stamps are omitted so configuration recreates them in the snapshot; absolute
or escaping source symlinks are omitted with `rsync --safe-links`. Builder
interruption uses the same process-group cleanup as the host runner.
Temporary source/build files are removed when
the command ends; archived outputs remain.

An optional `--cache-dir <directory>` supplies `RTT.zip` and `v2.4.0.tar.gz`.
The RTT cache must match the source-pinned SHA-256. The LittleFS archive hash
is recorded for provenance; it is not an additional authenticity guarantee.
Cache use changes download URLs only inside the disposable copy. Without this
option, the existing NuttX download rules need network access.

Retain the complete output directory:

| Output | Purpose |
|---|---|
| `source-state.json` | Source hashes, exact repository commits/dirty state, compiler, cache overrides and no target actions |
| `sample-profiles.json` | Contract snapshot used by the build job |
| `build-results.json` | Per-profile build/admission status; a failed build stops the matrix |
| `builds/<profile>/` | ELF, resolved config, link maps, optional bin/hex, build log and digest-bound receipt |
| SCIF `libarch.a`, `rzv_scif.o` | Exact provider evidence even when unused `up_putc` is discarded by the linker |

A single-profile build can be checked independently through the builder. The
full negative artifact suite below expects the complete 14-profile matrix.

## Check archived images without a board

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-artifact-check.py \
  --manifest build/rzv2h-ci-samples/sample-profiles.json \
  --builds build/rzv2h-ci-samples/builds \
  --source-state build/rzv2h-ci-samples/source-state.json \
  --output build/rzv2h-ci-samples/artifact-checks.json

python3 Tools/rzv2h-regression.py run --group sample-artifacts \
  --sample-builds build/rzv2h-ci-samples/builds \
  --sample-source-state build/rzv2h-ci-samples/source-state.json \
  --output build/rzv2h-ci-artifact-tests
```

The underlying test remains directly callable:

```sh
python3 test/rzv2h-sample-artifact-test.py \
  --builds build/rzv2h-ci-samples/builds \
  --source-state build/rzv2h-ci-samples/source-state.json
```

There is no fallback to `plans/reports/`. Missing receipts fail; `--unit-only`
explicitly selects ELF parser primitives without compiled inputs. Keep input
archives and their source-state together when transferring them between jobs.
Receipts must bind `nuttx.elf`, `resolved.config`, `nuttx.map` and `System.map`.
Historical receipts without these digests do not satisfy the current gate.
All successful build admissions remain `BUILD-CHECKED`, `NOT-RUN`, and
unauthorized for target use. They never establish hardware qualification.

Existing PX4 artifact suites accept their own `--build-dir` options. Their
catalog notes name the default build targets. They require installed ROMFS,
resolved config, maps and package outputs as well as ELFs; do not substitute a
standalone NuttX ELF for a complete PX4 build.

## Build and check the PX4 matrix without hardware

The [PX4 policy](../../../Tools/rzv2h-px4-profiles.json) classifies all nine
RZ/V2H profiles exposed by the root `build.sh`. RA8 targets are outside this gate.
Use a new or empty job directory:

```sh
python3 Tools/rzv2h-px4-build.py --list
python3 Tools/rzv2h-px4-build.py --output build/rzv2h-px4-matrix

python3 Tools/rzv2h-px4-artifact-check.py \
  --archive build/rzv2h-px4-matrix/archive \
  --output build/rzv2h-px4-recheck.json

python3 Tools/rzv2h-regression.py run --group px4-archive-artifacts \
  --px4-archive build/rzv2h-px4-matrix/archive \
  --output build/rzv2h-px4-archive-tests
```

The builder makes independent local Git copies of working sources and initialized
repositories, including nested `pymavlink`. It retains staged/working edits,
eligible untracked sources, deletions, commits, tag identities and repository
origins. Untracked additions must match source/configuration names within the
builder's declared build roots; unrelated root files and private configuration
are omitted. It omits generated configuration links and unsafe source symlinks with
diagnostics. It runs `port-host` inside that same snapshot before sequential
root-script builds. It never configures or cleans the original checkout.
Input rescans detect source drift before another image is accepted.

Repeat `--target <canonical-name>` for a subset. Policy revision **3** selects
`dualcr8` alone when a sensor bring-up subset is requested: it has no qualified
CR8-1 peer. Duplicate explicit selections fail. The retired separate demo
target is rejected. Subset success has
`full_matrix: false`. The initial per-image timeout is 1800 seconds, configurable
with `--timeout`; `--host-timeout` bounds the complete host stage. Cancellation
stops owned process groups, including children whose leader exited. Commands
must remain in their owned groups; daemonizing commands are unsupported.

The existing build prerequisites apply, with local Git metadata and ARM binutils
(`nm`, `readelf`, `objcopy`) plus `gdb-multiarch` for offline compiled pair types.
Fake-debug host tests require ordinary loopback socket permissions. Declared
dependency downloads remain enabled. Optional `--cache-dir` uses the same
`RTT.zip`/LittleFS cache route as the sample builder, recording the override in
the source snapshot. RTT archive and patched source/header hashes must match the
source-pinned contract.

Retain the whole job directory:

| Location | Contents |
|---|---|
| `build-results.json`, `junit.xml` | Mutable job status, elapsed times and failure/pending entries |
| `archive/source-state.json`, `px4-profiles.json` | Frozen effective inputs, original inputs, Git/tool/cache provenance and policy |
| `archive/host/` | Host results, JUnit and individual logs |
| `archive/builds/<target>/` | Complete required firmware/config/ROMFS/metadata, focused-check logs and immutable target receipt |
| `archive/pair-receipt.json` | Only generated for a policy-qualified pair; absent under revision 3 while the actuator pair is unqualified |
| `archive/inventory.json` | Exact file sizes and hashes, excluding the inventory itself |

Checker reports stay outside `archive/`. Rechecks preserve its bytes and work
after disposable sources are removed or the archive is relocated. The checker
uses its installation-local policy; an archived policy cannot authorize changed
limits. Missing scheduled outputs, skipped/zero checks, timeouts and malformed
or coherently rehashed semantic mutants fail. The artifact test command requires
the complete real matrix. For parser development only, use
`python3 test/rzv2h-px4-artifact-test.py --unit-only`.

The CR8-1 package maximum is **8,650,368 uncompressed bytes**: 128 header +
130,560 ITCM + 131,072 cache SRAM + 8,388,608 cache DDR, from the active linker
and CMake split-section mapping. Independent descriptor, ELF/runtime reservation
and per-region bounds still apply. This software-format envelope does not
establish a physical flash partition or a loader/deployment capacity. Board ID
14 and `PX4FWv2` remain unchanged.

Console evidence follows the selected sources: CR8-1 uses an RTT console (`CONFIG_SYSLOG_RTT`, no SCI console);
CM33's current defconfig leaves RTT in ordinary SRAM rather than
selecting the dedicated linker RTT section. Private CR8 TCM addresses may match
between cores. Pair checks distinguish these local aliases from private SRAM/DDR
and intentional shared-memory windows.

CR8-1 uses the dedicated raw MHU/shared-memory character transport for
`/dev/ipcc1` and `/dev/ipcc3`. The generic experimental `IPCC` upper half and
`IPCC_BUFFERED` are independent of that transport; requested defconfig entries
do not establish resolved selections. Admission checks the raw selectors and
compiled registration provider.

CM33 selects `NSH_ARCHROMFS` so NSH mounts the generated PX4 ROMFS rather than
NuttX's built-in 1 KiB sample. The archive checker compares the bytes linked into
the ELF with that generated image and its installed tree.

Successful software admission remains `BUILD-CHECKED`, on-target `NOT-RUN`, with
`target_actions: []`. It establishes no electrical, silicon IRQ/DMA/cache,
timing, persistence or flight qualification. Legacy `px4-artifacts`, sample
groups and their argument contracts remain available.

The current reviewed software receipt records **61 host suites / 583 cases
passed**, the `mixer_module_tests` and `CollisionPrevention` functional suites,
three firmware targets (`default`, canonical `dualcr8`, and CR8-1 `pwm`), and
five candidate artifact cases. See [dual-CR8 software validation](../evidence/dualcr8-software-validation-261021.md)
for the durable hashes and the boundary that keeps the CR8-1 identity and
actuator pair unconfigured.

## Execute an approved board batch

Board execution needs a dedicated Linux runner with the approved probe,
exclusive access to that probe, the exact ELF/hash and the fixture's physical
connections. Use a protected/manual CI job or equivalent local approval route
for loads and declared driver operations. Remote hardware runner enrollment is
separate. A machine receipt never grants approval.

The catalog links the existing ELF-aware preflight, guarded single-core loader,
RTT bridge, NSH client and one-shot register reader. Follow the
[board-sample procedure](rzv2h-rtt-board-samples.md) and
[IPC HIL guide](rzv2h-ipc-hil-test-guide.md). The IPC autotest loads two cores;
it is a different fixture from the new single-core `/dev/ipcc4` local sample.
CM33 attach, unexpected reset recovery and peripheral connections remain
subject to the owning project's restrictions. Inspect current load-helper retry
behavior; stop on reset/connect-failure markers rather than scheduling retries.

After an approved sample capture, check saved evidence with
`platforms/nuttx/Debug/rzv2h-sample-runner.py`. It requires manifest/profile,
transcript, separate post-run health and a run receipt with terminal, timeout,
resource and host-cleanup proof. See its `--help` for exact arguments. It only
parses saved files and does not operate the board.

Keep `legacy-hardware` entries out of unattended jobs. They include direct
configure/make routes, static RTT/frame addresses, interactive sessions and a
GDB-server RTT hold fragment that is unsupported on CR8. These remain indexed
for traceability; the current guarded wrappers own the supported workflow.

## Execute an approved local board batch

The [local executor](../../../platforms/nuttx/Debug/rzv2h-sample-lab.py)
defaults to dry-run. It accepts only the reviewed installed policy and matching
admitted native archive. Supply a fixture JSON with `reset_class: "warm-load"`,
a source-backed `initial_state`, and `verified` mapping each required fixture
name to its observation/reference. Unknown prerequisites are refused.

```sh
python3 platforms/nuttx/Debug/rzv2h-sample-lab.py \
  --archive <native-archive> --profile <profile> --fixture <fixture.json> \
  --output <new-run-directory> --dry-run
```

After explicit approval, the same command uses `--execute --approval-ref
<independent-approval-reference>`. It prints exact ELF/core/hash, takes an
exclusive local lock, requires free probe/ports, forces `LOAD_ATTEMPTS=1`, and
uses only fixed bounded commands. Reset/DBGEN failures stop execution and
require renewed approval; a timeout leaves target state unresolved. It never
attaches CM33 or automates reset, watchdog expiry, storage writes or task kills.
It checks actual WAITPID/parent/child status support. Asynchronous and boot-only
apps require a separate read-only task census after stopping RTT. Host process
and port cleanup are independently observed. Logs mask the probe serial.
Bridge state lives in `<new-run-directory>/bridge-state`; helper temporary
files use `<new-run-directory>/tmp`, keeping target data with its run evidence.
Automatic post-load verification uses bounded PC and GIC reads before resume.
Capture a fault backtrace separately from the identified image: ARM assembly
prologue unwinding can stall and must not block ordinary load verification.

Saved native evidence can be rechecked using `rzv2h-sample-runner.py` with the
archived manifest and `--archive <native-archive>` in addition to transcript,
health and receipt arguments. Execution policy/executor digests must match
the reviewed installation. The original 14-profile offline interface remains
available. Changed executor inputs require a separately reviewed capture;
never rewrite old receipts.

`rzv2h-sample-coverage.py --archive <native-archive> --run <exact-run-directory>
--output <coverage.json> --markdown <summary.md>` re-admits every inventoried native image and
replays named receipts. Repeat `--run` chronologically. It exits nonzero for an
incomplete campaign and retains blocked/failed/not-run rows. Warm-load evidence
does not establish independent cold-state, electrical or production qualification.
