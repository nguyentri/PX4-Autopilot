#!/bin/bash
set -e

# Script to start J-Link GDB Server for RA8E1 debugging
# Usage: ./start_jlink_server.sh

echo "Starting J-Link GDB Server for Renesas RA8E1..."
echo "Device: R7FA8E1AF"
echo "Interface: SWD"
echo "Port: 2331"
echo ""
echo "Make sure your RA8E1 board is connected via USB and powered on."
echo "Press Ctrl+C to stop the server."
echo ""
/home/a5094159/opt/SEGGER/JLink_Linux_V856a_x86_64/JLinkExe \
    -device R7FA8E1AF \
    -if SWD \
    -speed 4000 \
    -autoconnect 1
