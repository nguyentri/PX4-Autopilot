# RDK-RZ/V2H Drone Demo: Block Diagrams for 3D Renders

**Date:** 2026-11-23
**Build it describes:** [3-layer drone demo board](./rzv2h-rdk-drone-demo-board.md) on an S500/LX450 quad
**Sources:**
- `refs/rzv2h_drone_px4-dev/docs/` HARDWARE.md and the photos in `assets/`.
- Component placement from the PoC PCB `Extension board for drone_20260713.PcbDoc`.

Each section below describes one image:
- a Mermaid block diagram for layout and topology;
- a **render brief** with the 3D facts (sizes, heights, camera, materials) that Mermaid cannot express.

**To render:**
- Paste one section (diagram + brief) into a 3D or image-generation tool.
- Or render the diagrams to SVG and use them as layout references:
  `mmdc -i docs/renesas/rzv2h-rdk-drone-demo-3d-render-diagrams.md -o /tmp/drone-diagrams.md`.

**Conventions:**
- Every top view is seen from above, with vehicle **forward = up**.
- Sizes marked *measured* come from the PoC PCB file.
- Sizes marked *assumed* are typical values to confirm on the real parts.
- Colours marked *render choice* are only there to tell parts apart.

## 1. Kit overview (all parts, exploded flat lay)

Same idea as `assets/drone_components.png`, updated for this stack.

```mermaid
block-beta
  columns 4
  frame["S500 / LX450 frame<br/>quad X, 450 mm class"]
  battery["4S LiPo 5300 mAh<br/>XT60"]
  pm03d["Holybro PM03D<br/>power module"]
  esc["4x SkyWalker 40A ESC"]
  motor["4x Sunny Sky X2216<br/>1100 kV"]
  props["4x 1045 (S500)<br/>or 9450 (LX450) props"]
  rdk["Layer 1<br/>RDK-RZ/V2H"]
  shield["Layer 2<br/>custom sensor shield<br/>ICM-45686, BMM150,<br/>BMP280, ADS1115"]
  ext["Layer 3<br/>Extension Board for Drone PoC<br/>connectors only"]
  gps["u-blox M10 GPS<br/>puck on mast"]
  lidar["Benewake TFmini Plus<br/>lidar, faces down"]
  sik["SiK telemetry v3<br/>radio + antenna"]
  rc["FlySky fs-a8s<br/>RC receiver"]
  cam["Logitech C920<br/>USB camera (CA55 Linux)"]
  hw["M2.5 / M3 standoffs<br/>stacking header"]
  jlink["SEGGER J-Link<br/>(bench only)"]

  classDef board fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef power fill:#c0392b,stroke:#6e1f17,color:#fff
  classDef sensor fill:#2e8b57,stroke:#174a2d,color:#fff
  class rdk,shield,ext board
  class battery,pm03d,esc power
  class gps,lidar,sik,rc,cam sensor
```

**Render brief:**
- Isometric flat lay on a green cutting mat, as in the reference photos.
- Soft studio light, every part labelled.
- The three boards sit side by side and also appear assembled as one stack in the corner.

## 2. Layer stack, exploded side view

```mermaid
block-beta
  columns 1
  l3["LAYER 3: Extension Board for Drone PoC, 65.0 x 40.0 mm, bare PCB with connectors<br/>top: CN1..CN5 along the edge opposite J1, H1 ESC pins, H2, SW1, U1/U4<br/>J1 holes: stacking-header tails soldered on top (J1 socket not fitted)"]
  gap23["M2.5 x 10 mm standoffs at both J1 ends, 58.0 mm apart (10 mm gap, chosen)"]
  l2["LAYER 2: custom sensor shield, 65.0 x 56.5 mm (full HAT, 16.5 mm deeper than Layer 3)<br/>top: M1 ICM-45686, M3 BMP280, M4 ADS1115 under Layer 3; M2 BMM150, J4, test pads in the open strip<br/>bottom: J2 2x20 stacking header, socket body facing down"]
  gap12["socket body 8.4 mm over the RDK male header pins, four M2.5 x 11 mm standoffs on the 58 x 49 mm pattern (about 11 mm RDK to Layer 2)"]
  l1["LAYER 1: RDK-RZ/V2H, 1.7 mm PCB<br/>40-pin male header on one long edge, Ethernet/USB edge forward, DC barrel jack, J-Link"]
  gap01["M2.5 / M3 standoffs + vibration damping"]
  plate["S500 / LX450 top plate"]

  classDef pcb3 fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef pcb2 fill:#6a3d9a,stroke:#2f1a47,color:#fff
  classDef pcb1 fill:#2f6f4f,stroke:#123222,color:#fff
  classDef gap fill:#f4f4f4,stroke:#999,color:#333,stroke-dasharray: 4 3
  classDef frame fill:#222,stroke:#000,color:#fff
  class l3 pcb3
  class l2 pcb2
  class l1 pcb1
  class gap23,gap12,gap01 gap
  class plate frame
```

**Render brief:**
- Exploded vertical stack, 3/4 view from the front-left, gaps exaggerated about 3x.
- **Board outlines:**
  - Layer 3 is 65.0 x 40.0 mm (*measured*), with two Ø2.75 mm holes on the header row centreline, 3.5 mm from each short edge.
  - Layer 2 is 65.0 x 56.5 mm (full Raspberry Pi HAT, *design choice*). It shares the Layer 3 header-edge holes and adds two more 49 mm further on (*estimated* from the RDK manual photo), so it stands on four standoffs.
  - Layer 2 sticks out 16.5 mm past the Layer 3 far edge. The M2 compass, J4 and the test pads sit on that open strip.
- **Header:** the 2x20 2.54 mm header lies along one long edge, centred, 3.8 mm in from that edge.
- **Heights:**
  - RDK PCB 1.7 mm (*from the RDK schematic, p. 1*). Layer 2 and Layer 3 PCBs 1.6 mm (*assumed*).
  - J2 socket body 8.4 mm (*measured*, M20-7812045 class). RDK top to Layer 2 bottom about 11 mm (*estimated*; spec §4.4.4).
  - Layer 2 to Layer 3 gap 10 mm (*chosen*, spec §4.4.4), which needs a stacking header with ≥14.7 mm of tail.
- **Header pins:** draw one continuous row of 40 gold pins running from the RDK header, through the Layer 2 socket, up through Layer 3.
- **PCB colours:** blue for Layer 3 (as photographed); purple for Layer 2 and green for the RDK (*render choice*).
- **Alternative B:** Layer 3 with its J1 socket fitted on its bottom, plugged onto the Layer 2 tails.
- **Reference photo:** `assets/real_drone_top1.png` shows the PoC fitted with J1 under the board, plugged straight onto the RDK with brass standoffs at both header ends.

## 3. Layer 3 top view (PoC PCB placement)

Placement is rotated 180° from the PCB file so it matches the photo
`assets/real_drone_top1.png`: connectors along the upper edge, J1 along
the lower edge. On the vehicle, the J1 edge lies along the left side (spec §4.4.1). Parts in grey are footprints left empty in this stack.

```mermaid
block-beta
  columns 8
  cn5["CN5<br/>fs-a8s RC<br/>Molex 3P"] cn4["CN4<br/>TFmini<br/>Molex 4P"] cn3["CN3<br/>SiK<br/>GH 6P"] space cn2["CN2<br/>GPS M10<br/>GH 10P"] space cn1["CN1<br/>PM03D 5 V<br/>CLIK-Mate 6P"] h2["H2<br/>spare 2x3"]
  sw1["SW1<br/>SBUS invert<br/>set 1-2"] u14["U1 / U4<br/>SBUS level<br/>shift"] u7["U7<br/>IMU (DNP)"] u6["U6<br/>IMU (DNP)"] u2["U2<br/>IMU (DNP)"] u35["U3 / U5<br/>baro (DNP)"] u8["U8<br/>mag (DNP)"] h1["H1<br/>4x ESC<br/>right angle"]
  hl["M2.5<br/>hole"] j1["J1 2x20 header row (pin 1 at the right end, inner row; 5 V pins 2/4 on the outer row, next to the board edge)"]:6 hr["M2.5<br/>hole"]

  classDef conn fill:#f5f5f5,stroke:#333,color:#000
  classDef dnp fill:#bbbbbb,stroke:#777,color:#444,stroke-dasharray: 3 3
  classDef fit fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef hole fill:#d4a017,stroke:#7a5c00,color:#000
  class cn1,cn2,cn3,cn4,cn5,h1,h2 conn
  class u2,u6,u7,u35,u8 dnp
  class sw1,u14,j1 fit
  class hl,hr hole
```

**Render brief:**
- Straight-down top view of a blue 65.0 x 40.0 mm PCB with white silkscreen "Extension Board for Drone PoC".
- **Upper edge, left to right:** white CN5 (3P), CN4 (4P), CN3 (6P), CN2 (10P), CN1 (6P, the largest).
- **H1:** four 3-pin right-angle headers pointing off the right edge.
- **H2:** the 2x3 header in the upper-right corner.
- **SW1:** slide switch at the left edge.
- **Sensor pads:** the U2/U6/U7 IMU, U3/U5 baro and U8 mag pads are empty.
- **J1 area:** 40 gold pin tails in a row near the lower edge.
- **Mounting:** brass M2.5 standoffs in the two holes at the J1 ends.

## 4. Layer 2 top view (custom sensor shield, proposed placement)

No PCB exists yet, so this is the proposed placement. Fixed facts: board outline,
J2 row and header-edge holes (copied from Layer 3), the Layer 3 keep-outs and all
the nets. The zone coordinates are in spec §4.4.2. Each column is about 8 mm wide,
the far edge (y = 56.5) is at the top and the header edge at the bottom. The
top row is the open strip past the Layer 3 edge (y = 40).

```mermaid
block-beta
  columns 8
  hlf["M2.5<br/>hole"] m2["M2 Waveshare BMM150, SCI7 0x10 (A0, A1 to GND)<br/>open above, furthest from power and ESC wires<br/>X arrow to the left = forward, Y arrow up = right"]:4 j4["J4 1x5<br/>A0..A3, GND"] tp["TP1..TP10<br/>test pads"] hrf["M2.5<br/>hole"]
  edge["Layer 3 far edge (y = 40): open strip above, under Layer 3 below"]:8
  space free["free, over the RDK SoC"]:3 m3["M3 GY-BMP280-3.3, SCI7 0x76<br/>14.5 x 11.5 mm, pull-ups removed<br/>foam over port"]:2 spare["spare"] ko2["keep-out<br/>H2 tails"]
  ko1["keep-out<br/>SW1 tails"] m4["M4 ADS1115, SCI0 0x48<br/>machined-pin socket<br/>over SCI0 pins 22 / 36"]:3 m1["M1 ICM-45686, SPI0<br/>CS P93, INT1 to P94 via R4<br/>X arrow left, Y arrow down"]:2 koh["keep-out<br/>H1 ESC header tails"]:2
  space r3["R3 4.7k<br/>P51, pin 36"] space r124["R4 1k / R1 10k / R2 4.7k<br/>pins 26 / 24 / 22"] c1["C1 10 uF<br/>pin 17"] space space space
  hl["M2.5<br/>hole"] j2["J2 2x20 stacking header (tails up, socket body below, pins 39/40 at the left end, pin 1 at the right end)"]:6 hr["M2.5<br/>hole"]

  classDef sens fill:#2e8b57,stroke:#174a2d,color:#fff
  classDef pas fill:#eeeeee,stroke:#666,color:#000
  classDef hdr fill:#6a3d9a,stroke:#2f1a47,color:#fff
  classDef hole fill:#d4a017,stroke:#7a5c00,color:#000
  classDef keep fill:#ffffff,stroke:#c0392b,color:#c0392b,stroke-dasharray: 4 3
  classDef edge fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef free fill:#ffffff,stroke:#bbbbbb,color:#777,stroke-dasharray: 2 2
  class m1,m2,m3,m4 sens
  class r3,r124,c1,j4,tp pas
  class j2 hdr
  class hl,hr,hlf,hrf hole
  class ko1,ko2,koh keep
  class edge edge
  class free,spare free
```

**Render brief:**
- Top view of a 65.0 x 56.5 mm PCB (purple, *render choice*), with the header row along the bottom edge and pin 1 at the right end. Four M2.5 holes, one in each corner.
- **Layer 3 shadow:** draw the Layer 3 outline (65 x 40 mm, from the bottom edge) as a translucent blue overlay, so the open strip at the top stands out.
- **Open strip (top 16.5 mm):** the 29 x 20 mm Waveshare BMM150 module at the left, fixed by its header row and two nylon screws at its forward corners; a straight 1x5 J4 header and a block of test pads at the right.
- **Under Layer 3:** M4, a larger ADS1115 breakout in a round-pin socket at the left; M1 ICM-45686 in the middle, just above the SPI pins; M3, a small purple GY-BMP280-3.3 (14.5 x 11.5 mm) above M1, its pin row on the J2 side.
- **Axis arrows:** M1 and M2 X arrows both point left (toward pins 39/40, vehicle forward). The M1 Y arrow points down (toward J2); the M2 Y arrow points up (away from J2).
- **Keep-outs:** leave bare board under the Layer 3 H1, H2 and SW1 tails (right side and left edge), drawn as dashed red outlines if shown.
- **Heights:** modules about 5 mm, M4 about 8.5 mm, all below the 10 mm Layer 2 to Layer 3 gap. M2 sits in the open strip, so its height is free.
- **Wiring:** short wires from the header row to each module; the I2C7 pair runs from pins 3/5 past M3 up to the M2 header row.

## 5. Airframe top view (placement on the quad)

PX4 quad X motor numbering and spin directions, as in HARDWARE.md.

```mermaid
block-beta
  columns 5
  m3["Motor 3<br/>front-left<br/>CW"] space fwd["FORWARD"] space m1["Motor 1<br/>front-right<br/>CCW"]
  space gps["GPS M10 on mast<br/>(arrow forward, clear of the stack)"] cam["C920 camera<br/>on the RDK front edge, optional"] sik["SiK radio<br/>+ antenna, right side"] space
  space space stack["3-layer stack<br/>(RDK + shield + extension)<br/>Ethernet/USB edge forward<br/>header edge on the left"] space space
  space rc["fs-a8s receiver<br/>antennas clear of carbon"] space space space
  m2["Motor 2<br/>rear-left<br/>CCW"] space rear["REAR"] space m4["Motor 4<br/>rear-right<br/>CW"]

  classDef cw fill:#c0392b,stroke:#6e1f17,color:#fff
  classDef ccw fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef mid fill:#2e8b57,stroke:#174a2d,color:#fff
  classDef label fill:#ffffff,stroke:#ffffff,color:#000
  class m3,m4 cw
  class m1,m2 ccw
  class stack,gps,sik,rc,cam mid
  class fwd,rear label
```

**Render brief:**
- 3/4 aerial view of a black S500 quad X frame, about 450 mm motor to motor, with red arm wiring.
- **Props:** show the direction arrows: motors 1 and 2 CCW, motors 3 and 4 CW.
- **Centre:** the stack sits on the top plate. The RDK Ethernet/USB edge faces forward, so the long 40-pin header edge runs front to back along the vehicle's left side, and the Layer 3 connectors face the right side (spec §4.4.1).
- **GPS:** puck on a carbon mast, with an arrow pointing forward.
- **SiK radio:** box with a black antenna on one side.
- **Receiver:** the small fs-a8s, with its antenna leads routed outward.
- **ESC leads:** the four ESC signal leads run from the arms to the H1 pins on the stack.
- **Reference photos:** `assets/real_drone_top.png` and `assets/real_drone_top1.png`.

## 6. Airframe side view (vertical layout)

```mermaid
block-beta
  columns 1
  gpsm["GPS M10 puck on mast"]
  stk["3-layer stack: Layer 3 (connectors) / Layer 2 (sensors) / Layer 1 RDK"]
  sikr["SiK radio + RC receiver, beside the stack"]
  top["Top plate (S500 / LX450)"]
  mid["PM03D and ESC power wiring between the plates"]
  bot["Bottom plate with landing-gear rails"]
  bat["4S 5300 mAh LiPo strapped to the rails (XT60 to PM03D)"]
  tf["TFmini Plus under the frame, lens facing straight down"]

  classDef top fill:#2e8b57,stroke:#174a2d,color:#fff
  classDef frame fill:#222,stroke:#000,color:#fff
  classDef power fill:#c0392b,stroke:#6e1f17,color:#fff
  class gpsm,stk,sikr,tf top
  class top,bot frame
  class mid,bat power
```

**Render brief:**
- Side elevation from the right, at eye level with the frame.
- **Battery:** it hangs below on velcro straps, as in `assets/real_drone_side2.png` (the older ribbon-cabled build).
- **Upper stack:** the three-board stack and GPS mast replace that build's ribbon and perfboard.
- **TFmini:** must have a clear view down, not blocked by the battery or landing gear.

## 7. Power and signal harness

```mermaid
flowchart LR
  bat["4S LiPo<br/>5300 mAh"] -->|XT60| pm["Holybro PM03D"]
  pm -->|main power| esc["4x ESC"]
  esc --> mot["4x motor"]
  pm -->|"12 V out (switch at 12 V)"| jack["RDK DC barrel jack"]
  pm -->|"5 V, CLIK-Mate 6P<br/>I2C wires cut"| cn1["Layer 3 CN1"]

  subgraph stack["3-layer stack"]
    direction TB
    l3["Layer 3: +5 V rail, connectors, SBUS shift"]
    l2["Layer 2: sensors on 3V3"]
    l1["Layer 1: RDK-RZ/V2H, 3V3 source"]
    l3 --- l2 --- l1
  end

  cn1 --> l3
  jack --> l1
  l3 -->|"CN2 GH 10P, UART9 115200"| gps["GPS M10"]
  l3 -->|"CN3 GH 6P, UART5 57600"| sik["SiK radio"]
  l3 -->|"CN4 4P, UART4 115200"| tf["TFmini Plus"]
  l3 -->|"CN5 3P, SBUS to UART6"| rc["fs-a8s"]
  l3 -->|"H1 PWM 400 Hz, signal + GND only"| esc
  sik -.->|"433/915 MHz MAVLink"| qgc["QGroundControl"]
  tx["RC transmitter"] -.->|2.4 GHz| rc
```

**Render brief:**
- A cable-harness illustration in which wire colours follow the power class:
  - red/black for battery and 12 V;
  - red/black thin for 5 V;
  - yellow/green/white for signals.
- Draw the ESC servo leads with the red BEC wire left unconnected.

## 8. 40-pin header map (for a close-up render)

Odd pins are the inner row; even pins are the board-edge row. Header geometry follows [rzv2h-rdk-40_pin_header_pin.png](./rzv2h-rdk-40_pin_header_pin.png).

```mermaid
block-beta
  columns 20
  p2["2<br/>5V"] p4["4<br/>5V"] p6["6<br/>GND"] p8["8<br/>SiK<br/>TX5"] p10["10<br/>SiK<br/>RX5"] p12["12<br/>P95"] p14["14<br/>GND"] p16["16<br/>GPS<br/>TX9"] p18["18<br/>GPS<br/>RX9"] p20["20<br/>GND"] p22["22<br/>SDA0<br/>ADS"] p24["24<br/>IMU<br/>CS"] p26["26<br/>IMU<br/>INT1"] p28["28<br/>P85"] p30["30<br/>GND"] p32["32<br/>ESC1"] p34["34<br/>GND"] p36["36<br/>SCL0<br/>ADS"] p38["38<br/>PA6"] p40["40<br/>P97"]
  p1["1<br/>3V3"] p3["3<br/>SDA7"] p5["5<br/>SCL7"] p7["7<br/>SBUS<br/>RX6"] p9["9<br/>GND"] p11["11<br/>P74"] p13["13<br/>TF<br/>RX4"] p15["15<br/>TF<br/>TX4"] p17["17<br/>3V3"] p19["19<br/>MOSI"] p21["21<br/>MISO"] p23["23<br/>SCK"] p25["25<br/>GND"] p27["27<br/>P84"] p29["29<br/>PA0"] p31["31<br/>ESC4"] p33["33<br/>ESC2"] p35["35<br/>ESC3"] p37["37<br/>P52"] p39["39<br/>GND"]

  classDef pwr fill:#c0392b,stroke:#6e1f17,color:#fff
  classDef gnd fill:#222,stroke:#000,color:#fff
  classDef spi fill:#6a3d9a,stroke:#2f1a47,color:#fff
  classDef i2c fill:#2e8b57,stroke:#174a2d,color:#fff
  classDef uart fill:#1f5fa8,stroke:#0b2d55,color:#fff
  classDef pwm fill:#d4a017,stroke:#7a5c00,color:#000
  classDef nc fill:#eeeeee,stroke:#999,color:#555
  class p1,p2,p4,p17 pwr
  class p6,p9,p14,p20,p25,p30,p34,p39 gnd
  class p19,p21,p23,p24,p26 spi
  class p3,p5,p22,p36 i2c
  class p7,p8,p10,p13,p15,p16,p18 uart
  class p31,p32,p33,p35 pwm
  class p11,p12,p27,p28,p29,p37,p38,p40 nc
```

**Render brief:**
- Macro close-up of the 2x20 2.54 mm header, colour-coded as above:
  - power red, GND black, SPI purple, I2C green, UART blue, PWM gold, unused grey.
- **Labels:** UART names are from the RDK side (TX5 = RDK transmit).
- **Orientation:** pin 1 square pad; viewed from above, the inner row runs 1 to 39 from left to right.
- Mirror the image when you need to match the photo orientation of §3.
