# Phase 1 — Source-Proven Driver Fixes

## Context

- [Plan](plan.md)
- [Mission 1 audit](../reports/audit-260809-rzv2h-adc-ether-phy-scif-mission1-report.md)
- [Reference source map](../../docs/renesas/reference-source-map.md)

## Requirements

- ADC: preserve byte-width `ADELCCR` access.
- Ethernet/PHY: restore descriptor ABI/coherency, network locking, safe mode resolution, role-neutral gigabit detection, unsigned MMIO masks.
- SCIF: preserve signed ICU IDs, reject invalid baud before mutation, bound ISR diagnostics, prevent SCI-B fallback under SCIF console.
- Apply SCIFA clock/reset/MSTOP only from core-matched generated authority.

## Files

- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_adc.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ether.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ether.h`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_ether_phy.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/hardware/rzv_ether.h`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_scif.c`
- `platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_lowputc.c`
- SCIFA CPG files only if generated evidence fully defines the contract.
- `test/rzv2h_adc_ether_scif_contract_test.py`

## Implementation

- [x] Route `ADELCCR` through an 8-bit accessor.
- [x] Apply source-only Ethernet/PHY corrections.
- [x] Restore a hardware-compatible descriptor stride with coherent ownership.
- [x] Apply source-only SCIF corrections.
- [x] Add SCIFA CPG support from core-matched generated authority.
- [x] Add source-contract regression tests.

## Validation

- `python3 test/rzv2h_adc_ether_scif_contract_test.py -v`
- `python3 -m unittest discover -s test -p 'rzv2h_*_contract_test.py' -v`
- Cortex-R8 syntax checks for touched translation units.
- Focused `rdk-rzv2h:adc`, `rdk-rzv2h:ether`, and `nsh-scif` builds where clean-tree tooling permits.
- `git diff --check` and source-contract side-effect sweep.

## Risks and Rollback

- DMA coherency and live link transitions require HIL; do not mark runtime-validated from builds.
- Clock, pin, interrupt-event, and PHY timing literals stay blocked without authority.
- Revert only the affected driver hunk if a focused build or contract fails; preserve unrelated dirty-tree changes.

## Unresolved Questions

- Exact GBETH CPG, pinmux, and per-channel event mapping for CR8?
- RDK PHY revision, straps, and RGMII delay ownership?
- SCIFA0 package pins and board routing?
