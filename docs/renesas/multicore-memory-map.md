# RZ/V2H Multi-Core Unified Memory Map (Ratified)

**Status:** Phase 1 ratified — 2026-07-12. Single source of truth for CR8-0 / CR8-1 / CM33 addresses.
**Ground truth:** R01UH1032EJ0110 Rev.1.10 §1.8.2 (CM33 address space, `reformatted_cm33_address_space.md`),
§2.2 CPU (CR8 TCM/boot, `RZV2H_HWM_CPUs.md`), FSP reference projects (`refs/*_cr8_{0,1}_ep`, `refs/*_cm33_ep`),
and the in-tree linker scripts as corrected in the CR8 boot slice.

Supersedes the stale core table in `ipc-architecture.md` (CR8-1 @0x40000000 / CM33 @0x40100000 — corrected).

---

## 1. Per-Core Address Aliasing (key model)

The same physical resource appears at **different addresses in each core's view**; the SoC's 36-bit
translator maps every per-core view to one overall address (HWM §1.7.3.2.2 for CM33). Always state which
core's view an address is in.

| Resource | CR8 view | CM33 Secure view | CM33 Non-Secure view |
|---|---|---|---|
| SRAM code region base | (SRAM$ per core, see §3) | `0x0800_0000` (SRAM0 Code-S) | `0x1800_0000` (SRAM0 Code-NS) |
| SRAM data alias | — | `0x2800_0000` (+0x20000000) | `0x3800_0000` |
| DDR base | `0x4000_0000` | `0x8000_0000` (DDR-S) | `0x9000_0000` (DDR-NS) |
| xSPI flash base | `0x6000_0000` | `0x6000_0000` (xSPI-S) | `0x7000_0000` |
| CR8-0 ITCM (AXI alias, for loaders) | local `0x0000_0000` | `0x4204_0000` | `0x5204_0000` |
| CR8-1 ITCM (AXI alias, for loaders) | local `0x0000_0000` | `0x4208_0000` | `0x5208_0000` |
| CR8-0 DTCM (AXI alias) | local `0x0002_0000` | `0x4206_0000` | `0x5206_0000` |
| CR8-1 DTCM (AXI alias) | local `0x0002_0000` | `0x420A_0000` | `0x520A_0000` |

TCM is **core-private**: each CR8 core sees its own ITCM at local `0x0` and DTCM at local `0x00020000`
(HWM §2.2: CR8 boots from I-TCM; ITCM/DTCM = 128 KB each, ECC). Loaders reach a specific core's TCM only
through the per-core AXI alias above.

---

## 2. CM33 (Cortex-M33) — pinned from HWM §1.8.2 + FSP reference

CM33 code space = `0x0000_0000–0x1FFF_FFFF`; data space = `0x2000_0000–0x3FFF_FFFF` (+0x20000000 alias of
the same physical SRAM). Boot ROM at `0x0` reads the BOOTPARAM block from a fixed SRAM address.

| Region | CM33-S start | End | Size | Notes | Status |
|---|---|---|---|---|---|
| ROM (Code, Secure) | `0x0000_0000` | `0x0001_FFFF` | 128 K | boot ROM | OK (HWM) |
| SRAM0 (Code, Secure) | `0x0800_0000` | `0x0807_FFFF` | 512 K | CM33 code bank 0 | OK (HWM) |
| SRAM1 (Code, Secure) | `0x0808_0000` | `0x080F_FFFF` | 512 K | CM33 code bank 1 (image spans 0+1) | OK (HWM) |
| BOOTPARAM | `0x0800_1E00` | `0x0800_1FFF` | 0x200 | ROM contract: end-word, size `0x00000A00`, entry, magic `0xAA55` | TARGET (FSP ref) |
| DUMMY gap | `0x0800_2000` | `0x0800_2007` | 8 | reserved gap before code | TARGET (FSP ref) |
| Code/rodata/data/bss/stack/heap | `0x0800_2800` | `0x080F_7FFF` | `0xF5800` | NuttX volatile-load window; FSP persistent image may extend farther | SOURCE-RATIFIED |
| RTT reserved window | `0x080F_8000` | `0x080F_BFFF` | 16 K | NuttX `.noncache_buffer`; MPU non-cacheable/shareable | SOURCE-RATIFIED |
| SRAM data alias (same phys) | `0x2800_2800` | — | — | data-space view (+0x20000000); not used by current NuttX ELF | SOURCE-RATIFIED |
| xSPI image source (flash) | `0x6000_0000` | — | image | boot ROM loads from here | TARGET |

**BOOTPARAM contents (FSP `rzv2h_evk_cm.ld`) for a future persistent image:**
`LONG(__RAM_end__ - 0x08000000)` · `LONG(0x00000A00)` · `LONG(reset_entry + 0x20000000)` · `SHORT(0xAA55)`.
The entry is the code→data-alias of the reset handler. In NuttX this must resolve to `__start`.

The volatile NuttX debugger image now follows the FSP secure SRAM code view
at `0x0800_2800`, uses LMA=VMA, and maps the CM33 non-secure MHU view at
`0x5048_0000`. This is source/build evidence, not proof that SEGGER reset or
release establishes the required CM33 secure reset state. Persistent ROM/xSPI
packaging still requires BOOTPARAM and post-build work outside this RAM-load
validation scope.

---

## 3. CR8-0 / CR8-1 (Cortex-R8) — as implemented + verified (CR8 boot slice, 2026-07-12)

Both cores link the **private view at local `0x0`** (TCM is core-private); uniqueness is only in the
AXI/SRAM/DDR/flash aliases. Verified by build + `readelf` on `renesas_rdk-rzv2h_default` and
`renesas_rdk-rzv2h-io-cr8_1_default` this session.

| Region | CR8-0 (local/CR8 view) | CR8-1 (local/CR8 view) | Size | Status |
|---|---|---|---|---|
| ITCM (vectors + BSP text) | `0x0000_0000` | `0x0000_0000` | 127.5 K | OK |
| Flash header (in-image) | `0x0001_FE00` | `0x0001_FE00` | 0x80 | OK |
| DTCM (stack/heap/bss) | `0x0002_0000` | `0x0002_0000` | 128 K | OK (CP15 `0x00020021` enables at boot) |
| ITCM AXI alias (loader) | `0x1204_0000` | `0x1208_0000` | 128 K | OK |
| SRAM cache | `0x0818_0000` | `0x081C_0000` | 128 K | OK |
| SRAM uncache (+wait word) | `0x081A_0000` (`…081BFFFC`) | `0x081E_0000` (`…081FFFFC`) | 128 K | OK |
| DDR cache (kernel text/data) | `0x4080_0000` | `0x4180_0000` | 8 M | OK |
| DDR uncache | `0x4100_0000` | `0x4200_0000` | 8 M | OK |
| xSPI image (flash / srec VMA) | `0x2020_0000` / `0x6020_0000` | `0x2130_0000` / `0x6130_0000` | image | OK |

DTCM enable (both cores, `arm_head.S`): `mcr p15,0,r0,c9,c1,0` with `r0 = 0x00020021` (base `0x00020000`,
size `0b01000`=128 KB, enable) — byte-identical to FSP CR8 `startup.asm`; DTCM 128 KB confirmed by HWM §2.2.

ICU INTR8SEL partition (single shared bank, per FSP): CR8-0 slots `0..84`, CR8-1 slots `85..126`.

---

## 4. Shared DDR windows (OpenAMP / MHU / IPC)

Same physical DDR window, addressed per core (CR8 base `0x4000_0000`; CM33-S FSP base `0x8000_0000`).

| Window | CR8 view | CM33-S view (FSP ref) | Size | Status |
|---|---|---|---|---|
| OPENAMP_RSCTBL | `0x42F0_0000` | `0x82F0_0000` | 4 K | OK (intentional cross-core overlap) |
| MHU_SHMEM | `0x42F0_1000` | `0x82F0_1000` | 4 K | OK |
| OPENAMP_VRING | `0x4300_0000` | `0x8300_0000` | 8 M (FSP ref 0xF00000) | OK |
| IPC_RAW_SHM (CR8↔CR8; CR8-1↔CM33 @+0x20000) | `0x4380_0000` | `0x8380_0000` | 256 K | SOURCE-RATIFIED; CM33 link uses `0x8382_0000` |

The raw IPC profile maps its CM33 secure-DDR view non-cacheable/shareable.
CPU-side visibility and cache behavior remain target validation gates.

---

## Unresolved (carry to CM33 implementation pass)
1. Prove the CM33 reset/vector/register launch sequence with `R9A09G057H44_M33_0` before execution.
2. Confirm CM33 CPU access to `0x8382_0000` and MHU NS `0x5048_0000`; DAP readback alone is insufficient.
3. Persistent ROM/xSPI bootparam acceptance remains outside the volatile-load scope.
