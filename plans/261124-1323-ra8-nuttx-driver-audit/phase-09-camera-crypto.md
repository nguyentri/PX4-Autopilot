---
phase: 9
title: "Phase 9: MIPI CSI + OV5640, mbed crypto"
status: pending
priority: P3
effort: "0.5d"
dependencies: [3]
---

# Phase 9: Camera and crypto (CM85)

## Scope
- Modules: `ra_mipi_csi.c`, `ra_ov5640.c`, `ra_mbed_crypto.c` (0 lines) + `ra_mbed_crypto.h`
- Board glue: `ra8p1_mipi_csi.c`, `ra8p1_mbed_crypto.c`
- Configs: `mipi-csi`, `mbed-crypto`
- FSP: `r_mipi_csi`, `r_mipi_phy` and `r_vin` (`mipi_csi`, `_quickstart`); `r_sce` (`mbed_crypto`)

## Tasks & Steps
1. MIPI CSI: PHY/lane configuration, VIN buffer placement, cache invalidate before the CPU reads a frame, and the OV5640 I2C address and init table vs the FSP sample's sensor. Check what the EK camera module actually is.
2. Is `ra_ov5640.c`, a sensor driver inside arch/, a layering finding?
3. mbed crypto: the source is empty. Trace what `mbed-crypto` actually builds and links (the board file, apps, the `r_sce` dependency). Classify the result as stub, missing or misleading config.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-camera-crypto.md`
