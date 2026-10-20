# Run RZ/V2H regression checks in CI

Use the repository-owned [script catalog](../../../Tools/rzv2h-regression-catalog.json)
to choose a stage. The commands below work from the checkout root and require
no campaign directory. The catalog retains existing script locations, including
imported helpers and legacy HIL fragments; listing a tool does not run it.

## Prepare a Linux runner

Initialize both NuttX/apps submodules. Host checks use Python 3, GCC/G++, Bash
and ordinary Linux process/socket tools. The CI-tool snapshot fixtures also
require `rsync`. Install the Python requirements from
[Tools/setup/requirements.txt](../../../Tools/setup/requirements.txt); the sample
host group specifically needs `empy>=3.3,<4` and `pyros-genmsg`. Kconfig coverage
in the broader host group also needs `kconfiglib`.

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
| `reference-host` | Local ignored CMSIS authority for all three cores; missing directories fail admission |
| `vendor-host` | Native RTT buffer tests; requires the downloaded SEGGER source in the checkout |
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

## Build the RTT sample matrix

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

The [PX4 policy](../../../Tools/rzv2h-px4-profiles.json) classifies all eight
RZ/V2H targets exposed by the root `build.sh`. RA8 targets are outside this gate.
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

Repeat `--target <canonical-name>` for a subset. Selecting `dualcr8` adds its
CR8-1 peer; duplicate explicit selections fail. Subset success has
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
| `archive/pair-receipt.json` | Both finalized dual-CR8 member digests and compatibility/type evidence |
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

Console evidence follows the selected sources: CR8-1 uses SCI1 without a selected
RTT provider; CM33's current defconfig leaves RTT in ordinary SRAM rather than
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

## Use a board runner later

Board execution needs a dedicated Linux runner with the approved probe,
exclusive access to that probe, the exact ELF/hash and the fixture's physical
connections. Use a protected/manual CI job or equivalent local approval route
for loads and declared driver operations. This toolkit does not launch a board
job or treat a machine receipt as user approval.

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
