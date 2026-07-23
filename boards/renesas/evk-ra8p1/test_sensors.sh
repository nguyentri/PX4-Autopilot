#!/bin/sh
#
# Comprehensive sensor integration test for EVK-RA8P1
# This script verifies that ICM20948 and BMP388 are working correctly on SPI
#

echo "=== EVK-RA8P1 Sensor Integration Test ==="
echo

echo "1. Checking driver status..."
echo "----------------------------------------"
echo "ICM20948 Status:"
icm20948 status
echo
echo "BMP388 Status:"
bmp388 status
echo

echo "2. Checking for active sensor topics..."
echo "----------------------------------------"
uorb list | grep -E "(sensor_accel|sensor_gyro|sensor_mag|sensor_baro)"
echo

echo "3. Quick sensor data check (5 samples each)..."
echo "----------------------------------------"
echo "Accelerometer data (should show ~9.8 on Z when level):"
timeout 5 listener sensor_accel | head -5
echo
echo "Gyroscope data (should be near zero when stationary):"
timeout 5 listener sensor_gyro | head -5
echo
echo "Magnetometer data (should change when rotating board):"
timeout 5 listener sensor_mag | head -5
echo
echo "Barometer data (should show atmospheric pressure):"
timeout 5 listener sensor_baro | head -5
echo

echo "4. System health check..."
echo "----------------------------------------"
commander status
echo

echo "5. Memory usage..."
echo "----------------------------------------"
free
echo

echo "=== Test Complete ==="
echo "Expected results:"
echo "- ICM20948: Should show SPI bus 1, status OK"
echo "- BMP388: Should show SPI bus 1, status OK"
echo "- Accel Z: ~9.8 m/s² when board is level"
echo "- Gyro: ~0 when stationary"
echo "- Mag: Values change when board rotates"
echo "- Baro: ~101325 Pa at sea level"
