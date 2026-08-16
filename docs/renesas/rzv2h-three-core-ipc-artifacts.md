# RZ/V2H Three-Core IPC Artifact Evidence

**Date:** 2026-08-09

**Scope:** tracked host-side evidence for the current `ipcc-raw-cr8_0`,
`ipcc-raw-cr8_1`, and `ipcc-raw-cm33` build artifacts. This file records
hashes, load-span authorization commands, and the CM33 vector symbol contract.
It does **not** claim target boot, reset, detach, interrupt, or IPC traffic
behavior.

## Provenance Rules

- `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/` contains the
  local generated ELFs, maps, and configs used for the commands below. Those
  files are ignored workspace inputs, not tracked proof.
- `refs/rzv2h_evk/...` contains local Renesas sample launch metadata. Those
  files are external source inputs, not tracked proof.
- Load authorization is granted only when the checker uses the canonical bundled
  manifest at
  `platforms/nuttx/Debug/rzv2h-ipc-elf-allowlists.json` **and** the caller
  supplies the expected SHA-256 for the exact ELF under review. A custom
  manifest remains inspection-only.

## Current Artifact Hashes

| Core | Local ELF | SHA-256 |
|---|---|---|
| CR8-0 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_0/nuttx` | `77f701cd701ae619ef895943f4c553f357fe4712313ddd656ee35eae0a29f7f6` |
| CR8-1 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_1/nuttx` | `93421bada02bd5c33a84cb1da7e2c6660ff1e71d7fd95bb9e8897dde32e1b2f1` |
| CM33 | `plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cm33/nuttx` | `03b0d99daaff61d61deaaec53cb1729ecab845f66d53944366ff8a583f03fee2` |

## Repro Commands

```sh
python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_0/nuttx \
  --device R9A09G057H44_R8_0 \
  --expect-sha256 77f701cd701ae619ef895943f4c553f357fe4712313ddd656ee35eae0a29f7f6

python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cr8_1/nuttx \
  --device R9A09G057H44_R8_1 \
  --expect-sha256 93421bada02bd5c33a84cb1da7e2c6660ff1e71d7fd95bb9e8897dde32e1b2f1

python3 platforms/nuttx/Debug/rzv2h-ipc-elf-allowlist.py \
  --elf plans/260809-1341-rzv2h-three-core-ipc-validation/artifacts/cm33/nuttx \
  --device R9A09G057H44_M33_0 \
  --expect-sha256 03b0d99daaff61d61deaaec53cb1729ecab845f66d53944366ff8a583f03fee2
```

Expected result for each command:

- `MANIFEST_STATUS=ratified`
- `MANIFEST=.../platforms/nuttx/Debug/rzv2h-ipc-elf-allowlists.json`
- `RESULT=AUTHORIZED_ADDRESS_CONTRACT`

## Authorized PT_LOAD Summary

| Core | Authorized spans |
|---|---|
| CR8-0 | `0x00000000/0x100`, `0x40800000/0x2fb30`, `0x4082fb30/0x33b8`, `0x40832ee8/0x1838`, `0x0001fe00/0x80` |
| CR8-1 | `0x00000000/0x100`, `0x41800000/0x2fb38`, `0x4182fb40/0x33cc`, `0x41832f0c/0x16d4`, `0x0001fe00/0x80` |
| CM33 | `0x08002800/0x1f6c4 filesz, 0xf5800 memsz`, `0x080f8000/0x0 filesz, 0x24c0 memsz` |

## CM33 Vector Contract

- Current NuttX CM33 links `.vectors` at `0x08002800` and exports `_vectors`,
  not `__Secure_Vectors`.
- The rebuilt vector words are MSP `0x08023ec8` and Thumb reset PC
  `0x080030dd`; the MSP now satisfies the required 8-byte alignment.
- `__start` remains the ELF entry symbol, but debugger launch must consume the
  verified vector words at `0x08002800` for MSP and Thumb PC setup. A PC-only
  jump to `__start` is not an authorized launch recipe.
- Renesas `&__Secure_Vectors` is an FSP sample-launch field name only. Treat it
  as external reference metadata, not as the NuttX CM33 symbol contract.
