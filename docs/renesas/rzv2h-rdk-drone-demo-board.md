# RDK-RZ/V2H Drone Demo Board: 3-Layer Hardware Build Guide

**Date:** 2026-11-23
**Status:** Build guide for the hardware engineer. Nothing below is on-target proof.
**Firmware it must run unchanged:** CR8-0 `renesas_rdk-rzv2h_demo`
([demo.px4board](../../boards/renesas/rdk-rzv2h/demo.px4board),
[rc.board_sensors](../../boards/renesas/rdk-rzv2h/init/demo/rc.board_sensors),
[pin ownership](./pinmap.md#pin-ownership-by-profile))
**Layer 3 sources:** [schematic SCH-20260708 V1.0](./Extension%20board%20for%20drone_SCH-20260708%201.pdf);
PCB, BOM and schematic `refs/Extension Board for drone PoC-20260713/` (local, gitignored)
**Header source:** [RDK 40-pin drawing](./rzv2h-rdk-40_pin_header_pin.png)
**Reference build:** `refs/rzv2h_drone_px4-dev/docs/HARDWARE.md` and its photos (S500 frame; older ribbon-cabled perfboard, newer PoC board plugged on the RDK)
**3D render diagrams:** [rzv2h-rdk-drone-demo-3d-render-diagrams.md](./rzv2h-rdk-drone-demo-3d-render-diagrams.md)

This guide tells you how to build and wire the three boards: power, ground,
every sensor pin, and the address and mode straps. The finished stack runs
the demo image as a single-core FMU (CR8-1 disabled). It should fly from
QGroundControl with an SBUS RC transmitter, first tethered or props-off.

## 1. Stack and roles

```text
 Layer 3  Extension board for drone (PoC-20260713), BARE PCB populated as connectors-only
          CN1 PM03D 5 V in │ CN2 GPS M10 │ CN3 SiK radio │ CN4 TFmini Plus │ CN5 fs-a8s RC
          H1 4x ESC signal │ H2 spare │ U1/U4/SW1 SBUS level shift + inverter
             ▲ J1 holes: Layer 2 stacking-header tails soldered through (J1 socket not fitted, §4.1)
 Layer 2  Custom sensor shield (replaces the Arduino Uno R3 Proto Shield)
          M1 ICM-45686 (SPI0, INT1→P94) │ M2 BMM150 + M3 BMP280 (SCI7 I2C) │ M4 ADS1115 (SCI0 I2C)
             ▲ stacking-header socket, plugs onto RDK J1 male pins (not soldered)
 Layer 1  RDK-RZ/V2H, CR8-0 = PX4 FMU, powered from the drone battery (PM03D 12 V), J-Link/RTT console
```

| Layer | Carries | Does not carry |
|---|---|---|
| 1 RDK | SoC, 3.3 V for every logic part, J-Link | Any 5 V peripheral load |
| 2 Custom shield | IMU, magnetometer, barometer and ADC breakout modules; their pull-ups and decoupling | Any 5 V net, any connector to the airframe |
| 3 Extension board | All airframe connectors (GPS, lidar, radio, RC, ESC, PM03D 5 V), the 5 V peripheral rail, the SBUS level shifter | Any IMU, baro or mag (all footprints empty) |

Every one of the 40 J1 nets passes straight through Layer 2 (pin N to pin N).
The external devices (GPS, TFmini, SiK, fs-a8s, ESCs) are mounted on the
airframe and plug into Layer 3. The breakout modules are fitted on Layer 2.

The reference build differs. It joins the RDK to a perfboard with a 40-pin
ribbon, uses an MPU9250, feeds the sensors from an AMS1117 3.3 V regulator,
inverts SBUS with a C1815 transistor, and routes the IMU INT to pin 22 (P50).
This stack replaces all of that with the Layer 3 PCB and the RDK 3V3 rail,
and P50 is SCI0 SDA here.

## 2. Design rules (read first)

| # | Rule | Why |
|---|---|---|
| R1 | All RDK pads are **3.3 V logic and not 5 V tolerant**. No 5 V signal or pull-up may reach any J1 pin. | Damage to the SoC |
| R2 | Layer 2 modules are powered **only from 3V3** (J1 pins 1/17). Never use a "5 V" module input or a 5 V-referenced pull-up. | A module fed 5 V pulls SDA/SCL to 5 V and breaks R1 |
| R3 | 5 V peripherals (GPS, TFmini Plus, SiK, fs-a8s) run only from the Layer 3 **+5V rail**, fed by the PM03D 5 V output through CN1. | Reference power split; keeps the RDK rail clean |
| R4 | Layer 3 **R3 is DNP**. The Layer 3 +5V rail never connects to RDK 5V (J1 pins 2/4). | The RDK makes its own 5 V from the 12 V input; two sources in parallel back-feed it |
| R5 | Only **BMM150 0x10 and BMP280 0x76** sit on SCI7 (P76/P77, PX4 bus 7). The I2C wires in the GPS and PM03D cables are cut. | One owner per address; the firmware starts only these two |
| R6 | Only the **ADS1115 at 0x48** sits on SCI0 (P50 SDA, P51 SCL, PX4 bus 0). It is temporary; a battery management IC replaces it later. | `ads1115 -X -b 0` is the only SCI0 driver started |
| R7 | All Layer 3 IMU, baro and mag footprints stay **empty**, together with their passives | Their nets are the same as Layer 2's (P93 CS, 0x76, 0x10) |
| R8 | The RDK is never soldered. Layer 1 to Layer 2 is a socket. | The RDK must stay replaceable and debuggable |
| R9 | Never load a `default` or NuttX button/DRDY sample image onto this stack. | `default` drives P94 as SPI CS1, which fights M1 INT1 |

## 3. Power tree

The RDK is powered from the drone battery in flight, as in the reference build.

```text
 4S LiPo (5300 mAh) ──► PM03D ──┬── main power out ──────────► 4x ESC power leads (never through the stack)
                                │
                                ├── 12 V out (8 V/12 V switch at 12 V) ──► RDK DC barrel jack (Layer 1)
                                │
                                └── CLIK-Mate 5 V ──► Layer 3 CN1-1/2 (+5V), CN1-5/6 (GND)
                                                        │  Layer 3 +5V rail
                                                        ├── CN2-1  GPS M10            5 V
                                                        ├── CN3-6  SiK radio          5 V
                                                        ├── CN4-4  TFmini Plus        5 V
                                                        ├── CN5-1  fs-a8s receiver    5 V
                                                        ├── H2-2   spare
                                                        ╳── R3 DNP: no link to RDK 5 V (J1-2/4)
                                                        ╳── H1 middle row NC: ESC BEC red wires go nowhere

 RDK ──► J1-1 / J1-17 +3V3  (one net, through Layer 2 to Layer 3)
            ├── Layer 2: M1 ICM-45686, M2 BMM150, M3 BMP280, M4 ADS1115,
            │            P93/P50/P51 pull-ups, bulk 10 µF
            └── Layer 3: U1/U4 level shifter VCC, CN2-8 via R12 (GPS LED/switch), H2-4

 GND: J1-6, 9, 14, 20, 25, 30, 34, 39 joined on every layer. The PM03D ground reaches
      the stack twice (CN1-5/6 and the RDK jack return); both come from the same PM03D.
```

**Bench, props-off, no battery:**
- Feed the RDK from a 12 V bench supply into its barrel jack.
- Feed a current-limited (1 A) 5 V bench supply into CN1-1/2 (+) and CN1-5/6 (−) through a CLIK-Mate pigtail.
- Tie the two bench supply grounds together.

**Before the first battery connection:** with the RDK unplugged, measure the
PM03D 12 V output at the barrel plug (centre and sleeve polarity, 11.5–12.5 V)
and the 5 V output at CN1.

### 3.1 Supply per device

| Device | Layer | Supply | Source pin | Typical current | Logic level on J1 |
|---|---|---|---|---|---|
| RDK-RZ/V2H | 1 | 12 V (jack accepts 12–24 V) | PM03D 12 V out | adapter class 12 V/2 A; supply must allow up to 24 V/5 A peak | — |
| ICM-45686 module | 2 | 3.3 V (VDD and VDDIO) | J1-1/17 | <1 mA | 3.3 V |
| BMM150 module (Waveshare) | 2 | 3.3 V on VCC (onboard LDO; never 5 V, R1) | J1-1/17 | ≈4 mA, of which ≈2.8 mA flows in the two address-strap pull-ups | 3.3 V |
| BMP280 module (GY-BMP280-3.3) | 2 | 3.3 V only (no regulator) | J1-1/17 | <1 mA | 3.3 V |
| ADS1115 module | 2 | 3.3 V | J1-1/17 | <1 mA | 3.3 V |
| SN74LV1T126 / SN74LV1T04 (U1/U4) | 3 | 3.3 V | J1-1/17 | <1 mA | in: 5 V tolerant, out: 3.3 V |
| u-blox M10 GPS | 3 via CN2 | 5 V | +5V rail | ~50 mA | 3.3 V UART |
| TFmini Plus lidar | 3 via CN4 | 5 V (4.5–6 V) | +5V rail | ~110 mA avg, higher peaks | 3.3 V UART |
| SiK telemetry v3 | 3 via CN3 | 5 V | +5V rail | ~100 mA while transmitting | 3.3 V UART |
| FlySky fs-a8s | 3 via CN5 | 5 V | +5V rail | ~30 mA | SBUS, shifted to 3.3 V by U1/U4 |
| 4x SkyWalker 40A ESC | 3 via H1 | battery (PM03D main out) | not from the stack | — | 3.3 V PWM from RZ (verify ESC accepts it) |

Budget: the 3V3 load is under 20 mA. +5V is about 300 mA average; size the source for 1 A.

**RDK side, from the RDK documents** (`docs/renesas/WS125_Robotic_Development_Kit_User_Manual.pdf`
pp. 6 and 11; `docs/renesas/V2H Robot RDK_SCH-20250624.pdf` pp. 2 and 17):
- The DC jack takes 12–24 V. The manual names 12 V/2 A or 24 V/1 A adapters and says the supply must satisfy a 24 V/5 A maximum. At 12 V from the PM03D, budget at least 2 A; the user confirmed the PM03D 12 V output meets this and its plug fits the jack.
- J1-1/17 (3V3) is the PMIC `D3.3V` rail, 3.5 A maximum, shared with the RDK itself. The stack's <20 mA is negligible.
- J1-2/4 (5V) is `D5.0V2`, a separate 5 V/5 A buck that also feeds the USB ports through a load switch. The stack does not use it (R4).
- SCI7 already has 2.2 kΩ pull-ups to `D3.3V` on the RDK (R180/R181).

## 4. Layer 2: custom sensor shield

### 4.1 Board and stacking

**Outline: full Raspberry Pi HAT size, 65.0 × 56.5 mm.** The header edge copies the Layer 3 PCB:
- J1 centre is on the board centreline (32.6 mm from the left edge) and 3.8 mm from the long edge.
- In the PCB file view (header edge at the top), pin 1 is on the inner row at the left end. Pins 2/4 (5 V) are on the row next to the board edge.
- Two Ø2.75 mm (M2.5) mounting holes on the J1 centreline, 3.5 mm in from each short edge (58.0 mm apart).
- These numbers match the Raspberry Pi HAT format: 65 mm wide, holes 58 mm apart and 3.5 mm in.

Layer 2 is 16.5 mm deeper than Layer 3 (40 mm). The extra strip:
- has nothing above it;
- carries the M2 compass, J4 and the test pads (§4.4.2);
- has two more M2.5 holes over the RDK's far hole pair, 49 mm from the header-edge holes (*est.*, §8). Layer 2 therefore stands on four standoffs.

The 40 mm outline cannot hold the 29 × 20 mm Waveshare BMM150 module (§5.2)
next to M1, M3 and M4 without entering a keep-out.

With every board face-up, pin N must sit over RDK pin N. The reference photo
`refs/rzv2h_drone_px4-dev/docs/assets/real_drone_top1.png` supports this. It shows
the populated PoC:
- face-up, with its silkscreen readable;
- with the J1 socket body under the board, plugged straight onto the RDK header;
- with brass M2.5 standoffs at both J1 ends going down to the RDK.

Still confirm it by continuity (§9 checks 2 and 4) before anything is soldered.

**Layer 3 J1 finding:** the PoC places J1 (Harwin M20-7812045, 2x20 *female*,
8.4 mm) on the **top** side, facing up. Fitted as placed, it cannot mate
with anything below it; the reference build fitted it on the bottom instead
(photo above). Use one of these joints:

| Joint | How | Result |
|---|---|---|
| **A, soldered (default)** | Leave J1 unfitted. The Layer 2 stacking-header tails pass up through the Layer 3 J1 holes and are soldered on the Layer 3 top. | Permanent Layer 2 + 3 assembly, lowest height |
| B, plug-on | Fit the J1 socket on the Layer 3 **bottom** instead (same holes, same pin numbers). The Layer 2 tails plug into it. | Layer 3 removable; about 11 mm between Layer 2 and Layer 3 |

**Layer 2 parts per joint:**
- **J2:** one 2x20 2.54 mm stacking header (female body, long male tails), inserted from the **bottom**. The socket body plugs onto the RDK J1 male pins and the tails come out of the Layer 2 top. There is only one set of 40 holes, so two separate headers cannot be used.
- **Tail length for A:** at least 3.2 mm (two PCBs) plus the Layer 2 to Layer 3 gap plus 1.5 mm of protrusion. The chosen 10 mm gap (§4.4.4) needs ≥14.7 mm of tail above the J2 body; an 8 mm gap needs ≥12.7 mm.
- **Tail length for B:** at least 6 mm above the Layer 2 top surface.
- Set the gap with M2.5 standoffs in the two header-edge holes. The header must never carry the stack's weight.

**Order and height:**
- Fit and test the Layer 2 modules (§9 checks 2–3) **before** joint A is soldered, because it is permanent.
- Every Layer 2 top-side part must clear the Layer 3 bottom (and its THT pins) by ≥1 mm.
- The Layer 2 bottom must clear the RDK components under the 65 × 56.5 mm footprint.
- Build on a 2-layer PCB (a perfboard prototype is also acceptable), with a bottom-side GND pour tied to all eight J1 GND pins.
- Placement zones, keep-outs, heights and the assembly sequence are in §4.4.

### 4.2 Parts

| Ref | Part | Qty | Notes |
|---|---|---|---|
| J2 | 2x20 2.54 mm stacking header, long tails, inserted from the bottom | 1 | §4.1 |
| M1 | ICM-45686 breakout, SPI pins and INT1 exposed, 3.3 V | 1 | §5.1 |
| M2 | Waveshare BMM150 3-Axis Magnetometer Sensor, 29 × 20 mm, I2C | 1 | §4.4.5, §5.2. Strap A0/SDO and A1/CS to GND for 0x10. Remove its right-angle header. Fix it with two nylon M2 screws, nuts and 2.5 mm spacers. |
| M3 | GY-BMP280-3.3 module, 11.5 × 14.5 mm, 3.3 V only, I2C/SPI | 1 | §4.4.5, §5.3. Remove its SDA/SCL pull-ups (§5.4). Not the 5 V GY-BMP280 variant with a regulator. |
| M4 | ADS1115 breakout, 3.3 V, on a low-profile machined-pin female socket so it can be swapped for the battery IC | 1 | §5.5. A standard 8.5 mm female socket is too tall (§4.4.4). |
| J4 | 1x5 2.54 mm straight header: A0, A1, A2, A3, GND | 1 | ADS1115 inputs, 0–3.3 V only. It is in the strip past Layer 3 (§4.4.2), so it stays reachable. |
| R1 | 10 kΩ, P93 to 3V3 | 1 | Keeps IMU CS high during boot; omit if M1 already pulls CS up |
| R2, R3 | 4.7 kΩ, P50 to 3V3 and P51 to 3V3 | 2 | SCI0 has no pull-ups on the RDK |
| R4 | 1 kΩ in series, M1 INT1 to P94 | 1 | Limits current if a wrong image drives P94 (R9) |
| C1 | 10 µF, 3V3 to GND at J2 pin 1/17 | 1 | Bulk |
| C2–C5 | 100 nF, 3V3 to GND at each module VDD pin | 4 | If the module has none |
| TP1–TP10 | Test pads: 3V3, GND, SCK, MOSI, MISO, CS, SDA7, SCL7, SDA0, SCL0 | 10 | Logic analyzer and meter access, in the strip past Layer 3 (§4.4.2) |
| — | M2.5 standoffs: 4 × 11 mm (RDK to Layer 2) and 2 × 10 mm (Layer 2 to Layer 3), with screws | 1 set | §4.4.4 |

### 4.3 Layer 2 netlist

| Net | J1 pin | Layer 2 connections |
|---|---|---|
| +3V3 | 1, 17 | M1 VDD + VDDIO, M2 VCC (H2-7), M3 VCC + CSB, M4 VDD, R1, R2, R3, C1–C5 |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | M1 GND, M2 GND + A1/CS + A0/SDO (H2-6, H2-2, H2-5), M3 GND + SDO, M4 GND + ADDR, J4-5, C1–C5 |
| SPI0 MOSI | 19 (P90) | M1 SDI |
| SPI0 MISO | 21 (P91) | M1 SDO |
| SPI0 SCK | 23 (P92) | M1 SCLK |
| IMU CS | 24 (P93) | M1 CS, R1 |
| IMU INT1 | 26 (P94) | R4 → M1 INT1 |
| SCI7 SDA | 3 (P76) | M2 SDA/SDI (H2-4), M3 SDI/SDA |
| SCI7 SCL | 5 (P77) | M2 SCL/SCK (H2-3), M3 SCK/SCL |
| SCI0 SDA | 22 (P50) | M4 SDA, R2 |
| SCI0 SCL | 36 (P51) | M4 SCL, R3 |
| ADC inputs | — | M4 A0–A3 → J4-1..4 |
| All other pins | 2, 4, 7, 8, 10–13, 15, 16, 18, 27–29, 31–33, 35, 37, 38, 40 | Pass-through only, no Layer 2 connection |

**Ground routing:**
- Return M1 to J1 pin 20 or 25 (next to the SPI pins).
- Return M2/M3 to J1 pin 6 or 9 (next to the I2C pins), and M4 to pin 34 or 39 (next to P51).
- Keep the SPI wires ≤50 mm with a ground next to them.

### 4.4 Layout and mounting guide

This section tells the hardware engineer where each module goes on Layer 2,
which way it faces, how tall it may be and in which order the stack is built.
The positions come from the Layer 3 PCB file (pad coordinates parsed from
`Extension board for drone_20260713.PcbDoc`) and the RDK documents. Values
marked *est.* come from the RDK manual photo; check them on the real board
before ordering parts.

#### 4.4.1 Reference view and stack orientation

**Reference view.** Every coordinate below is in the **Layer 2 top view**:
- J2 runs along the bottom edge, and J2 pin 1 is at the right end.
- The origin is the bottom-left corner. x runs right (0–65 mm) and y runs away from the header (0–56.5 mm).
- Layer 3 covers y 0–40 only.
- This is the PCB file view rotated by 180°. It matches the reference photo `real_drone_top1.png`.

Fixed features in this view:

| Feature | Position (mm) |
|---|---|
| M2.5 holes (Ø2.75), header edge | (3.5, 3.8) and (61.5, 3.8), shared with Layer 3 |
| M2.5 holes (Ø2.75), far edge | (3.5, 52.8) and (61.5, 52.8), Layer 2 only (*est.*, 49 mm Raspberry Pi pitch) |
| J2 pin 1 (3V3) / pin 2 (5V) | x 56.55; pin 1 on the inner row (y 5.07), pin 2 on the edge row (y 2.53) |
| J2 pin *n* | x = 56.55 − 2.54 × ⌊(*n* − 1) / 2⌋. Odd pins are on the inner row, even pins on the edge row. |
| I2C7 pins 3 / 5 | x 54.0 / 51.5 |
| SPI0 pins 19–26 (MOSI, MISO, SCK, CS, INT1) | x 33.7 to 26.1 |
| SCI0 pins 22 (SDA0) / 36 (SCL0) | x 31.2 / 13.4 |
| J2 pins 39 / 40 | x 8.3 |
| Layer 3 edge | y = 40 |

What lies around and under Layer 2, from the RDK manual top view (p. 7) rotated the same way:
- The RDK Ethernet and stacked USB block is just past the x = 0 edge, with about 1–2 mm to spare (*est.*).
- The RZ/V2H SoC is under the middle of Layer 2, at about y 19–38 (*est.*).
- No fan is fitted on this stack. Leave the RDK 3-pin fan connector empty.
- The RDK is about 86 × 75 mm (*est.*) and uses the Raspberry Pi hole pattern (58 × 49 mm). All four RDK holes are under Layer 2 holes. Only the header-edge pair is also under Layer 3.
- The RDK DC jack is at the RDK corner beyond the x = 65 end and away from J2, outside Layer 2.

**Stack orientation on the frame.** The RDK Ethernet/USB edge points to
**vehicle forward**, as in the reference build. The camera on that edge carries
the live video stream. Then:
- the x = 0 edge of Layer 2 faces forward, so −x is vehicle forward;
- the J2 header edge (y = 0) lies along the vehicle's **left** side, so +y is vehicle right;
- the H1 ESC header on Layer 3 points rearward, and the Layer 3 connectors CN1–CN5 lie along the right side.

If the frame forces a different stack yaw, do not move the modules. Set
`SENS_BOARD_ROT` in QGC (2 = yaw 90°, 4 = yaw 180°, 6 = yaw 270°). It rotates
all internal sensors together. Then verify with §4.4.7.

#### 4.4.2 Placement zones

```text
 Layer 2, top view: J2 row at the bottom, J2 pin 1 at the right end.
 Coordinates in mm from the bottom-left corner. Not to scale; the zone table rules.

 y=56.5 +----------------------------------------------------------------+ far edge
        |  @                                                         @   | = vehicle RIGHT
        |  +----------------------------+   +-- J4 1x5 --+               |
        |  | M2 BMM150 (Waveshare)      |   +------------+               |
        |  | x 7-36, y 36-56            |                                |
        |  | X <- fwd, Y ^ right, -R 0  |   +-- TP1..TP10 ----------+    |
        |  | open above, past Layer 3   |   | x 38-64, y 41-48      |    |
        |  | H2 7-pin row on this edge  |   +-----------------------+    |
 y=40   |..|............................|....... Layer 3 ends ...........|
        |  +----------------------------+                                |
        | +---------------------------+  +-------------+                 |
        | | M4 ADS1115                |  | M3 BMP280   |           ######|
        |#| machined-pin socket       |  | x 35-50     |           # H2 #|
        |#| x 6-34, y 9.5-27.5        |  | y 22.5-34.5 |           ######|
        |#| over SCI0 pins 22 and 36  |  +-------------+ ##########      |
        |#|                           |  +-------------+ #   H1   #      |
        | |                           |  | M1 ICM-45686| #  tails #      |
        | |                           |  | x 35-51     | #        #      |
        | +---------------------------+  +-------------+ ##########      |
        |        R3           R4 R1 R2  C1                               |
        |      39 o o o o o o o o o o o o o o o o o o o o 1              |
        |  @   40 o o o o o o o o o o o o o o o o o o o o 2        @     |
 y=0    +----------------------------------------------------------------+ header edge
       x=0                                                            x=65  = vehicle LEFT

  FORWARD <---- (the RDK Ethernet + USB block sits just past the x=0 edge)
  @ = M2.5 holes   # = keep-out under Layer 3 THT tails (SW1 at the left edge)
```

| Zone | x (mm) | y (mm) | Content | Why here |
|---|---|---|---|---|
| Header strip | 0–65 | 0–7 | J2 tails and the two standoffs only | The tails continue up into Layer 3. The standoffs and nuts need about Ø6 mm. |
| Passive row | 6–52 | 7–9.5 | R4, R1 and R2 next to J2 pins 26, 24 and 22; R3 next to pin 36; C1 next to pin 17 | Pull-ups and the series resistor belong at the pin they serve |
| M4 ADS1115 | 6–34 | 9.5–27.5 | Temporary ADC on its socket | Straight over its SCI0 pins 22 and 36. It is insensitive to heat and stray fields, so it may sit over the SoC. Its 8.5 mm socket height fits under Layer 3 (§4.4.4). |
| M1 ICM-45686 | 35–51 | 9.5–21.5 | IMU | Next to the SPI pins (x 26–34), so the SPI wires stay short, and clear of the H1 keep-out. It is about 10 mm from the stack centre, which PX4 tolerates. |
| M3 BMP280 | 35–50 | 22.5–34.5 | Barometer, GY-BMP280-3.3 (14.5 × 11.5 mm, long edge parallel to J2) | On the I2C7 route from J2 pins 3/5 to M2. Layer 3 covers it against propeller wash. |
| M2 BMM150 | 7–36 | 36–56 | Magnetometer, Waveshare module 29 × 20 | Mostly past the SoC, and ≥20 mm from the Layer 3 CN1 5 V entry (56.5, 36), the H1 ESC header and the RDK DC jack. Only its H2 edge (y 36–40) is under Layer 3. It clears the far hole at (3.5, 52.8). |
| Test pads | 38–64 | 41–48 | TP1–TP10 | Past the Layer 3 edge, so they stay reachable after assembly |
| J4 | 40–53 | 51–54 | Straight 1x5 header | Past the Layer 3 edge and reachable; clear of the far hole at (61.5, 52.8). The ADC inputs carry only microamps, so they do not disturb M2. |
| Spare | 51–58 | 21–40 | — | Clear of the H2 tails |

The zones are sized for the chosen or common modules: about 11–16 mm square for
M1, the 14.5 × 11.5 mm GY-BMP280-3.3 for M3, 28 × 18 mm for M4, and the
29 × 20 mm Waveshare module for M2. If a
module does not fit, move it within these rules, in this order of priority:
1. M2 stays furthest from power wiring, switching current and the SoC.
2. M1 keeps the shortest SPI wires and a rigid mount.
3. Nothing goes into a keep-out (§4.4.3).

#### 4.4.3 Keep-outs

**Under Layer 3 (Layer 2 top side).** Three Layer 3 parts are through-hole.
Their tails stick out of the Layer 3 bottom by about 1.5–2 mm, into the gap
above Layer 2. All other Layer 3 parts are SMD on its top side, so its bottom
is flat elsewhere. Leave these zones empty on Layer 2:

| Layer 3 part | Tail positions (mm) | Layer 2 keep-out (mm) |
|---|---|---|
| H1, 4x3 right-angle ESC header | x 55.8–60.9, y 10.6–18.2 | x 53–64, y 9–20 |
| H2, 2x3 spare header | x 60.7–63.3, y 21.7–26.8 | x 59–65, y 20–28.5 |
| SW1, slide switch | x 3.0, y 18.0–22.0 | x 1–5, y 16–24 |

**Under Layer 2 (bottom side, facing the RDK):**
- Fit no parts on the bottom side. Trim every module and wire tail to ≤1 mm.
- The SoC (no fan; a passive heatsink is optional) and every other RDK part under the 65 × 56.5 mm outline must clear the Layer 2 bottom by ≥1 mm. With the ≈11 mm socket height, that allows about 9 mm. Check it at dry fit (§4.4.6 step 2).
- The Layer 2 front edge (x = 0) must not touch the RDK Ethernet/USB block.

#### 4.4.4 Height budget and standoffs

| Item | Value | How to set it |
|---|---|---|
| RDK top → Layer 2 bottom | ≈11 mm: 2.5 mm RDK header base + 8.5 mm J2 socket body | Seat J2 fully on the RDK, measure, and choose four M2.5 standoffs of that length (11 mm is the usual Raspberry Pi HAT size). The header must not carry the weight. |
| Layer 2 PCB | 1.6 mm | |
| Layer 2 → Layer 3 gap G | **10 mm (chosen)**: M2.5 × 10 mm female-female standoffs on the two header-edge holes | G ≥ tallest Layer 2 part under Layer 3 + 1 mm. No part sits under a Layer 3 tail, so the tails do not add to G. |
| Layer 3 PCB | 1.6 mm | |
| J2 tail above its body (joint A) | ≥ 3.2 mm + G + 1.5 mm, so **≥14.7 mm** | Order the stacking header by tail length (for example the Samtec ESQ family) and confirm the length in its datasheet |

Typical part heights above the Layer 2 top surface:
- A breakout soldered on its own male header with the plastic spacer down: about 5–5.5 mm. That is a 2.5 mm spacer, a 1.6 mm PCB and about 1 mm of parts.
- M4 in a machined-pin (round) socket: about 8.5 mm, about 3 mm of socket plus 5.5 mm. It fits G = 10 with 1.5 mm to spare.
- M4 in a standard 8.5 mm female socket: about 14 mm. It does **not** fit; do not use one.
- M2 and the test pads and J4 in the strip past Layer 3 (y > 40) have no height limit. Only M2's H2 edge (y 36–40) is under Layer 3, and it is about 5 mm tall.

If a stacking header with a ≥14.7 mm tail cannot be bought, fall back to
G = 8 mm (tail ≥12.7 mm). Then solder M4 directly on its header instead of
a socket. Swapping it for the battery IC then means desoldering it.

#### 4.4.5 How to mount each module

**All modules:** solder each one flat, component side up, on its own male
header. The header pins pass through Layer 2 and are soldered on the bottom.
Never use foam tape or hot glue as the only support.

**M1 ICM-45686:**
- Mount it rigidly. Solder every header pin, and optionally add a dot of rigid epoxy under the module edge.
- Do not soft-mount the IMU alone; that adds resonance. The whole stack is soft-mounted to the frame instead (§8).
- Align the module edges parallel to J2 within about 2°. QGC level calibration removes the small residual tilt.
- **Axes:**
  - The module's X arrow points **left, toward the J2 pin 39/40 end**, which is vehicle forward.
  - Its Y arrow points **down, toward J2**, which is vehicle left.
  - Its Z axis points up, out of the board.
  - This is `-R 0`: the driver maps chip +x forward, +y left, +z up to the PX4 body frame (`ICM45686.cpp`).

**M2 BMM150 (Waveshare BMM150 3-Axis Magnetometer Sensor):**

Prepare the module before fitting it:
- Desolder or cut off the pre-fitted 4-pin right-angle header (H3). It is unused, and it would stick out past the module's forward edge.
- Leave the white PH2.0 5-pin connector (H1) unused.
- Check that the I2C/SPI pads (H4) select I2C (PS high), the factory setting.
- Solder a straight 7-pin male header into the H2 pad row (DRY, A1/CS, SCL/SCK, SDA/SDI, A0/SDO, GND, VCC), with the plastic spacer down. Wire it as in §5.2, including the two GND address straps.

Mount it in its zone:
- Use the H2 header and the two module holes at its forward corners. Fix the holes with nylon M2 screws, nuts and 2.5 mm nylon spacers.
- Mark and drill those two Layer 2 holes at dry fit.

**Axes.** The silkscreen next to the chip shows X, Y and Z, with Z as ⊗, into the board. Mount the module component side up:
- the X arrow points **left, toward the J2 pin 39/40 end** (vehicle forward), so the edge where the right-angle header was is the forward edge;
- the Y arrow points **up, away from J2** (vehicle right). This is the **opposite** of M1's Y arrow;
- Z then points into the board, which is down;
- the H2 row is on the edge facing J2.

This is the PX4 body frame (X forward, Y right, Z down). So `bmm150` runs
without `-R`, at rotation 0. The driver applies no axis remap of its own.

**Hardware near M2:** keep power wires and any steel screws or nuts at least
10 mm away from it. Use brass or nylon hardware near it.

**M3 BMP280 (GY-BMP280-3.3):**
- Solder it on its 6-pin header with the long edge parallel to J2 and the pin row on the J2 side, so it fits x 35–50, y 22.5–34.5.
- Before fitting it, remove its SDA and SCL pull-up resistors (§5.4). Find them with a meter on the bare module: the resistor that reads about 10 kΩ (marking `103`, *typical for this board*) between the SDA pin and VCC, and the one between the SCL pin and VCC. Afterwards SDA and SCL read open to VCC. Leave the CSB and SDO resistors; the wiring in §5.3 overrides them.
- Glue a piece of open-cell foam over its port hole. The foam must not press on the sensor lid.

**M4 ADS1115:**
- Fit a machined-pin female strip on Layer 2.
- Put the module's male header on the module, so it plugs in from the top.
- Wire A0–A3 to J4 along the free strip at x 49–58.

**Wiring:**
- Use short point-to-point wires, under 50 mm, with a ground next to each signal (§4.3).
- Run the I2C7 pair from J2 pins 3/5 to M3, then on to the M2 H2 row. That is about 50 mm in total, which is fine for I2C.

#### 4.4.6 Assembly sequence

1. **Layer 3 alone:** fit its parts per §6.1, leaving J1 unfitted for joint A, and run §9 check 1.
2. **Dry fit on the RDK:**
   - Insert J2 into the bare Layer 2 from the bottom, and plug it onto the RDK without solder.
   - Measure the RDK-to-Layer 2 height, and the clearance from the SoC and every other RDK part under the 65 × 56.5 mm outline.
   - Check that all four Layer 2 holes line up with the RDK holes, and that the x = 0 edge clears the Ethernet/USB block.
   - Mark pin 1 on Layer 2, and mark the two M2 module holes.
3. **Solder J2** to Layer 2, with the body flush against the Layer 2 bottom and the tails square to the board.
4. **Fit the remaining Layer 2 parts:**
   - Fit the passives, then M1, the prepared M2 (§4.4.5), M3, the M4 socket, J4 and the test pads.
   - Trim every bottom tail to ≤1 mm.
   - Mark the M1 and M2 axis arrows on the Layer 2 silkscreen, or with a pen.
5. **Run §9 checks 2 and 3** with Layer 2 alone on the RDK, on its four 11 mm standoffs. Fix anything now, because joint A is permanent.
6. **Fit Layer 3 over the tails:**
   - Fit the 10 mm standoffs on the two header-edge holes of Layer 2, and lower Layer 3 over the tails.
   - Check that pin 1 is over pin 1, and that no part touches the Layer 3 bottom.
7. **Solder the tails** on the Layer 3 top, then run §9 check 4.
8. **Mount the stack on the frame:**
   - Use the orientation in §4.4.1 and the mounting notes in §8.
   - Tie all cables so that none of them levers Layer 3. Layer 3 is held only at the header edge.

#### 4.4.7 Orientation check after assembly

Run these checks props-off in QGC, after the sensor calibrations.

**IMU:**
- Lower the vehicle's right side: the artificial horizon rolls right.
- Lift the nose: it pitches up.
- Turn the vehicle clockwise, seen from above: the heading increases.
- If any of these is wrong, fix it before going further:
  - `SENS_BOARD_ROT` if the whole stack is turned;
  - the `-R` value in `rc.board_sensors` if only M1 is wrong.

**Compass:**
- Away from steel, point the nose north, using a phone compass as the reference. QGC should show about 0°.
- Turn the vehicle 90° clockwise. QGC should show about 90°.
- If the heading moves the wrong way, or is off by a multiple of 90°, M2 needs a `-R` on its `bmm150` line in `rc.board_sensors`. That is a firmware change; record it.

**Interference:**
- In the MAVLink console, `listener sensor_mag` must stay steady while the USB camera is plugged in and the SiK radio is transmitting.
- Keep the camera plugged in for both calibration and flight. Its supply current is then a constant offset, which calibration removes.
- Motor current only appears under load, so repeat the check in the first tethered-hover log. The field magnitude should not follow throttle. If it does, move M2 or plan an external compass.

## 5. Sensor module pin configuration

The firmware starts each sensor with fixed bus, address and chip-select
values. Each module must be strapped to match before power-up.

### 5.1 M1 ICM-45686 (SPI, `icm45686 -s -b 0 -c 3 -R 0`)

| Module pin | Connect to | Note |
|---|---|---|
| VDD, VDDIO | 3V3 | Not 5 V |
| GND | GND (J1-20/25) | |
| SCLK (SCL/AP_SCLK) | P92 SCK, J1-23 | SPI mode 3, ≤24 MHz |
| SDI (SDA/AP_SDA) | P90 MOSI, J1-19 | |
| SDO (AD0/AP_SDO) | P91 MISO, J1-21 | Must not be strapped to GND or 3V3 |
| CS (AP_CS) | P93, J1-24 | Low selects SPI. Remove any module strap that ties CS to VDDIO. |
| INT1 | P94, J1-26, through R4 | The `board_config.h` IMU interrupt pin. The demo firmware polls the IMU (`CONFIG_RZV2H_SPI0_SINGLE_IMU`) and leaves P94 unconfigured, so the wire is ready for a later DRDY build but unused today. |
| INT2 | not connected | |

- **Orientation:** mount flat, component side up, in zone M1 of §4.4.2. The X arrow points toward the J2 pin 39/40 end and the Y arrow toward J2. With the stack oriented as in §4.4.1, that is X forward, Y left: `-R 0`.
- Any other module orientation must be recorded and set with `-R` in `rc.board_sensors` before flight. A turned stack is handled by `SENS_BOARD_ROT` instead (§4.4.1).
- Mount it rigidly, as described in §4.4.5.

### 5.2 M2 BMM150 (I2C, `bmm150 -I -b 7 -a 0x10`)

M2 is the **Waveshare BMM150 3-Axis Magnetometer Sensor**. It has an RT9193
3.3 V LDO and NDC7002N level shifters, with 4.7 kΩ pull-ups on both sides of
the shifters. Wire it through its 7-pin H2 pad row, numbered from the silkscreen:

| H2 pin | Name | Connect to | Note |
|---|---|---|---|
| 1 | DRY | not connected | The firmware polls the part |
| 2 | A1/CS | GND | Address bit 1 = 0 |
| 3 | SCL/SCK | P77 SCL7, J1-5 | |
| 4 | SDA/SDI | P76 SDA7, J1-3 | |
| 5 | A0/SDO | GND | Address bit 0 = 0, so 7-bit address **0x10** |
| 6 | GND | GND (J1-6/9) | |
| 7 | VCC | 3V3 (J1-1/17) | **Never 5 V.** The bus-side pull-ups go to VCC, so 5 V would pull SDA7/SCL7 to 5 V (R1). |

- **The straps are required.** The module pulls A0 and A1 high, so unstrapped it answers at **0x13**. A1/A0 select 0x10 (0/0), 0x11 (0/1), 0x12 (1/0) or 0x13 (1/1). Only 0x10 matches the firmware.
- Each GND strap draws about 1.4 mA through the module's pull-up, about 2.8 mA in total. That is expected (§3.1).
- The H4 pads must select I2C (PS high), the factory setting. The H3 right-angle header is removed and the PH2.0 connector is unused (§4.4.5).
- Mount it as in §4.4.5: X arrow forward, Y arrow away from J2. The `bmm150` driver applies no axis remap, so verify the heading with §4.4.7 before trusting it.

### 5.3 M3 BMP280 (I2C, `bmp280 -I -b 7 -a 0x76`)

M3 is the **GY-BMP280-3.3** module (11.5 × 14.5 mm, 3.3 V only, I2C/SPI), from
the [shop listing](https://dientuduchuy.com/products/gy-bmp280-3-3-cam-bien-ap-suat-khi-quyen).
The listing does not state the pin order or the onboard resistors. The usual
board has a 6-pin row VCC, GND, SCL, SDA, CSB, SDO and 10 kΩ resistors; check
both against the silkscreen of the received module.

| Module pin | Connect to | Note |
|---|---|---|
| VCC | 3V3 | Never 5 V: the 3.3 V module has no regulator. |
| GND | GND (J1-6/9) | |
| CSB | 3V3 | High = I2C. Low at power-up latches SPI until a power cycle. |
| SDO | GND | 7-bit address **0x76**. High gives 0x77, which the firmware does not use. |
| SCL/SCK | P77 SCL7, J1-5 | |
| SDA/SDI | P76 SDA7, J1-3 | |

- Shield the BMP280 port hole from propeller airflow and direct light, for example with open-cell foam.

### 5.4 I2C pull-up budget

- **SCI7:**
  - The RDK already fits 2.2 kΩ pull-ups (R180/R181).
  - M2 adds 4.7 kΩ on its bus side. While the line is low, its chip-side 4.7 kΩ also sinks through the shifter FET. The effective value is 2.2 ∥ 4.7 ∥ 4.7 ≈ **1.14 kΩ**, about 2.9 mA, just inside the limit below.
  - So **M3 must add no pull-ups.** Its usual 10 kΩ would bring the total to about 1.02 kΩ, below the limit. Remove its SDA/SCL pull-up resistors (§4.4.5).
- **SCI0:** the RDK has none. R2/R3 (4.7 kΩ) plus the usual 10 kΩ on an ADS1115 module give about 3.2 kΩ.
- **Limit:** the pull-up from each SDA or SCL pin to 3V3 must be **≥1.1 kΩ**, which keeps the sink current ≤3 mA. All pull-ups must go to 3V3 (R2).
- **Meter check (power off, GPS/PM03D I2C wires cut, R5):** SDA7/SCL7 read about 1.5 kΩ to 3V3, because the meter does not see the M2 chip-side path (the unpowered LDO and the FET body diode block it). About 1.3 kΩ or lower means M3 pull-ups are still fitted. SDA0/SCL0 read about 3.2 kΩ.

### 5.5 M4 ADS1115 (I2C, `ads1115 -X -b 0`), temporary

| Module pin | Connect to | Note |
|---|---|---|
| VDD | 3V3 | Not 5 V (R2) |
| GND | GND (J1-34/39) | |
| ADDR | GND | 7-bit address **0x48**, the only one the firmware probes |
| SCL | P51 SCL0, J1-36 | |
| SDA | P50 SDA0, J1-22 | |
| ALERT/RDY | not connected | |
| A0–A3 | J4-1..4 | Each input must stay within 0–3.3 V. Nothing is connected by default. |

- **Firmware:** `rc.board_sensors` starts it as in `demosih`. `rzv2h_adc_telemetry` forwards the four channels to QGC as `NAMED_VALUE_FLOAT` `ADS_A0`..`ADS_A3`.
- **Battery:** no battery source is configured (`BAT1_SOURCE -1`), so there is no battery failsafe. A battery management IC will replace M4 on the same SCI0 pins later; R2/R3 stay.
- **H2:** Layer 3 H2-1 also carries P51. Leave H2-1 unconnected.

## 6. Layer 3: populate the bare extension board

### 6.1 Population list

| Fit | Refs | Part / setting |
|---|---|---|
| **No** (joint A) / bottom side (joint B) | J1 | Harwin M20-7812045. See §4.1; never fit it on the top side as placed in the PCB. |
| Yes | CN1 | Molex 502494-0670 (CLIK-Mate 6P) |
| Yes | CN2 | JST SM10B-GHS-TB (GH 10P) |
| Yes | CN3 | JST SM06B-GHS-TB |
| Yes | CN4 | Molex 0532610471 |
| Yes | CN5 | Molex 53261-0371 |
| Yes | H1 | Samtec TSW-104-08-G-T-RA |
| Yes | H2 | FCI 77313-801-06LF (2x3) |
| Yes | U1, U4, C1, C2 | SN74LV1T126DCKR, SN74LV1T04DCKR, 0.1 µF ×2 |
| Yes | SW1 | C&K SS-12D07-VG. Set to **position 1–2 (inverted, U4)** for SBUS. |
| Yes | R12 | 0 Ω (feeds 3V3 to CN2-8 for the GPS safety LED/switch) |
| **No** | R3 | 5 V link to RDK (R4) |
| **No** | U2, U6, U7, R4, R7, R9, C3, C4, C9–C12 | IMU section (R7). U6's CS pad is on P94, which carries M1 INT1 here. |
| **No** | U3, U5, R1, R2, C5–C8 | Baro section (R7). R1/R2 are the 4.7 kΩ SCI7 pull-ups; the RDK 2.2 kΩ is enough. |
| **No** | U8, R10, C13, C14 | Mag section (R7) |

The PoC PCB has no P50 net; only the reference perfboard used pin 22 for an
IMU interrupt. The schematic flags the P71 (J1-13), P53 (J1-31) and P93
(J1-24) labels with no-ERC markers. Beep these nets end to end on the bare
PCB before soldering (§9 check 1).

### 6.2 Connector pinout and cable wiring

Pin numbers are the Layer 3 footprint numbers. The cable to each device is
wired **by signal**, not pin-to-pin: device TX goes to an RDK RXD pin, and
device RX goes to an RDK TXD pin.

**CN1 PM03D (CLIK-Mate 6P), 5 V source only:**

| Pin | Net | PM03D cable |
|---|---|---|
| 1, 2 | +5V | 5 V out |
| 3 | P77 SCL7 | **Cut** (keeps the PM03D monitor off SCI7, R5) |
| 4 | P76 SDA7 | **Cut** |
| 5, 6 | GND | GND |

**CN2 GPS M10 (GH 10P, Pixhawk GPS order), 115200 8N1 on `/dev/ttyS9`:**

| Pin | Net | GPS signal |
|---|---|---|
| 1 | +5V | VCC |
| 2 | P82 TXD9 (J1-16) | GPS RX |
| 3 | P83 RXD9 (J1-18) | GPS TX |
| 4 | P77 SCL7 | **Cut** (GPS compass stays off SCI7, R5) |
| 5 | P76 SDA7 | **Cut** |
| 6 | P52 (J1-37) | Safety switch (unused by demo) |
| 7 | PA6 (J1-38) | Safety LED (unused) |
| 8 | +3V3 via R12 | 3.3 V for switch/LED |
| 9 | P97 (J1-40) | Buzzer (unused) |
| 10 | GND | GND |

The M10 ships at 9600 baud. The PX4 `gps` driver auto-configures it to
115200 (`SER_GPS1_BAUD`), as in the reference build.

**CN3 SiK telemetry v3 (GH 6P), 57600 8N1 MAVLink on `/dev/ttyS5`:**

| Pin | Net | Radio signal |
|---|---|---|
| 6 | +5V | VCC |
| 5 | P72 TXD5 (J1-8) | Radio RX |
| 4 | P73 RXD5 (J1-10) | Radio TX |
| 3, 2 | NC | CTS/RTS: leave open, radio flow control off |
| 1 | GND | GND |

> **Polarity warning:** CN3 is numbered in the reverse of the Pixhawk TELEM
> order, where pin 1 is 5 V. A stock 1:1 GH cable can put 5 V on the radio's
> GND. Power the board with the radio **unplugged** and measure at the cable's
> radio end. 5 V must appear on the radio's VCC pin before you connect it.

**CN4 TFmini Plus (4P), 115200 8N1 on `/dev/ttyS4`:**

| Pin | Net | Lidar signal |
|---|---|---|
| 4 | +5V | VCC (5 V) |
| 3 | P70 TXD4 (J1-15) | Lidar RXD |
| 2 | P71 RXD4 (J1-13) | Lidar TXD |
| 1 | GND | GND |

Build the cable from the Benewake wire table, matching by signal name. The
lidar UART is 3.3 V TTL; its supply is 5 V.

**CN5 fs-a8s RC (3P), SBUS 100000 8E2 on `/dev/ttyS6`:**

| Pin | Net | Receiver signal |
|---|---|---|
| 1 | +5V | VCC |
| 2 | GND | GND |
| 3 | fs-a8s_RX_5V → U1/U4 → SW1 → P75 (J1-7) | SBUS out |

- CN5 is not in servo order (signal, +, −). Wire it by signal.
- Set the receiver to SBUS output.
- SW1 at 1–2 selects the U4 inverter, which turns the inverted SBUS into the normal UART level that SCI6 expects. Position 2–3 selects the non-inverting U1 path, for a receiver that outputs non-inverted serial.

**H1 4x ESC (3 rows x 4), `pwm_out` 400 Hz, PX4 quad-X order:**

| ESC / motor | Position | Signal pin / net (J1) | Middle pin | GND pin |
|---|---|---|---|---|
| 1 | front right | 1 / PA4 GPT6A (32) | 2, NC | 3 |
| 2 | rear left | 4 / PA7 GPT7B (33) | 5, NC | 6 |
| 3 | front left | 7 / P96 GPT9A (35) | 8, NC | 9 |
| 4 | rear right | 10 / P53 GPT10B (31) | 11, NC | 12 |

- Plug each ESC servo lead with signal on the outer pin, the red BEC wire on the NC middle pin, and black on GND. The BEC then feeds nothing.
- The motor positions follow the reference build and the PX4 quad-X airframe. Check spin direction in the QGC motor test, props off.

**H2 spare (2x3):**
- Pins: 1 P51 (leave open, §5.5), 2 +5V, 3 P85, 4 +3V3, 5 P84, 6 GND.
- Nothing is fitted to H2 in the demo.

## 7. Full 40-pin allocation

| Pin | Pad | Layer 2 | Layer 3 | `demo` firmware |
|---|---|---|---|---|
| 1, 17 | 3V3 | Modules, pull-ups | +3V3 (U1/U4, CN2-8, H2-4) | — |
| 2, 4 | 5V | — | R3 (DNP) | — |
| 3 / 5 | P76 SDA7 / P77 SCL7 | M2, M3 | CN1-4/3, CN2-5/4 (cable wires cut) | Bus 7: BMM150 0x10, BMP280 0x76 |
| 7 | P75 RXD6 | — | SW1 common (SBUS) | `rc_input` |
| 8 / 10 | P72 TXD5 / P73 RXD5 | — | CN3-5 / CN3-4 | MAVLink 57600 |
| 11 | P74 | — | not routed | unused |
| 12 | P95 | — | U7 CS (DNP) | unused |
| 13 / 15 | P71 RXD4 / P70 TXD4 | — | CN4-2 / CN4-3 | `tfmini` 115200 |
| 16 / 18 | P82 TXD9 / P83 RXD9 | — | CN2-2 / CN2-3 | `gps` 115200 |
| 19 / 21 / 23 | P90 MOSI / P91 MISO / P92 SCK | M1 | IMU section (DNP) | SPI0 |
| 22 | P50 SDA0 | M4, R2 | not routed | Bus 0: ADS1115 0x48 |
| 24 | P93 SS0 | M1 CS, R1 | U2 CS (DNP) | `icm45686 -c 3` |
| 26 | P94 | M1 INT1 via R4 | U6 CS (DNP) | unconfigured (IMU polled) |
| 27 / 28 | P84 / P85 | — | H2-5 / H2-3 | unused |
| 29 | PA0 | — | not routed | unused |
| 31 / 32 / 33 / 35 | P53 / PA4 / PA7 / P96 | — | H1-10 / 1 / 4 / 7 | `pwm_out` motor 4 / 1 / 2 / 3 |
| 36 | P51 SCL0 | M4, R3 | H2-1 (leave open) | Bus 0: ADS1115 0x48 |
| 37 / 38 / 40 | P52 / PA6 / P97 | — | CN2-6 / 7 / 9 | unused |
| 6, 9, 14, 20, 25, 30, 34, 39 | GND | GND pour | GND | — |

## 8. Mechanical

- **Frame:** S500 (as photographed) or the LX450 the reference recommends. 4S 5300 mAh battery, PM03D on the frame plate.
- **Stack:** the RDK on brass or nylon standoffs (M2.5/M3) on the top plate. Layer 2 stands on four M2.5 standoffs (11 mm), one in each corner of its 65 × 56.5 mm outline. Layer 3 stands on two 10 mm standoffs on the Layer 2 header-edge holes (§4.1, §4.4.4). J1 must never carry the stack's weight or cable strain.
- **Mounting holes:** the RDK uses the Raspberry Pi pattern, 58 × 49 mm. This is taken from the manual photo, which is accepted for the build; confirm it at dry fit (§4.4.6 step 2). All four RDK holes are under Layer 2 holes. Only the header-end pair is under Layer 3, so Layer 3 is held only along the header edge.
- **Stack orientation:** the RDK Ethernet/USB edge points forward and the J2 header edge lies along the vehicle's left side (§4.4.1). Any other yaw needs `SENS_BOARD_ROT`.
- **Layout, heights and assembly order:** see §4.4.
- **Cables:** tie them to Layer 3 or the frame, and route them away from M1/M2.
- **Clearance:** keep the RDK DC jack and J-Link debug connector reachable with the stack fitted.
- **Vibration:** soft-mount the whole stack on the frame (damping balls or foam), not M1 alone.

## 9. Hardware acceptance checks

Run these in order and record the values in a dated transcript under
`docs/renesas/evidence/`.

1. **Bare Layer 3, unpowered:**
   - Beep each J1 hole to its connector pin per §6.2, including P71 to CN4-2, P53 to H1-10 and P93 to the U2 pad.
   - No short between adjacent pins.
   - +5V is open to J1-2/4 (R3 DNP).
2. **Layer 2 alone on the RDK, unpowered:**
   - J2 pin 1 sits on RDK pin 1 (3V3) and pin 2 on RDK pin 2 (5V): beep 3V3 from an RDK test point to J2 tail 1.
   - P76 and P77 (SDA7/SCL7) to 3V3: ≈1.5 kΩ. About 1.3 kΩ or lower means M3 pull-ups are still fitted (§5.4).
   - P50 and P51 to 3V3: ≈3–4.7 kΩ.
   - M2 H2-2 (A1/CS) and H2-5 (A0/SDO) to GND: 0 Ω. M2 H2-7 (VCC) to 3V3: 0 Ω.
   - P93 to 3V3: ≈10 kΩ. P94 to M1 INT1: ≈1 kΩ.
   - No pin at 5 V potential (R1).
3. **Layer 2 alone, RDK powered from 12 V:**
   - 3V3 at M1–M4: 3.20–3.40 V.
   - Boot the demo image. RTT shows `ICM45686 started on SPI0 CS pin 3`, `BMM150 started on SCI7 I2C bus 7`, `BMP280 started on SCI7 I2C bus 7` and `ADS1115 started on SCI0 I2C bus 0`.
   - `i2cdetect -b 7` lists only 0x10 and 0x76. 0x13 instead of 0x10 means the M2 address straps are missing. `i2cdetect -b 0` lists only 0x48.
4. **Full stack, peripherals unplugged:**
   - Beep RDK pin 1 to the Layer 3 +3V3 net and RDK pin 2 to the R3 pad, to confirm pin N over pin N.
   - +5V rail 4.85–5.35 V from the PM03D or bench supply.
   - CN3 polarity verified at the cable end.
   - 3V3 present at U1/U4 pin 5.
5. **Peripherals plugged:**
   - +5V stays in range.
   - `i2cdetect -b 7` still lists only 0x10 and 0x76 (GPS and PM03D I2C wires cut).
6. **SBUS:** with SW1 at 1–2 and the receiver bound, P75 idles high at 3.3 V, and `listener input_rc` follows the sticks.
7. **Topics:**
   - `listener` shows `sensor_accel`, `sensor_gyro`, `sensor_mag`, `sensor_baro`, `distance_sensor`, `adc_report` and `sensor_gps` (fix outdoors).
   - QGC MAVLink Inspector shows `ADS_A0`..`ADS_A3`.
   - See [demo bench checks](./validation/demo-bench-validation.md).
8. **Battery power and QGC:**
   - The RDK boots from the PM03D 12 V output with the battery connected.
   - QGC connects over SiK at 57600.
   - Accelerometer, compass and RC calibration complete.
   - Arm with RC, props off. Motors 1–4 respond on PA4/PA7/P96/P53 in the §6.2 positions.

Checks 1–8 support a bounded on-target claim ([evidence rules](./port-status-nuttx.md)). Tethered flight comes after them.

## 10. Deferred alternative

Populating the Layer 3 sensor footprints (3x ICM-45686, 2x BMP390L, BMM150)
with the CR8-0 `default` image would remove Layer 2 entirely; it matches
that board pad for pad ([pinmap](./pinmap.md#single-core-drone-default-against-the-reference-hardwaremd)).
It needs LGA reflow assembly, a different firmware target and the J1 fix in
§4.1, so it is deferred. Never combine it with Layer 2 (R7, R9).

## 11. Open items

- **Battery IC:** part, I2C address and PX4 driver are still to be chosen. It replaces M4 on SCI0. Until then `BAT1_SOURCE -1` and no battery failsafe.
- **Layer 3 J1:** the next PCB revision should move J1 to the bottom side, as the reference build fits it by hand, or specify a stacking header.
- **PM03D 12 V output:** the user confirmed it delivers ≥2 A and its plug matches the RDK jack. Still measure the voltage and polarity at the plug before the first battery connection (§3).
- **Parts to confirm by measurement:**
  - whether the SkyWalker 40A accepts 3.3 V PWM;
  - a stacking header with ≥14.7 mm of tail for the chosen 10 mm gap (§4.4.4); the 8 mm fallback needs ≥12.7 mm;
  - at dry fit: the four RDK hole positions (photo estimate), the RDK-to-Layer 2 height (≈11 mm), and the clearance of the SoC and every other RDK part under the 65 × 56.5 mm outline (§4.4.6 step 2).
- **M1 module:** the exact ICM-45686 breakout model and size are not chosen yet. Its zone in §4.4.2 assumes about 11–16 mm square; recheck it when the part arrives.
- **M3 module:** the GY-BMP280-3.3 is chosen. Confirm its pin order and its SDA/SCL pull-up resistors on the received board (§4.4.5, §5.3).
