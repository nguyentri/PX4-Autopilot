# Audit: camera (MIPI-CSI, VIN, OV5640) and mbed-crypto — RA8P1 CM85

## 1. Scope, core, baseline

- Core: CM85 (`evk-ra8p1`). Static audit only; nothing built, run or flashed.
- Baseline: PX4 `87f03177dbd`, NuttX `8f85716a87`, apps `ee45eec37`.
- Prefixes: A = `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8`, E = `.../boards/arm/ra8/evk-ra8p1`, F = `.../fpb-ra8e1`.
- FSP refs: `refs/ra8p1/ek_ra8p1/mipi_csi/mipi_csi_ek_ra8p1_ep/e2studio/`, `refs/ra8p1/ek_ra8p1/mbed_crypto/mbed_crypto_ek_ra8p1_ep/e2studio/`.
- Configs: `mipi-csi`, `mbed-crypto`. ELF layer: not built (user declined builds).
- RA8E1: `RA_HAVE_MIPI_CSI`/`RA_HAVE_VIN` selected only by RA8P1 chips (A/Kconfig:215,217,335,337); no F defconfig enables `RA_MIPI_CSI` (grep 0 hits). RA8E1 selects `RA_HAVE_CEU` (Kconfig:54), not audited here.

## 2. Trace matrix (CM85)

| Driver | Kconfig | Make.defs / CMake | Board glue / bringup | Status | FSP sample |
|---|---|---|---|---|---|
| ra_mipi_csi + VIN | `RA_MIPI_CSI` defined twice (A/Kconfig:3392, 5892) | Make.defs:91; CMake:84 | E/src/ra8p1_mipi_csi.c; bringup:391-394 | compiles (Make), no frames | `mipi_csi/` (`r_mipi_csi`, `r_mipi_phy`, `r_vin`) |
| ra_ov5640 | under `RA_MIPI_CSI` | Make.defs:92; **CMake missing** | called from `ra_camera_hw_setup` | compiles (Make) | `src/camera_sensor.c` |
| ra_mbed_crypto | none | none | none | 0-byte files (E0) | `mbed_crypto/` (`rm_psa_crypto`, RSIP E50D, OSPI_B, LittleFS) |

## 3. Findings

### CAM-01 High (high conf): MIPI D-PHY never initialised
- Failure: NuttX never programs the D-PHY (no user of `A/hardware/ra8p1/ra_mipi_phy.h` in any `.c`). FSP configures PHY PLL (24 MHz/3 × 125 = 1 GHz) and timings (TINIT 74999, TCLKSETT 62, THSSETT 24, …; `common_data.c:294-334`) before CSI. Without PHY lock/HS-settle the CSI receiver sees no packets → `read()` blocks forever on `frame_sem`.
- RA8E1: none (RA8P1-only peripheral). Remediation: port `r_mipi_phy` open sequence (PLL, timing, lane enable, wait lock) ahead of `ra_mipi_csi_hw_init`. Class: pre-existing.

### CAM-02 High (high conf): data-type mismatch — sensor sends YUV422, CSI/VIN filter RGB888
- Failure: OV5640 init writes `0x4300 = 0x32` (YUV422, A/ra_ov5640.c:73); VIN `CSI_IFMD` uses `R_VIN_CSI_IFMD_DT_0X24` (RGB888, A/ra_mipi_csi.c:307) and `MC INF_110` 24-bit RGB input. VIN discards packets with DT 0x1E → no frames; even if accepted, format would be misinterpreted.
- Ref: FSP `data_type_enable = YUV422_8_BIT` (`common_data.c:356`), VIN `input_mode YCBCR422_8_BIT`, `data_type YUV422_8_BIT` (`:471, :484`), output RGB565 with YC→RGB coefficients.
- RA8E1: none. Remediation: DT 0x1E + YCbCr422 input with VIN colour conversion (or set sensor to RGB565 DT 0x22 consistently); make `CAM_FMT_*`/`BYTES_PER_PIXEL` follow. Class: pre-existing.

### CAM-03 High (high conf): framebuffer at 0x60000000 with SDRAM absent/disabled
- Failure: `RA_MIPI_CSI_FB_BASE=0x60000000` (Kconfig:3426 default, `mipi-csi` defconfig, A/ra_mipi_csi.c:73-74, 329). EK SDRAM is at 0x68000000 (FSP `sdram_ep.h:51-52`) and `mipi-csi` defconfig does not enable `RA_SDRAM` → VIN writes ~3.7 MB (2 × 1024×600×3, :329-333) to an unbacked external-bus window → AXI bus error / garbage; CPU `memcpy` (:495) faults.
- Ref: FSP places three VIN buffers in `.sdram_noinit` (`common_data.c:458-460`).
- RA8E1: none. Remediation: enable `RA_SDRAM` in `mipi-csi`, default FB_BASE inside SDRAM (≥0x68000000), reserve the range from any heap; make bringup order SDRAM before camera. Class: pre-existing.

### CAM-04 Medium (high conf): no D-cache maintenance on VIN DMA buffers
- `mipi-csi` has `ARMV8M_DCACHE=y`; 0x60000000-0x7FFFFFFF is WBWA cacheable under the default ARMv8-M map (no MPU programming in ra8). `ra_camera_read` `memcpy`s from `fb[ready_fb]` (A/ra_mipi_csi.c:495) without `up_invalidate_dcache` → stale/partial frames.
- RA8E1: none. Remediation: invalidate the frame range before copy (buffers 32-byte aligned). Class: pre-existing.

### CAM-05 Medium (high conf): poll wake-up is broken and double-counts frames
- `ra_camera_poll` sets `fds->priv = &priv->frame_sem` (:591); notifier posts `fds->priv` (:200-202) instead of `poll_notify()` → poller's own semaphore never posted (poll never wakes), and `frame_sem` is posted twice per frame (:239 + :202) → subsequent `read()` returns without a new frame. Counting semaphore also accumulates stale frames while nobody reads.
- RA8E1: none. Remediation: use `poll_notify(priv->poll_fds, N, POLLIN)`; keep `frame_sem` binary (reset before wait). Class: pre-existing.

### CAM-06 Medium (medium conf): CSI controller config diverges from FSP
- MCT0 only sets lane count (A/ra_mipi_csi.c:~280); FSP also sets err_frame_notify, reserved_packet_reception, generic_rule_mode, ECC 24-bit (`common_data.c:345-351`). MCT2 FRRCLK/FRRSKW = 0x80 (:284-285) vs FSP 10/10 (`:353-354`) — value derives from the PHY HS clock; wrong value mis-detects packet end. Only RXIE RACTDETE + VC FSRE/FERE enabled; CSI ISR does not report errors.
- RA8E1: none. Remediation: take FSP control values; compute FRR from PHY rate. Class: pre-existing.

### CAM-07 Low (high conf): duplicate `config RA_MIPI_CSI`
- Defined at A/Kconfig:3392 (`depends on RA_HAVE_MIPI_CSI && RA_HAVE_VIN`, `select I2C`) and :5892 (`depends on RA_HAVE_MIPI_CSI`). Kconfig ORs the dependencies → symbol visible without VIN; two prompts in menuconfig. Same for `RA_VIN` placement in "Video" menu (:5906) with no consumer beyond defconfig.
- RA8E1: shared Kconfig, but RA8E1 lacks `RA_HAVE_MIPI_CSI` → none. Remediation: delete the :5892 copy. Class: drift.

### CAM-08 Low (high conf): CMake omits `ra_ov5640.c`
- A/CMakeLists.txt:84 adds `ra_mipi_csi.c` only; Make.defs:91-92 adds both → CMake build of `mipi-csi` fails to link (`ra_ov5640_*` undefined).
- RA8E1: shared CMakeLists, no F config affected. Remediation: add `ra_ov5640.c` next to `ra_mipi_csi.c`. Class: pre-existing (validation gap until built).

### CAM-09 Low (medium conf): sensor driver in arch layer, no ID check, generic default bus
- OV5640 is a board-level sensor but lives in `A/` and is hard-linked from the arch driver; init writes the table without reading chip ID 0x300A/0x300B, so a missing/unpowered sensor is reported as stream failure later. `RA_MIPI_CSI_I2C_BUS` default 0 (Kconfig:3432) vs EK I2C1 (FSP `hal_data.c:191-192` channel 1, 400 kHz); defconfig sets 1 correctly. `CONFIG_VIDEO`/`VIDEO_STREAM` enabled but driver is a custom `/dev/camera0`, not the NuttX video/imgsensor framework.
- RA8E1: none. Remediation: move sensor to `drivers/video` or board, add ID probe, default bus 1. Class: drift.

### CAM-10 Medium (high conf): `ra_mbed_crypto` is an empty stub; config is software-only mbedTLS
- `A/ra_mbed_crypto.c`, `A/ra_mbed_crypto.h`, `E/src/ra8p1_mbed_crypto.c` are 0 bytes; no Kconfig, Make.defs, CMake or bringup reference. `mbed-crypto` defconfig = `CRYPTO_MBEDTLS`, `MBEDTLS_APPS`, `MBEDTLS_APP_SELFTEST` → pure software crypto, no RSIP/SCE acceleration, no TRNG entropy source.
- Ref: FSP sample uses `rm_psa_crypto` + RSIP E50D (`r_sce`) + `rm_littlefs_spi_flash` on OSPI_B (configuration.xml modules).
- Risk: name implies hardware crypto parity that does not exist; if mbedTLS entropy falls back to a weak/non-HW source, generated keys are weak (verify `MBEDTLS_ENTROPY_*` settings).
- RA8E1: none (no files compiled). Remediation: delete the empty files or rename config `mbedtls-sw`; hardware path is a deferral (RSIP port). Class: deferral / validation gap.

## 4. Verified correct

- OV5640 I2C address 0x3C (A/ra_ov5640.c:39) = FSP `REG_CAM_I2C_SLAVE_ADDR 0x3C` (`camera_sensor.h:130`); 400 kHz; 2-lane MIPI `0x300E=0x45`.
- Reset pin P709 low→high pulse (E/src/ra8p1_mipi_csi.c; board.h:432) = FSP `camera_sensor.c:384-386`. P705 PWDN extra, harmless.
- ELC events `RA_ELC_MIPICSI_RX 0x38F`, `RA_ELC_VIN_IRQ 0x395` (ra8p1_irq.h:633,638) = FSP `bsp_elc.h:530,535`.
- MSTP MIPI_CSI = MSTPCRC bit 17 (ra_mstp.c:157) = FSP `bsp_module_stop.h:321`. VIN = MSTPCRC bit 16 (ra_mstp.c:159) not cross-checked (no FSP VIN macro found).
- Lane count 2 and VC 0 match FSP.

## 5. Rejected paths / dead code

- Rejected: RA8E1 CEU exposure (different IP, not in scope).
- Dead: `ra_mbed_crypto.*`, `ra8p1_mbed_crypto.c`; `RA_VIN` Kconfig (no code gate); `CONFIG_VIDEO*` in `mipi-csi` (unused by driver).

## 6. Evidence tier / verdict

| Driver | Tier | Verdict |
|---|---|---|
| ra_mipi_csi + VIN | E1 | FAIL |
| ra_ov5640 | E1 | DONE_WITH_CONCERNS |
| ra_mbed_crypto | E0 (stub) | BLOCKED (no implementation) |

ELF layer for `mipi-csi`, `mbed-crypto`: not built (user declined builds).

## 7. Unresolved questions

1. Which camera module/connector is fitted on the target EK (OV5640 per FSP)? Confirms CAM-02 format choice.
2. Is hardware crypto (RSIP/PSA) in scope, or is `mbed-crypto` meant as a software self-test only?
3. mbedTLS entropy source in `mbed-crypto` build (not inspected in apps `ee45eec37`).
