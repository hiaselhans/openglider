import unittest

import openglider.rs


class TestPolyline(unittest.TestCase):
    def setUp(self):
        self.p1 = openglider.rs.vector.PolyLine2D([
            [1.7273, 9.5983],
            [1.3771, -0.3956],
            [0.9972, -0.3956],
            [0.9909, -0.3922],
            [1.2346, 9.6048],
            [1.7273, 9.5983]
            ])

        self.p2 = openglider.rs.vector.PolyLine2D([
            [0, 0],
            [0.8974, -0.0130],
            [1.0935, -0.0193],
            [1.2883, -0.0268],
            [1.4817, -0.0357],
            [2, 0],
            [2, -1],
            [0, -1],
            [0, 0]
        ])

    def test_union(self):
        union = self.p1.bool_union(self.p2)
        self.assertGreaterEqual(len(union), 1)

    def test_bool_intersection_area(self):
        left = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ])
        right = openglider.rs.vector.PolyLine2D([
            [1.0, 1.0],
            [3.0, 1.0],
            [3.0, 3.0],
            [1.0, 3.0],
            [1.0, 1.0],
        ])

        intersections = left.bool_intersection(right)

        self.assertEqual(len(intersections), 1)
        self.assertAlmostEqual(intersections[0].get_area(), 1.0, places=6)

    def test_bool_union_area(self):
        left = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ])
        right = openglider.rs.vector.PolyLine2D([
            [1.0, 1.0],
            [3.0, 1.0],
            [3.0, 3.0],
            [1.0, 3.0],
            [1.0, 1.0],
        ])

        union = left.bool_union(right)

        self.assertEqual(len(union), 1)
        self.assertAlmostEqual(sum(poly.get_area() for poly in union), 7.0, places=6)

    def test_bool_intersection_clips_open_polyline(self):
        polygon = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ])
        path = openglider.rs.vector.PolyLine2D([
            [-1.0, 1.0],
            [1.0, 1.0],
            [3.0, 1.0],
        ])

        clipped = polygon.bool_intersection(path)

        self.assertEqual(len(clipped), 1)
        points = list(clipped[0])
        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[0][0], 0.0, places=6)
        self.assertAlmostEqual(points[0][1], 1.0, places=6)
        self.assertAlmostEqual(points[1][0], 1.0, places=6)
        self.assertAlmostEqual(points[1][1], 1.0, places=6)
        self.assertAlmostEqual(points[2][0], 2.0, places=6)
        self.assertAlmostEqual(points[2][1], 1.0, places=6)

    def test_clip_by_closed_outline(self):
        polygon = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
            [0.0, 0.0],
        ])
        path = openglider.rs.vector.PolyLine2D([
            [-1.0, 1.0],
            [1.0, 1.0],
            [3.0, 1.0],
        ])

        clipped = path.clip(polygon)

        self.assertEqual(len(clipped), 1)
        points = list(clipped[0])
        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[0][0], 0.0, places=6)
        self.assertAlmostEqual(points[0][1], 1.0, places=6)
        self.assertAlmostEqual(points[1][0], 1.0, places=6)
        self.assertAlmostEqual(points[1][1], 1.0, places=6)
        self.assertAlmostEqual(points[2][0], 2.0, places=6)
        self.assertAlmostEqual(points[2][1], 1.0, places=6)

    def test_clip_by_open_outline_quad(self):
        polygon = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 2.0],
            [0.0, 2.0],
        ])
        path = openglider.rs.vector.PolyLine2D([
            [-1.0, 1.0],
            [1.0, 1.0],
            [3.0, 1.0],
        ])

        clipped = path.clip(polygon)

        self.assertEqual(len(clipped), 1)
        points = list(clipped[0])
        self.assertEqual(len(points), 3)
        self.assertAlmostEqual(points[0][0], 0.0, places=6)
        self.assertAlmostEqual(points[1][0], 1.0, places=6)
        self.assertAlmostEqual(points[2][0], 2.0, places=6)

    def test_area_is_positive_for_reversed_winding(self):
        forward = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [2.0, 0.0],
            [2.0, 1.0],
            [0.0, 1.0],
            [0.0, 0.0],
        ])
        reverse = openglider.rs.vector.PolyLine2D([
            [0.0, 0.0],
            [0.0, 1.0],
            [2.0, 1.0],
            [2.0, 0.0],
            [0.0, 0.0],
        ])

        self.assertAlmostEqual(forward.get_area(), 2.0, places=6)
        self.assertAlmostEqual(reverse.get_area(), 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
