# EVK-RA8P1 IMU Integration Guide

## Hardware Configuration

### Sensor: ICM-20948 (GY-912 Module)

The GY-912 module contains:
- **ICM-20948**: 9-axis IMU (3-axis gyroscope + 3-axis accelerometer + AK09916 magnetometer)
- **BMP388**: Barometric pressure sensor (I2C interface)

### SPI Pin Mapping (Arduino Header)

| Signal | Pin | Port.Pin | Function | Notes |
|--------|-----|----------|----------|-------|
| SCK | D13 | P102 | GPIO_ARDUINO_SPI_SCK | SPI1 Clock |
| MISO | D12 | P100 | GPIO_ARDUINO_SPI_MISO | SPI1 Data In |
| MOSI | D11 | P101 | GPIO_ARDUINO_SPI_MOSI | SPI1 Data Out |
| CS | D10 | P103 | GPIO_ARDUINO_SPI_CS0 | ICM-20948 Chip Select (Active Low) |
| DRDY | D2 | P011 | GPIO_ARDUINO_D2_INT | ICM-20948 Data Ready (IRQ16) |

### I2C Pin Mapping (for BMP388)

| Signal | Pin | Port.Pin | Function |
|--------|-----|----------|----------|
| SCL | - | P400 | I2C0 Clock |
| SDA | - | P401 | I2C0 Data |

BMP388 I2C Address: `0x76` or `0x77` (depends on SDO pin)

---

## Software Configuration

### SPI Bus Configuration

**File:** `boards/renesas/evk-ra8p1/src/spi.cpp`

```cpp
constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
    initSPIBus(SPI::Bus::SPI1, {
        // ICM-20948: 9DOF IMU (gyroscope, accelerometer, magnetometer)
        initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
                      SPI::CS{GPIO::Port1, GPIO::Pin3},    // P103 - CS
                      SPI::DRDY{GPIO::Port0, GPIO::Pin11}), // P011 - DRDY/IRQ16
    }),
};
```

### Board Config Definitions

- SW4_4 and SW4_3 must be ON

**File:** `boards/renesas/evk-ra8p1/src/board_config.h`

```c
#define IMU_SCL                P102 (Arduino D13)
#define IMU_SDA                P100 (Arduino D12)
#define IMU_SDO                P101 (Arduino D11)
#define IMU_CS                 PB0  (Arduino D9)
#define IMU_RDY                P011 (Arduino D2)
```

### ICM-20948 SPI Settings

| Parameter | Value | Notes |
|-----------|-------|-------|
| SPI Mode | Mode 3 (CPOL=1, CPHA=1) | Per ICM-20948 datasheet |
| Max Frequency | 4 MHz | Supports up to 7 MHz |
| Bit Order | MSB First | Standard |
| Data Width | 8-bit | Standard |

---

## Startup Script

**File:** `boards/renesas/evk-ra8p1/init/rc.board_sensors`

```bash
# Start IMU on SPI1 - ICM20948 9-axis sensor with integrated magnetometer
# -s: SPI mode, -b 1: SPI bus 1, -R 0: no rotation, -M 1: enable magnetometer
icm20948 start -s -b 1 -M 1

# Start Barometer on I2C0 - BMP388 (try 0x76 then 0x77)
bmp388 start -X -b 0 -a 0x76
```

---

## Testing Procedures

### 1. Boot and Sensor Initialization

After flashing and booting the board, check the console output:

```
ICM20948 IMU initialized successfully
BMP388 barometer initialized successfully (0x76)
```

### 2. Check Sensor Status

```bash
# IMU status
icm20948 status

# Barometer status
bmp388 status
```

Expected output for `icm20948 status`:
```
INFO  [icm20948] Running on SPI bus 0
INFO  [icm20948] FIFO: xyz samples
INFO  [icm20948] temperature: xx.x C
```

### 3. Monitor Sensor Data via uORB Topics

```bash
# Accelerometer data
listener sensor_accel

# Gyroscope data
listener sensor_gyro

# Magnetometer data (AK09916)
listener sensor_mag

# Barometer data
listener sensor_baro
```

### 4. Verify Data Rates

```bash
# Check topic publication rates
uorb top
```

Expected rates:
| Topic | Rate |
|-------|------|
| sensor_accel | ~200-1000 Hz |
| sensor_gyro | ~200-1000 Hz |
| sensor_mag | ~100 Hz |
| sensor_baro | ~50 Hz |

### 5. Sensor Calibration

```bash
# Accelerometer calibration
commander calibrate accel

# Gyroscope calibration
commander calibrate gyro

# Magnetometer calibration
commander calibrate mag
```

---

## Troubleshooting

### Issue: IMU not detected

**Symptoms:**
```
ERROR: ICM20948 IMU initialization failed!
```

**Checklist:**
1. Verify SPI wiring (SCK, MISO, MOSI, CS)
2. Check CS pin is correctly configured as output high initially
3. Verify SPI1 is enabled in NuttX defconfig (`CONFIG_RA_SPI1=y`)
4. Check SPI clock frequency (try lowering to 1 MHz for debug)

### Issue: DRDY interrupt not working

**Symptoms:**
- Sensor initializes but data rate is low
- `DRDY missed` counter incrementing in `icm20948 status`

**Checklist:**
1. Verify DRDY pin (P011) connected to ICM-20948 INT1
2. Check IRQ16 is enabled in NuttX (`CONFIG_RA_ICU=y`)
3. Verify GPIO configuration includes `R_PFS_ISEL` bit for IRQ input
4. Check `px4_arch_gpiosetevent` returns 0 (success)

### Issue: Magnetometer not working

**Symptoms:**
- `sensor_mag` topic not publishing
- AK09916 errors in log

**Checklist:**
1. Ensure `-M 1` flag is passed to `icm20948 start`
2. ICM-20948 I2C master must be configured for AK09916 communication
3. Check internal I2C bus speed (400 kHz)

### Issue: BMP388 not detected

**Symptoms:**
```
ERROR: BMP388 barometer initialization failed!
```

**Checklist:**
1. Verify I2C0 wiring (SCL=P400, SDA=P401)
2. Try alternate address: `bmp388 start -X -b 0 -a 0x77`
3. Check I2C0 is enabled (`CONFIG_RA_I2C0=y`)
4. Verify pull-up resistors on I2C lines

---

## GPIO Encoding Reference

For RA8P1, GPIO pinset encoding (per `ra_gpio.h`):

```
Bits 31-28: Port number (GPIO_PORT_SHIFT = 28)
Bits 27-24: Pin number (GPIO_PIN_SHIFT = 24)
Bits 23-0:  Configuration flags
```

Key configuration bits:
| Bit | Name | Description |
|-----|------|-------------|
| 0 | R_PFS_PODR | Port Output Data (1=high) |
| 2 | R_PFS_PDR | Port Direction (1=output) |
| 4 | R_PFS_PCR | Pull-up Control |
| 14 | R_PFS_ISEL | IRQ Input Enable |

Example for DRDY pin P011 with IRQ:
```c
// Port0, Pin11, Pull-up, IRQ enable
drdy_gpio = (0 << 28) | (11 << 24) | (1 << 4) | (1 << 14);
```

---

## References

- [ICM-20948 Datasheet](https://invensense.tdk.com/products/motion-tracking/9-axis/icm-20948/)
- [BMP388 Datasheet](https://www.bosch-sensortec.com/products/environmental-sensors/pressure-sensors/bmp388/)
- [EVK-RA8P1 User Manual](https://www.renesas.com/evk-ra8p1)
- PX4 ICM20948 Driver: `src/drivers/imu/invensense/icm20948/`
- PX4 BMP388 Driver: `src/drivers/barometer/bmp388/`
