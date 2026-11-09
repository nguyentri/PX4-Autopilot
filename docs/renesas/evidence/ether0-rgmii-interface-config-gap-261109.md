# ether0 MAC TX stall: RGMII interface configuration gap (2026-11-09)

Scope: RDK-RZ/V2H CR8-0, NuttX `rzv_ether.c`, `ether-mac-loopback-rtt` and
`ether0-board-rtt` profiles. This record compares source code only. The
register values below come from the
[2026-11-09 hardware run](rtt-hil-demo-hardware-run-261109.md), and this
analysis made no new board access. **The cause is inferred and untested on
the board.** It does not change any status tier.

## Finding

The GBETH0 MAC is stuck in its transmit clock domain, not in the DMA. FSP
4.2.0 and the Renesas GbEther reference both configure the RGMII interface
glue outside the Synopsys MAC before they use it. NuttX does not program any
of these three registers:

| Register (SVD offset) | Field | FSP / reference value | NuttX |
|---|---|---|---|
| `SYS_GBETH0_CFG` (SYSC + 0xF00) | `PHY_INTF_TYPE` [18:16] | 1 = RGMII | defined in `rzv_sysc.h`, never written |
| `PFC_OEN` (GPIO + 0x3C20, PWPR-protected) | `OEN0` [0] | 0 = ET0_TXC_TX_CLK pad output (RGMII) | defined in `rzv_gpio.h`, never written |
| `CPG_SSEL0` (CPG + 0x2F0) | bit 12 (SVD `SELCTL3`) | FSP ORs in 0x1000 for RGMII | only logged by `rzv_clock.c`, never written |

The NuttX driver sets the MAC speed bits and the CSDIV0 divider. That explains
why changing them in the 2026-11-09 run had no effect.

## Register state at the stall (observed)

| Register | Value | Decode |
|---|---|---|
| MAC_DEBUG (0x114) | 0x00020000 | TFCSTS[18:17] = 01: the TX frame controller waits for the previous frame's status or for the IFG/backoff to end. TPESTS = 0, RX side idle. |
| MAC_CONFIGURATION | LM, DM, PS, FES, TE, RE set | Full duplex, so there is no backoff or deferral. Only the TX-domain handshake is left to wait on. |
| MTL_TXQ0_DEBUG | 0x00010012 | One packet queued, queue not empty, read state: the frame reached the MAC interface. |
| DMA_CH0_STATUS | 0x500 | TX/RX DMA running, no bus error (descriptors in non-cached DDR). |
| RX descriptor 0 des3 | 0xc1000000 | Still OWN: nothing was looped back. |
| CPG CLKON11 / CLKMON5 / CSDIV0 | 0x3FFF / all set / 0 | ETH0 TX/RX/TX180/RX180 gates on, 1000M divider. |

A clock gate that is on and running proves only that the gate is open. It
does not show which source SSEL selected, whether the TXC/RXC pads carry a
clock, or which interface mode the MAC latched.

## Source references

- FSP `R_ETHER_PHY_Open`
  (`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/r_ether_phy/r_ether_phy.c:336-349`):
  - For RGMII it calls `R_BSP_EthernetModeCfg(channel, BSP_ETHERNET_MODE_RMII)`.
    The enum value is 0 and misnamed: here it means RGMII.
  - It then sets `SYS_GBETHn_CFG.PHY_INTF_TYPE = (mii_type == RGMII)`.
- FSP `R_BSP_EthernetModeCfg`
  (`refs/rz-fsp-4.2.0/rzv/rz/fsp/src/bsp/mcu/all/bsp_io.h:624-650`):
  - In RGMII mode it ORs `BSP_FEATURE_IOPORT_PRV_SET_SSEL0_SELCTL2` (0x1000)
    into `CPG_SSEL0` for channel 0, and `..._SSEL1_SELCTL0` (0x0100) into
    `CPG_SSEL1` for channel 1. It does not set the WEN bit.
  - It then unlocks PWPR, writes `PFC_OEN.OENn = mode` (0 for RGMII), and
    relocks PWPR.
- Renesas GbEther reference
  (`refs/rzv2h_gb_ether/plat/ether/EtherMain.c:271-302`):
  - It sets `SYS_AOF24` bit 8 for DDR0 address translation.
  - It clears OEN0/OEN1 at `GPIO + 0x3C40`, with the comment "OUT (RGMII
    mode) … Use PLL clock for clk_tx_i only for RGMII mode".

## Source conflicts

- **SSEL bit names.** The SVD and the CMSIS bit masks name SSEL0 bit 12
  `SELCTL3`, but FSP's macro for the same 0x1000 value is named
  `SELCTL2`. Likewise, FSP's SSEL1 value 0x0100 is bit 8. Which clock mux bit
  12 selects (taken here to be the GBE0 RX clock from ET0_RXC) is inferred
  from the FSP RGMII context, not from the hardware manual.
- **PFC_OEN offset.** FSP, the SVD and NuttX put PFC_OEN at GPIO + 0x3C20,
  while the GbEther reference uses GPIO + 0x3C40. This may be a
  silicon-revision difference.

## Ranked hypotheses

| # | Hypothesis | Confidence |
|---|---|---|
| 1 | `PHY_INTF_TYPE` is not RGMII, so the MAC latched a GMII/MII interface and its TX path waits on a clock or handshake that never arrives. It has to be written before the GBETH or DMA software reset that samples it. | Medium |
| 2 | `OEN0` = 1 leaves the TXC pad as an input, so the TX clock loop through the pad is broken. | Medium |
| 3 | SSEL0 bit 12 = 0 sources the RX clock from CSDIV instead of the PHY RXC. This fits the `ether0-board-rtt` RX failure better than the TX stall. | Low-medium for the TX stall |
| 4 | Another fault stalls the TX status return, such as `SYS_AOF24` or the TX FIFO size. DDR descriptor fetches already work without a bus error. | Low |
| — | Half-duplex backoff, or a speed/divider mismatch | Excluded (DM=1; 100M and 1000M failed identically) |

## Discriminating board check (not yet run)

1. **Read only, no change.** With the `ether-mac-loopback-rtt` ELF at the
   prompt, read the following and add the values to this record:
   - `SYS_GBETH0_CFG`
   - `CPG_SSEL0`
   - `PFC_OEN` at both GPIO + 0x3C20 and GPIO + 0x3C40
   - `PWPR` (GPIO + 0x3BE4)

   This alone confirms or rules out hypotheses 1-3.
2. **Driver change.** Before the MAC reset in the GBETH bring-up:
   - set `PHY_INTF_TYPE = 1`;
   - unlock PWPR, clear `OEN0`, and relock;
   - set SSEL0 bit 12 together with its WEN bit 28, then verify the readback.
3. **Rerun the profiles.** Rerun `ether-mac-loopback-rtt`. It passes when RX
   descriptor 0 OWN clears and MAC_DEBUG returns to 0. Then rerun
   `ether0-board-rtt` against the PHY.

## Unresolved

- What are the reset values of `PHY_INTF_TYPE`, `CPG_SSEL0` and `PFC_OEN`?
  Neither the SVD nor FSP gives them.
- Is PFC_OEN at GPIO + 0x3C20 or GPIO + 0x3C40?
- Does an SSEL write need its WEN bit? FSP writes without it.
- Does internal loopback (LM=1) still need a valid `PHY_INTF_TYPE` or the
  external RXC?
- Is `PHY_INTF_TYPE` sampled at the CPG GBETH reset, at the DMA software
  reset, or at both?
