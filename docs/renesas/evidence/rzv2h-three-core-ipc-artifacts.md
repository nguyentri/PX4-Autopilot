# RZ/V2H Three-Core IPC Artifact Evidence

**Date:** 2026-08-09

**Scope:** tracked host-side evidence for the current `ipcc-raw-cr8_0`,
`ipcc-raw-cr8_1`, and `ipcc-raw-cm33` build artifacts. This file records
hashes, load-span authorization commands, and the CM33 vector symbol contract.
It does **not** claim target boot, reset, detach, interrupt, or IPC traffic
behavior.

These artifacts describe the native raw IPC ABI-v2 and its guarded volatile
load contract. They are distinct from the reference CA55 RPMsg/RPC/uXRCE
path. Host-side address/hash evidence is sufficient for software review and
load preparation; the missing target transcript is a physical qualification
gate for a selected multi-core profile, not a blocker for standalone CR8
software work.

## Provenance Rules

- `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/` contains the
  local generated ELFs, maps, and configs used for the commands below. Those
  files are ignored workspace inputs, not tracked proof.
- `refs/rzv2h_evk/...` contains local Renesas sample launch metadata. Those
  files are external source inputs, not tracked proof.
- The address contract is verified only when the checker uses the canonical
  bundled manifest at
  `platforms/nuttx/Debug/rzv2h-ipc-elf-allowlists.json` **and** the caller
  supplies the expected SHA-256 for the exact ELF under review. A custom
  manifest remains inspection-only.
- A target load is authorized only through `--authorize-load`, with a loader
  command containing exactly one literal `{elf}` argument. Hashing, `readelf`,
  and that loader then consume one retained private snapshot; checker-only
  success does not authorize a later load from the original path.

## Current Artifact Hashes

| Core | Local ELF | SHA-256 |
|---|---|---|
| CR8-0 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_0/nuttx` | `49d9972089779c551d8c99eb64c41742db216825995dd88552b366b5a964024a` |
| CR8-1 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_1/nuttx` | `728662961d0f637d27f212c0e42623f88007493585702d5c7d7d3c01288ddd79` |
| CM33 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cm33/nuttx` | `4dae214e2c6df0fe7c6d59e142e2a5dcbcd762fab2de7a25689ddb28e892b97f` |

## Repro Commands

```sh
python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_0/nuttx \
  --device R9A09G057H44_R8_0 \
  --expect-sha256 49d9972089779c551d8c99eb64c41742db216825995dd88552b366b5a964024a

python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_1/nuttx \
  --device R9A09G057H44_R8_1 \
  --expect-sha256 728662961d0f637d27f212c0e42623f88007493585702d5c7d7d3c01288ddd79

python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cm33/nuttx \
  --device R9A09G057H44_M33_0 \
  --expect-sha256 4dae214e2c6df0fe7c6d59e142e2a5dcbcd762fab2de7a25689ddb28e892b97f
```

Expected result for each command:

- `MANIFEST_STATUS=ratified`
- `MANIFEST=.../platforms/nuttx/Debug/rzv2h-ipc-elf-allowlists.json`
- `LOAD_EXECUTED=NO`
- `RESULT=ADDRESS_CONTRACT_VERIFIED`

For an actual volatile load, start the J-Link GDB server with the exact device
selector above, then use guarded mode. The `{elf}` token is replaced with the
retained snapshot and must be passed as its own loader argument:

```sh
python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf <artifact-elf> \
  --device <exact-device-selector> \
  --expect-sha256 <recorded-sha256> \
  --loader /usr/bin/gdb-multiarch \
  --loader-arg={elf} \
  --loader-arg=--batch \
  --loader-arg=-ex \
  --loader-arg='target remote localhost:2331' \
  --loader-arg=-ex \
  --loader-arg=load \
  --loader-arg=-ex \
  --loader-arg=detach \
  --authorize-load
```

Only `RESULT=GUARDED_LOAD_COMPLETED` means the authorized snapshot was handed
to the loader. This command was host-regression-tested but not run against the
target in this evidence pass.

## Authorized PT_LOAD Summary

| Core | Authorized spans |
|---|---|
| CR8-0 | `0x00000000/0x100`, `0x40800000/0x2fe5c`, `0x4082fe60/0x3468`, `0x408332c8/0x0 filesz, 0x1838 memsz`, `0x0001fe00/0x80` |
| CR8-1 | `0x00000000/0x100`, `0x41800000/0x2fe64`, `0x4182fe70/0x347c`, `0x418332ec/0x0 filesz, 0x16d4 memsz`, `0x0001fe00/0x80` |
| CM33 | `0x08002800/0x1f7dc filesz, 0xf5800 memsz`, `0x080f8000/0x0 filesz, 0x24c0 memsz` |

## CM33 Vector Contract

- Current NuttX CM33 links `.vectors` at `0x08002800` and exports `_vectors`,
  not `__Secure_Vectors`.
- The rebuilt vector words are MSP `0x08023fe0` and Thumb reset PC
  `0x080030dd`; the MSP now satisfies the required 8-byte alignment.
- `__start` remains the ELF entry symbol, but debugger launch must consume the
  verified vector words at `0x08002800` for MSP and Thumb PC setup. A PC-only
  jump to `__start` is not an authorized launch recipe.
- Renesas `&__Secure_Vectors` is an FSP sample-launch field name only. Treat it
  as external reference metadata, not as the NuttX CM33 symbol contract.
