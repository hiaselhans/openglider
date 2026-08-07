import math
import unittest

import openglider.rs
import euklid


def sharpest_turn_angle(polyline: openglider.rs.vector.PolyLine2D) -> tuple[int, float]:
    nodes = list(polyline.nodes)
    best_index = -1
    best_angle = -1.0

    for i in range(1, len(nodes) - 1):
        p_prev = nodes[i - 1]
        p = nodes[i]
        p_next = nodes[i + 1]

        v1 = p - p_prev
        v2 = p_next - p
        l1 = v1.length()
        l2 = v2.length()
        if l1 < 1e-10 or l2 < 1e-10:
            continue

        cosang = max(-1.0, min(1.0, v1.normalized().dot(v2.normalized())))
        angle_deg = math.degrees(math.acos(cosang))

        if angle_deg > best_angle:
            best_angle = angle_deg
            best_index = i

    return best_index, best_angle


class TestRigidfoilOffsetSegment(unittest.TestCase):
    def get_data(self):
        return [
            [0.006394281505783397, 0.0062865029643995535],
            [0.006179291372068676, 0.004183100125936744],
            [0.0060433378795087265, 0.0009001960184355397],
            [0.005996321314344388, 0.00021007307095197945],
            [0.006010933756973685, 0.00023999878466742316],
            [0.006133856528670388, -0.0008753607900430715],
            [0.006263706923800042, -0.0016857170452202733],
            [0.006491849797770586, -0.002350251724355395],
        ]

    def test_offset_rs(self) -> None:
        # Extracted from rib 20 rigidfoil center line around the problematic cut area.
        center_segment = openglider.rs.vector.PolyLine2D(self.get_data())

        offset_segment = center_segment.offset(0.016)

        index, angle_deg = sharpest_turn_angle(offset_segment)

        self.assertNotEqual(index, -1)
        # Regression guard: the old algorithm produced ~106 degrees here.
        self.assertLess(angle_deg, 95.0)

    def test_offset_euklid_reference_is_sharp(self) -> None:
        # Reference backend still exhibits the sharp-angle artifact on this segment.
        center_segment = euklid.vector.PolyLine2D(self.get_data())

        offset_segment = center_segment.offset(0.016)

        index, angle_deg = sharpest_turn_angle(offset_segment)

        # expect failing tests in euklid
        self.assertNotEqual(index, -1)
        self.assertGreater(angle_deg, 100.0)


if __name__ == "__main__":
    unittest.main()
