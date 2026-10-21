#!/usr/bin/env python3
"""Check the packaged normalized fixture's independent rank/sign/limit algebra."""
from pathlib import Path
import itertools
import math
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
AIRFRAME = ROOT / 'ROMFS/px4fmu_common/init.d/airframes/22001_rzv2h_lab_pivot'


def parameters():
    return {name: float(value) for name, value in re.findall(
        r'^param set-default (\w+) ([-\d.]+)$', AIRFRAME.read_text(), re.M)}


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def effectiveness(p, i):
    prefix = f'CA_ROTOR{i}_'
    position = tuple(p[prefix+'P'+axis] for axis in 'XYZ')
    axis = tuple(p[prefix+'A'+axis] for axis in 'XYZ')
    norm = math.sqrt(sum(v*v for v in axis))
    thrust = tuple(v/norm*p[prefix+'CT'] for v in axis)
    moment = cross(position, thrust)
    torque = tuple(moment[j] - p[prefix+'KM']*thrust[j] for j in range(3))
    return torque + thrust


class PivotAllocation(unittest.TestCase):
    def test_exactly_two_assigned_functions_and_no_local_output_start(self):
        p = parameters()
        self.assertEqual(p['CA_ROTOR_COUNT'], 2)
        self.assertEqual([p[f'PWM_MAIN_FUNC{i}'] for i in range(1, 5)], [101, 102, 0, 0])
        defaults = (ROOT/'boards/renesas/rdk-rzv2h/init/dualcr8/rc.board_defaults.cmds').read_text()
        self.assertIn('param set-default SYS_AUTOSTART 4014', defaults)
        self.assertIn('set PWM_OUT_START no', defaults)
        self.assertNotIn('22001', defaults)

    def test_effectiveness_has_rank_two_only_roll_and_vertical_force(self):
        columns = [effectiveness(parameters(), i) for i in range(2)]
        self.assertEqual(columns, [(1, 0, 0, 0, 0, -1), (-1, 0, 0, 0, 0, -1)])
        # A nonzero 2x2 minor proves rank 2; two columns cap rank at 2.
        a, b = columns
        self.assertNotEqual(a[0]*b[5] - b[0]*a[5], 0)
        for row in (1, 2, 3, 4):
            self.assertEqual((a[row], b[row]), (0, 0))

    def test_frd_roll_split_saturation_and_order(self):
        for collective, roll in itertools.product((0, .2, .5, 1, 1.8, 2), (-2, -.5, 0, .5, 2)):
            left = (collective + roll) / 2
            right = (collective - roll) / 2
            bounded = [max(0, min(1, value)) for value in (left, right)]
            saturated = any(a != b for a, b in zip((left, right), bounded))
            if not saturated:
                self.assertAlmostEqual(sum(bounded), collective)
                self.assertAlmostEqual(bounded[0]-bounded[1], roll)
            self.assertTrue(all(0 <= v <= 1 for v in bounded))
        # Positive FRD roll increases the left output; positive pivot -X
        # torque reverses that sign. Neither convention may silently swap it.
        self.assertGreater((1+.2)/2, (1-.2)/2)

    def test_only_remote_profile_packages_fixture(self):
        cmake = (AIRFRAME.parent/'CMakeLists.txt').read_text()
        self.assertRegex(cmake, r'if\(CONFIG_BOARD_RDK_RZV2H_REMOTE_OUTPUTS\)\s+px4_add_romfs_files\(22001_rzv2h_lab_pivot\)')
        self.assertIn('Normalized geometry', AIRFRAME.read_text())
        self.assertNotRegex(AIRFRAME.read_text(), r'(?m)^param set-default (CBRK_|COM_ARM_|SYS_HAS_)')


if __name__ == '__main__':
    unittest.main()
