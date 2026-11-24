---
phase: 8
title: "Phase 8: CANFD, Ethernet, USB device"
status: pending
priority: P2
effort: "1.5d"
dependencies: [3]
---

# Phase 8: Connectivity (CM85)

## Scope
- Modules: `ra_canfd.c`; `ra_ether.c`, `ra_ether_rmac.c`, `ra_ether_phy.c` and the five `ra_ether_phy_*.c`; `ra_usbdev.c` + `ra8_usbdev.h`
- Board glue: `ra8p1_canfd.c`, `ra8p1_ether.c`, `ra8p1_usb.c`
- Configs: `canfd`, `ether`, `usb-pcdc`
- FSP: `r_canfd` (`can_fd`, the only carrier); `r_rmac`, `r_rmac_phy` and `r_layer3_switch` (`ethernet`); `r_usb_basic` + `r_usb_pcdc` (`usb_pcdc`, `usb_phid`)

## Tasks & Steps
1. CANFD: nominal and data bit timing from the real CANFD clock, the RX FIFO/TX buffer mapping, error/bus-off recovery and the upper-half (`can` or SocketCAN) contract.
2. Ethernet: the RA8P1 IP is RMAC + ESWM/layer3 switch, not the RA8E1 ETHERC/EDMAC. Check that `ra_ether.c` uses RMAC on RA8P1 and that `ra_ether_rmac.c` follows the `r_rmac` descriptor and chain rules. Check the EK PHY part and address against the selected `RA_ETHERNET_PHY_*` and `configuration.xml`. Check cache maintenance on the descriptors.
3. USB: which controller `ra_usbdev.c` drives (USBFS vs USBHS), the clock/PLL source, the FIFO/pipe mapping, and the CDC-ACM consumer.
4. Flag PHY drivers that no EK configuration uses as dead code.

## Deliverable
`plans/261124-1323-ra8-nuttx-driver-audit/reports/audit-connectivity.md`
