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
