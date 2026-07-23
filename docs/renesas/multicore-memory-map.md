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
| Code/rodata/data/bss/stack/heap | `0x0800_2800` | `~0x080F_EFFF` | `0xFC7FF` (~1 M) | LMA=VMA (ROM loads whole image) | TARGET (FSP ref) |
| SRAM data alias (same phys) | `0x2800_2800` | — | — | `.data`/`.bss` data-space view (+0x20000000) | TARGET |
| xSPI image source (flash) | `0x6000_0000` | — | image | boot ROM loads from here | TARGET |

**BOOTPARAM contents (FSP `rzv2h_evk_cm.ld`), to reproduce in `rdk-rzv2h_cm33.ld`:**
`LONG(__RAM_end__ - 0x08000000)` · `LONG(0x00000A00)` · `LONG(reset_entry + 0x20000000)` · `SHORT(0xAA55)`.
The entry is the code→data-alias of the reset handler. In NuttX this must resolve to `__start`.

**Open decisions (do NOT ship blind — boot-critical, HW-unverifiable):**
- Secure vs non-secure alias for the NuttX CM33 image (FSP reference uses Secure `0x08…`).
- `.data` model: LMA=VMA whole-image-load (ROM) vs `CONFIG_BOOT_RUNFROMFLASH` copy — must match `rzv_start_cm33.c`.
- CM33 peripheral MMIO aliases (e.g. MHU): current `rzv_start_cm33.c` maps MHU NS `0x1048_0000`; HWM §1.8.2
  lists MHU (NS) `0x5048_0000` / (S) `0x4048_0000`. Reconcile before CM33 boot bring-up.

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
| IPC_RAW_SHM (CR8↔CR8; CR8↔CM33 @+0x10000) | `0x4380_0000` | (alias TBD) | 256 K | VERIFY — CM33 alias not yet in `cm33.ld` |

CM33 shared-window secure vs non-secure alias, and DDR cacheability from CM33, remain open (needs HW test).

---

## Unresolved (carry to CM33 implementation pass)
1. Secure vs non-secure CM33 alias choice for image + shared windows.
2. CM33 `.data` copy model (LMA=VMA vs RUNFROMFLASH) — couple `cm33.ld` and `rzv_start_cm33.c` together.
3. CM33 MHU/peripheral MMIO alias reconciliation (`0x1048_0000` in code vs HWM `0x5048_0000`).
4. All CM33 boot addresses tagged TARGET need on-target confirmation (ROM bootparam acceptance).
