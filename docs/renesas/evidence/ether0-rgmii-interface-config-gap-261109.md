# ether0 MAC TX stall: RGMII interface configuration gap (2026-11-09)

Scope: RDK-RZ/V2H CR8-0, NuttX `rzv_ether.c`, `ether-mac-loopback-rtt` and
`ether0-board-rtt` profiles. This record compares the source code first. The
stall-time register values come from the
[2026-11-09 hardware run](rtt-hil-demo-hardware-run-261109.md). A read-only
board check of the interface registers followed the same day (see
[Board readback](#board-readback-2026-11-09)). It rules out two of the three
gaps and leaves `PFC_OEN.OEN0` as the leading cause. **No fix has been tried
on the board yet.** This record does not change any status tier.

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
- **PFC_OEN offset (resolved).** FSP, the SVD and NuttX put PFC_OEN at GPIO
  + 0x3C20 from a GPIO base of 0x10410020. The GbEther reference writes
  `BASE_ADDRESS_GPIO + 0x3C40` from a base of 0x10410000
  (`refs/rzv2h_gb_ether/include/rzv2h_base_addr.h:8-18`,
  `plat/include/ether_register.h:21`). Both name the same address,
  0x10413C40. The reference clears OEN0 and OEN1 (mask 0x3) and polls the
  readback until both read 0.

## Ranked hypotheses

The ranking below includes the board readback. The source-only confidence
is in parentheses.

| # | Hypothesis | Confidence |
|---|---|---|
| 2 | `OEN0` = 1 leaves the TXC pad as an input, so the TX clock loop through the pad is broken. The board reads OEN0 = 1, and the stall reproduces with that value. | **Leading** (medium) |
| 4 | Another fault stalls the TX status return, such as `SYS_AOF24` or the TX FIFO size. DDR descriptor fetches already work without a bus error. | Low |
| 1 | `PHY_INTF_TYPE` is not RGMII, so the MAC latched a GMII/MII interface. | Excluded: it reads 1 = RGMII (medium) |
| 3 | SSEL0 bit 12 = 0 sources the RX clock from CSDIV instead of the PHY RXC. | Excluded: bit 12 reads 1 (low-medium) |
| — | Half-duplex backoff, or a speed/divider mismatch | Excluded (DM=1; 100M and 1000M failed identically) |

## Board readback (2026-11-09)

Under the AGENTS.md standing board grant, the `ether-mac-loopback-rtt` ELF
(sha256 prefix `3f196f9a9e6508ec`, `_SEGGER_RTT` 0x081a2400) was RAM-loaded
on CR8-0 with `rzv2h-load-one-core.sh`. CR8-0 was held in reset after the
earlier `reboot`; the loader started it, loaded the ELF and verified it. The
CM33 was not connected. Every read used `jlink-gdb-oneshot.py` (read-only,
`-noreset -noir`). No J-Link log showed a reset, DBGEN or connect-failure
marker, and NuttX never writes these registers.

| Register (address) | Before `hwtest` | After `hwtest` | SVD decode |
|---|---|---|---|
| `SYS_GBETH0_CFG` (0x10430F00) | 0x00010000 | 0x00010000 | `PHY_INTF_TYPE` = 1 (RGMII), `MAC_SPEED` = 0 |
| `SYS_GBETH1_CFG` (0x10430F04) | 0x00010000 | — | `PHY_INTF_TYPE` = 1 |
| `CPG_SSEL0` (0x10420300) | 0x00001000 | 0x00001000 | SELCTL3 (bit 12) = 1, every WEN bit 0 |
| `CPG_SSEL1` (0x10420304) | 0x00000010 | — | SELCTL1 (bit 4) = 1 |
| `PFC_OEN` (0x10413C40) | 0x0000003F | 0x0000003F | OEN0-OEN5 = 1: every pad is an input (MII direction) |
| GPIO + 0x3C40 (0x10413C60) | 0x00000000 | — | No SVD register: confirms that 0x10413C40 is the OEN register |
| `PWPR` (0x10413C04) | 0x000000A0 | 0x000000A0 | REGWE_A = 0 (OEN locked), REGWE_B = 1 |
| `CPG_CLKON_11` / `CLKMON_5` | — | 0x0000FFFF / 0x7FFFFFFF | ETH0 gates on and running |
| `CPG_RST_11` / `RSTMON_5` | — | 0x0000FFFF / 0x00000000 | GBETH resets released |

`hwtest` reproduced the stall with these values:

```text
TEST: ether.function_mac_loopback START
Clock enabled: domain=11 bit=8
Reset deasserted: domain=11 mask=0x1
GBETH0 initialized successfully
TEST: ether.function_mac_loopback FAIL reason="expected=0 actual=-116"
TEST: ether.function_loopback_cleanup FAIL reason="expected=2 actual=0"
TEST_DONE: exit=1
```

The test cleanup puts the MAC back in reset (MACCR reads 0 afterwards), so
the stall-time MAC state above still comes from the earlier run.
`PHY_INTF_TYPE` and SSEL0 bit 12 already hold the values FSP writes. OEN0
does not: FSP and the reference clear it, and the board leaves it at 1.

The `ether1` values match the `ether0` values, which suggests that 1 is the
reset value of `PHY_INTF_TYPE` rather than a boot-firmware write. That is
inferred: the readback cannot tell the two apart.

## Next board check

1. **Driver change.** In the GBETH bring-up, before the MAC reset:
   - set REGWE_A in PWPR, clear `PFC_OEN.OEN0` (the reference also clears
     OEN1), and restore PWPR;
   - read the OEN register back.

   Leave `PHY_INTF_TYPE` and SSEL0 alone; they already hold the RGMII values.
2. **Rerun the profiles.** Rerun `ether-mac-loopback-rtt`. It passes when RX
   descriptor 0 OWN clears and MAC_DEBUG returns to 0. Then rerun
   `ether0-board-rtt` against the PHY.
3. If the loopback still stalls with OEN0 = 0, look at hypothesis 4
   (`SYS_AOF24`, TX FIFO sizing).

## Unresolved

- Is `PHY_INTF_TYPE` = 1 the reset value, or did the boot firmware write it?
- What is the reset value of `PFC_OEN`? It read 0x3F after boot, and nothing
  in NuttX writes it.
- Does OEN1 also need clearing for ether0? The reference clears both bits.
- Does internal loopback (LM=1) need the TXC pad driven, or is OEN0 only an
  external-path setting? The step 1 result answers this.
- Does an SSEL write need its WEN bit? This no longer matters for ether0,
  since SSEL0 bit 12 is already set.
