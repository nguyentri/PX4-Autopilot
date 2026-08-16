# RZ/V2H Three-Core J-Link Contract

**Scope:** source-backed preparation for volatile RAM validation. No target
reset, load, run, or detach behavior is claimed here.

## Core selection

| Core | SEGGER server device | e2 studio target | Special setting |
|---|---|---|---|
| CR8-0 | `R9A09G057H44_R8_0` | `R9A09G057H44GBG_CR8_0` | — |
| CR8-1 | `R9A09G057H44_R8_1` | `R9A09G057H44GBG_CR8_1` | — |
| CM33  | `R9A09G057H44_M33_0` | `R9A09G057H44GBG_CM33_0` | FSP sample metadata records secure vector `&__Secure_Vectors`; current NuttX uses `_vectors` at `0x08002800` |

Use the SEGGER server-device string, not the e2 studio target name, with
`JLinkGDBServerCLExe`/`JLinkGDBServer` `-device`.

| Core | Local Renesas launch input | Local J-Link settings input |
|---|---|---|
| CR8-0 | `refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_0_ep/e2studio/sci_b_uart_rzv2h_evk_cr8_0_ep Debug_Flat.launch` | matching `Debug_Flat.jlink` in the same directory |
| CR8-1 | `refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cr8_1_ep/e2studio/sci_b_uart_rzv2h_evk_cr8_1_ep Debug_Flat.launch` | matching `Debug_Flat.jlink` in the same directory |
| CM33  | `refs/rzv2h_evk/sci_b_uart/sci_b_uart_rzv2h_evk_cm33_ep/e2studio/sci_b_uart_rzv2h_evk_cm33_ep Debug_Flat.launch` | matching `Debug_Flat.jlink` in the same directory |

The three Renesas `Debug_Flat.launch` files select USB, SWD, numeric speed
`15000`, a 30-second connection timeout, and GDB port 61234. Their matching
`.jlink` files are byte-identical and specify no custom script or loader.
Those `refs/` paths are local ignored source inputs. They are not tracked proof;
use [RZ/V2H Three-Core IPC Artifact Evidence](./rzv2h-three-core-ipc-artifacts.md)
for tracked hashes and host-side authorization commands.

## Reset, run, and detach metadata

The supplied launch metadata is not an executable lifecycle specification.
It contains these simultaneous values:

- reset-begin-connection enabled, but connection reset and generic GDB reset
  disabled;
- reset-on-reload enabled, but reset-after-download and reset-before-run
  disabled;
- Renesas resume enabled, but generic resume disabled;
- stop-at `main` enabled, with no explicit PC assignment;
- disconnect mode `2` and release-reset enabled.

These values are identical for CR8-0, CR8-1, and CM33 except for the CM33 FSP
sample's secure-vector field:

| Operation | Recorded value for each core | What is proven |
|---|---|---|
| Attach/reset | `uResetBeginConnection=1`, `uNoReset=1`, `connection.reset=false`, generic `doReset=false` | Configuration only; physical reset outcome unresolved |
| Download/reload | image+symbols enabled, `uresetOnReload=1`, reset-after-download false | Reload requests reset; actual scope and order unresolved |
| Hold/stop | `stopAt=main`, `doHalt=false`, no PC assignment | No persistent core-hold mechanism is defined |
| Resume | Renesas resume true, generic resume false | Effective resume behavior unresolved |
| Detach | `uDisconnectionMode=2`, `release.reset=true` | Numeric mode and resulting run/reset state unresolved |
| Script/register init | script empty, register-init false | No custom lifecycle sequence is supplied |

The `.jlink` settings request flash download verification but disable RAM
download verification. They do not prove that a transfer occurred or that a
loaded RAM image was read back successfully.

The local files do not define the precedence of those duplicate fields or the
meaning of disconnect mode `2`. Therefore they do not prove whether attach
resets a core, whether download releases it, or whether detach leaves it
running, halted, or reset. Measure those transitions per selector before a
multi-image session. Until then:

1. do not issue reset after loading the first core;
2. record and restore each core's initial run/halt state;
3. do not use detach as a hold or release mechanism;
4. allow only one server process to own probe `52000195`.

## CM33 debugger address view

The Renesas CM33 reference disproves the earlier NuttX ATCM/BTCM model.
Addresses `0x00000000` and `0x20000000` are broad secure code/data views; the
reference does not define them as CM33 ATCM/BTCM. The actual debugger image is:

| Purpose | Address/view | Evidence |
|---|---|---|
| boot ROM | `0x00000000` | CM33 secure code view |
| BOOTPARAM | `0x08001e00` | persistent ROM contract |
| dummy loader area | `0x08002000` | persistent image packaging |
| executable SRAM image | `0x08002800` | secure SRAM code view |
| same SRAM data alias | `0x28002800` | code address + `0x20000000` |
| xSPI image source | `0x60000000` | post-build S-record origin |
| raw IPC shared DDR | `0x83820000` | CM33 secure DDR alias of CR8 `0x43820000` |
| MHU non-secure MMIO | `0x50480000` | CM33 peripheral view |

The NuttX raw CM33 ELF now uses SRAM `0x08002800..0x080f7fff` and reserves
`0x080f8000..0x080fbfff` for non-cacheable RTT storage. The tracked NuttX
contract is `_vectors` at `0x08002800`, not `__Secure_Vectors`. The address
checker authorizes these load spans only when the canonical bundled manifest and
the exact expected ELF SHA-256 are both supplied. This authorization covers
destinations only. Before execution, establish a vector-based reset path or
explicitly initialize MSP, VTOR/security state, Thumb state, and interrupt
masks from verified vector words. A PC-only jump to `__start` is prohibited.

## Remaining target evidence

- attach/reset/reload/resume/detach transition trace for each selector;
- CPU-side CM33 access to SRAM, MHU `0x50480000`, and DDR `0x83820000`;
- proof that switching selectors does not reset, halt, or release peer cores;
- RTT control-block selection while the other two cores continue running.
