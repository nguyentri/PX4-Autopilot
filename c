#!/bin/bash
set -e
export GIT_SUBMODULES_ARE_EVIL=1
cd ./platforms/nuttx/NuttX/nuttx
make distclean
cd ../../../..
make distclean
#echo "y" | make renesas_fpb-ra8e1_default
echo "y" | make renesas_evk-ra8p1_default
#echo "y" | make renesas_rdk-rzv2h_default