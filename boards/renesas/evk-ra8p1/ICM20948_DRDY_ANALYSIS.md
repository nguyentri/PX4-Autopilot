# ICM20948 Data Ready (DRDY) Implementation Analysis

## Overview
This document analyzes the ICM20948 Data Ready interrupt implementation and how it triggers PX4 to read IMU data on the Renesas FPB-RA8E1 platform.

## Data Flow Architecture

### 1. Hardware Setup
**Pin Configuration** (from `board_config.h`):
```c
#define GPIO_SPI1_IMU_DRDY  GPIO_IRQ6_P409
```

**Pin Details**:
- **Physical Pin**: P409 (PORT4, PIN9)
- **IRQ Number**: IRQ6 (External Interrupt 6)
- **Mode**: Interrupt input with pull-up resistor
- **Definition**: `(PORT4 | PIN9 | R_PFS_PCR | R_PFS_ISEL)`

### 2. Interrupt Registration Flow

#### Step 1: Driver Initialization
**File**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp`

```cpp
ICM20948::ICM20948(const I2CSPIDriverConfig &config) :
    _drdy_gpio(config.drdy_gpio),  // Store DRDY GPIO pin
    ...
{
    if (_drdy_gpio != 0) {
        // Allocate performance counter for missed interrupts
        _drdy_missed_perf = perf_alloc(PC_COUNT, MODULE_NAME": DRDY missed");
    }
}
```

#### Step 2: Configure DRDY Interrupt
**File**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp` (line 487-494)

```cpp
bool ICM20948::DataReadyInterruptConfigure()
{
    if (_drdy_gpio == 0) {
        return false;  // No DRDY pin configured
    }

    // Setup data ready on RISING edge (ICM20948 DRDY is active HIGH)
    return px4_arch_gpiosetevent(_drdy_gpio,
                                 true,   // rising edge
                                 false,  // not falling edge
                                 true,   // event-driven
                                 &DataReadyInterruptCallback,
                                 this) == 0;
}
```

**Key Parameters**:
- **Rising Edge**: `true` - ICM20948 DRDY goes HIGH when data is ready
- **Falling Edge**: `false` - We don't care about falling edge
- **Event Mode**: `true` - Enable interrupt-driven operation
- **Callback**: `DataReadyInterruptCallback` - Function called on interrupt
- **Context**: `this` - Pointer to ICM20948 driver instance

#### Step 3: Platform GPIO Interrupt Setup
**File**: `platforms/nuttx/src/px4/renesas/ra8/include/px4_arch/micro_hal.h`

```c
// Maps PX4 API to RA8 NuttX implementation
#define px4_arch_gpiosetevent(pinset,r,f,e,fp,a) ra_gpiosetevent(pinset,r,f,e,fp,a)
```

#### Step 4: RA8 GPIO Interrupt Implementation
**File**: `platforms/nuttx/NuttX/nuttx/arch/arm/src/ra8/ra_gpio.c` (line 655-818)

```c
int ra_gpiosetevent(uint32_t pinset, bool rising, bool falling,
                    bool event, xcpt_t func, void *arg)
{
    // 1. Extract port and pin from pinset (P409 → PORT4, PIN9)
    port = GPIO_GET_PORT(pinset);
    pin = GPIO_GET_PIN(pinset);

    // 2. Find which external IRQ is associated with this pin (IRQ6)
    irq_num = ra_gpio_find_irq(pinset);

    // 3. Get ICU event number for this IRQ
    icu_event = ra_gpio_get_irq_event(irq_num);

    // 4. Configure pin PFS register
    pfs_value |= R_PFS_ISEL;           // Enable IRQ input
    pfs_value |= R_PFS_EOFR_01;        // Detect rising edge
    pfs_value &= ~(1 << R_PFS_PDR);    // Set as input

    // 5. Attach ICU interrupt handler
    icu_irq = ra_icu_attach(icu_event, ra_gpio_irq_handler,
                           &g_gpio_irqs[slot], true);

    // 6. Configure external IRQ edge detection
    ra_icu_filter_config(irq_num, RA_ICU_IRQ_EDGE_RISING, ...);

    // 7. Store callback information
    g_gpio_irqs[slot].callback = func;  // DataReadyInterruptCallback
    g_gpio_irqs[slot].arg = arg;        // ICM20948 instance pointer

    return OK;
}
```

### 3. Interrupt Handling Flow

#### Hardware Event Chain:
```
ICM20948 Sensor
  ↓ (Data ready)
DRDY Pin (P409) goes HIGH
  ↓
RA8 External IRQ6 triggered
  ↓
ICU (Interrupt Control Unit) activates
  ↓
ra_gpio_irq_handler() called
  ↓
Calls stored callback: DataReadyInterruptCallback()
  ↓
ICM20948::DataReady() executed
```

#### Interrupt Service Routine
**File**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp` (line 471-474)

```cpp
int ICM20948::DataReadyInterruptCallback(int irq, void *context, void *arg)
{
    // Called from ISR context - must be fast!
    static_cast<ICM20948 *>(arg)->DataReady();
    return 0;
}
```

#### Data Ready Handler
**File**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp` (line 476-484)

```cpp
void ICM20948::DataReady()
{
    // Count DRDY interrupts until we have enough samples
    if (++_drdy_count >= _fifo_gyro_samples) {
        // Store timestamp when FIFO should have enough data
        _drdy_timestamp_sample.store(hrt_absolute_time());

        // Reset counter for next batch
        _drdy_count -= _fifo_gyro_samples;

        // Schedule immediate read from work queue (not ISR context)
        ScheduleNow();
    }
}
```

**Key Points**:
- **Interrupt Counting**: Accumulates DRDY events
- **FIFO Threshold**: Waits for `_fifo_gyro_samples` worth of data
- **Timestamp Capture**: Records exact time for data synchronization
- **Deferred Processing**: `ScheduleNow()` schedules read in work queue thread

### 4. Data Reading (Work Queue Context)

#### Run Implementation
**File**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp` (line 243-260)

```cpp
case STATE::FIFO_READ:
{
    // Get timestamp captured in ISR
    const hrt_abstime drdy_timestamp_sample = _drdy_timestamp_sample.fetch_and(0);

    if ((now - drdy_timestamp_sample) < _fifo_empty_interval_us) {
        // Use precise interrupt timestamp
        timestamp_sample = drdy_timestamp_sample;
    } else {
        // Interrupt was missed - increment performance counter
        perf_count(_drdy_missed_perf);
    }

    // Read FIFO via SPI
    transferhrt_abstime FIFORead(timestamp_sample);

    // ... process data ...
}
```

## Configuration Requirements

### 1. ICM20948 Sensor Register Configuration

**Interrupt Pin Configuration** (Register BANK_0::INT_PIN_CFG):
```cpp
{ Register::BANK_0::INT_PIN_CFG, INT_PIN_CFG_BIT::INT1_ACTL, 0 }
```
- **INT1_ACTL**: Sets interrupt pin polarity (active high/low)

**Interrupt Enable** (Register BANK_0::INT_ENABLE_1):
```cpp
{ Register::BANK_0::INT_ENABLE_1, INT_ENABLE_1_BIT::RAW_DATA_0_RDY_EN, 0 }
```
- **RAW_DATA_0_RDY_EN**: Enables data ready interrupt

### 2. Board Pin Configuration

**Initial Configuration** (from `boards/renesas/fpb-ra8e1/src/init.c`):
```c
/* Configure IMU data ready pin - driver will set up interrupt */
px4_arch_configgpio(GPIO_SPI1_IMU_DRDY);
```

**Pin Definition** (from `board_config.h`):
```c
#define GPIO_SPI1_IMU_DRDY  GPIO_IRQ6_P409
```

**Hardware Mapping** (from `ra8e1_pinmap.h`):
```c
#define GPIO_IRQ6_P409  (gpio_pinset_t)(PORT4 | PIN9 | R_PFS_PCR | R_PFS_ISEL)
```
- **R_PFS_PCR**: Pull-up control register bit
- **R_PFS_ISEL**: Interrupt select bit

## Timing Characteristics

### Sample Rate Configuration
```cpp
static constexpr float GYRO_RATE{9000.f};          // 9 kHz gyro
static constexpr float ACCEL_RATE{4500.f};         // 4.5 kHz accel
static constexpr int32_t SAMPLES_PER_TRANSFER{2};  // Read every 2 samples
```

### FIFO Timing
```cpp
uint16_t _fifo_empty_interval_us{1250};  // Default 1250 µs = 800 Hz
int32_t _fifo_gyro_samples{static_cast<int32_t>(_fifo_empty_interval_us / (1000000 / GYRO_RATE))};
```

**Calculation**:
- GYRO_RATE = 9000 Hz
- Period = 1000000 µs / 9000 Hz ≈ 111 µs per sample
- With 1250 µs interval: ~11 samples accumulated before read

## Current Implementation Status

### ✅ What's Working
1. **Pin Configuration**: GPIO_IRQ6_P409 defined correctly
2. **Hardware Support**: `ra_gpiosetevent()` implemented in NuttX
3. **Interrupt Registration**: Platform macro maps to RA8 function
4. **ICU Integration**: External IRQ6 properly routed through ICU

### ⚠️ Potential Issues

#### Issue 1: Interrupt Not Configured During Init
**Problem**: The interrupt might not be set up when the driver starts.

**Location**: `src/drivers/imu/invensense/icm20948/ICM20948.cpp` (line 217)

```cpp
case STATE::CONFIGURE:
    // ... sensor configuration ...

    if (DataReadyInterruptConfigure()) {
        _data_ready_interrupt_enabled = true;
        // Interrupt configured successfully
    }
```

**Verification Needed**:
- Check if `DataReadyInterruptConfigure()` is actually called
- Verify `_data_ready_interrupt_enabled` flag is set
- Confirm `_drdy_gpio` is non-zero when passed from board config

#### Issue 2: Pin Mode Conflict
**Problem**: Pin might be configured incorrectly in board initialization.

**Current Init** (`init.c`):
```c
px4_arch_configgpio(GPIO_SPI1_IMU_DRDY);
```

**Should Be**: Let the driver configure it, or ensure it's input with pull-up:
```c
// Option 1: Let driver handle it (remove from init.c)

// Option 2: Configure as input explicitly
#define GPIO_SPI1_IMU_DRDY  (PORT4 | PIN9 | GPIO_INPUT | R_PFS_PCR | R_PFS_ISEL)
```

#### Issue 3: ICU/IRQ Routing
**Problem**: External IRQ6 might not be properly routed in ICU.

**Check Required**:
1. Verify IRQ6 is enabled in ICU
2. Confirm ICU event table is set up correctly
3. Check interrupt priority configuration

## Debugging Steps

### 1. Verify DRDY Pin State
```bash
nsh> gpio -l | grep P409
```
Expected: Should show pin configured as input

### 2. Check Interrupt Registration
Add debug output in `ICM20948::DataReadyInterruptConfigure()`:
```cpp
bool ICM20948::DataReadyInterruptConfigure()
{
    PX4_INFO("Configuring DRDY interrupt on GPIO 0x%08x", _drdy_gpio);

    if (_drdy_gpio == 0) {
        PX4_ERR("DRDY GPIO is zero!");
        return false;
    }

    int ret = px4_arch_gpiosetevent(_drdy_gpio, true, false, true,
                                    &DataReadyInterruptCallback, this);

    PX4_INFO("gpiosetevent returned: %d", ret);
    return ret == 0;
}
```

### 3. Monitor Interrupt Activity
Add counter in `DataReady()`:
```cpp
void ICM20948::DataReady()
{
    static uint32_t irq_count = 0;
    if (++irq_count % 1000 == 0) {
        PX4_INFO("DRDY IRQ count: %u", irq_count);
    }

    if (++_drdy_count >= _fifo_gyro_samples) {
        _drdy_timestamp_sample.store(hrt_absolute_time());
        _drdy_count -= _fifo_gyro_samples;
        ScheduleNow();
    }
}
```

### 4. Check Performance Counters
```bash
nsh> icm20948 status
```
Look for:
- **DRDY missed**: Should be 0 or very low
- **FIFO empty**: Should have reasonable count

### 5. Verify SPI Configuration
Since you've already implemented `ra_spi_get_dev_config()`, verify:
```bash
nsh> icm20948 start -s
# Should see debug output about 7 MHz, Mode 3
```

## Recommended Fixes

### Fix 1: Ensure Driver Config Passes DRDY GPIO

**File**: `boards/renesas/fpb-ra8e1/src/spi.cpp`

Verify the SPI bus configuration includes DRDY:
```cpp
constexpr px4_spi_bus_t px4_spi_buses[SPI_BUS_MAX_BUS_ITEMS] = {
    initSPIBus(SPI::Bus::SPI1, {
        // ICM-20948: MUST include DRDY parameter
        initSPIDevice(DRV_IMU_DEVTYPE_ICM20948,
                     SPI::CS{GPIO::Port4, GPIO::Pin8},
                     SPI::DRDY{GPIO::Port4, GPIO::Pin9}),  // ← CRITICAL!

        // BMP388: No DRDY needed
        initSPIDevice(DRV_BARO_DEVTYPE_BMP388,
                     SPI::CS{GPIO::Port4, GPIO::Pin7}),
    }),
};
```

### Fix 2: Add Debug Output to Init

**File**: `boards/renesas/fpb-ra8e1/src/init.c`

```c
static void fpb_ra8e1_gpio_initialize(void)
{
    /* ... existing LED and CS setup ... */

    /* Configure IMU data ready pin */
    int ret = px4_arch_configgpio(GPIO_SPI1_IMU_DRDY);
    syslog(LOG_INFO, "Configured DRDY pin P409 (IRQ6): ret=%d\n", ret);

    /* Read back pin state to verify */
    bool state = px4_arch_gpioread(GPIO_SPI1_IMU_DRDY);
    syslog(LOG_INFO, "DRDY pin initial state: %d\n", state);
}
```

### Fix 3: Verify ICU Configuration

Check that ICU is properly initialized for external interrupts. This should be automatic in NuttX, but verify in startup logs.

## Summary

**DRDY Implementation Flow**:
1. ✅ **Hardware**: Pin P409 mapped to IRQ6
2. ✅ **NuttX Driver**: `ra_gpiosetevent()` implemented
3. ✅ **PX4 Platform**: Macro maps to RA8 function
4. ⚠️ **Driver Setup**: May need verification
5. ⚠️ **Pin Config**: Should be input with interrupt capability

**Most Likely Issue**:
The DRDY GPIO might not be properly passed from the board configuration to the ICM20948 driver. Check the `initSPIDevice()` call to ensure DRDY parameter is included.

**Next Steps**:
1. Verify DRDY parameter in `spi.cpp` SPI bus configuration
2. Add debug output to confirm interrupt registration
3. Monitor interrupt counter in `DataReady()` function
4. Check for "DRDY missed" performance counter

The architecture is sound - it's likely a configuration or initialization order issue preventing the interrupt from being set up correctly.
