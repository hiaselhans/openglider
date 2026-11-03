import math
import unittest

import numpy as np

from openglider.airfoil import Profile2D
from openglider.airfoil.generators.parsec import ParsecAirfoil, SurfaceParameters, _bspline_basis
from tests.helpers import import_dir


class TestParsecAirfoil(unittest.TestCase):
    def setUp(self) -> None:
        self.surface = SurfaceParameters(
            x_max=0.3,
            y_max=0.08,
            nose_radius=0.04,
            angle_front=0.1,
            front_percentage=0.3,
            top_radius=0.1,
            rear_factor=0.9,
            trailing_edge_angle=0.2,
            trailing_edge_factor=0.5
        )
        self.parsec = ParsecAirfoil(
            upper=self.surface,
            lower=SurfaceParameters(x_max=0.4, y_max=0.02, nose_radius=0.015, top_radius=0.1, trailing_edge_angle=0.05)
        )

    def test_control_points(self) -> None:
        front, rear = self.surface.control_points()

        # front curve
        np.testing.assert_allclose(front[0], [0, 0])
        np.testing.assert_allclose(front[1], [0, 0.04])

        def rotate(point: np.ndarray, angle: float) -> np.ndarray:
            rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
            return rotation @ point

        a = np.array([0.2, 0.08]) * 0.5
        np.testing.assert_allclose(
            front[2],
            rotate(a, 0.1) + rotate(a, 0.1 + math.pi / 2) * 0.3
        )
        np.testing.assert_allclose(front[3], [0.2, 0.08])
        np.testing.assert_allclose(front[4], [0.3, 0.08])

        # rear curve
        np.testing.assert_allclose(rear[0], [0.3, 0.08])
        np.testing.assert_allclose(rear[1], [0.4, 0.08])
        # interpolated between (x_max + top_radius) and the trailing edge
        x1 = 0.4 + 0.6 / 3
        x2 = 0.4 + 0.6 * 2 / 3
        np.testing.assert_allclose(rear[2], [x1, 0.08 * 2 / 3 * 0.9])
        y2 = 0.5 * 0.08 / 3 + 0.5 * math.tan(0.2) * (1 - x2)
        np.testing.assert_allclose(rear[3], [x2, y2])
        np.testing.assert_allclose(rear[4], [1, 0])

    def test_curve_ranges(self) -> None:
        # front: x = 0 ... x_max, rear: x = x_max ... 1 (monotonic), also for extreme parameters
        for angle in (-1.5, -0.5, 0., 0.5, 1.5):
            for percentage in (-1., 0., 0.5, 1.):
                surface = SurfaceParameters(x_max=0.3, y_max=0.08, angle_front=angle, front_percentage=percentage)
                front, rear = surface.control_points()

                self.assertEqual(front[0][0], 0)
                self.assertAlmostEqual(front[-1][0], 0.3)
                self.assertTrue(np.all(np.diff(front[:, 0]) >= -1e-12), front)
                self.assertAlmostEqual(rear[0][0], 0.3)
                self.assertEqual(rear[-1][0], 1)
                self.assertTrue(np.all(np.diff(rear[:, 0]) >= -1e-12), rear)

                polyline = surface.polyline()
                self.assertTrue(np.all(np.diff(polyline[:, 0]) >= -1e-12))
                self.assertGreaterEqual(polyline[:, 0].min(), 0)
                self.assertLessEqual(polyline[:, 0].max(), 1)

    def test_rear_factors(self) -> None:
        # 100%: no offset from the interpolation between maximum and trailing edge
        surface = SurfaceParameters(x_max=0.3, y_max=0.09, rear_factor=1., trailing_edge_factor=1.)
        _, rear = surface.control_points()

        self.assertAlmostEqual(rear[2][1], 0.06)
        self.assertAlmostEqual(rear[3][1], 0.03)

    def test_matches_rust_bspline(self) -> None:
        curves = self.parsec.get_curves()
        self.assertEqual(set(curves), {"upper_front", "upper_rear", "lower_front", "lower_rear"})

        t_values = (0., 0.2, 0.5, 0.9, 1.)
        basis = _bspline_basis(5, 3, t_values)

        for name, curve in curves.items():
            side, part = name.split("_")
            params = self.parsec.upper if side == "upper" else self.parsec.lower
            points = params.control_points()[0 if part == "front" else 1]
            if side == "lower":
                points = points * np.array([1, -1])

            for t, expected in zip(t_values, basis @ points):
                np.testing.assert_allclose(list(curve.get(t)), expected, atol=1e-12)

    def test_trailing_edge_closed(self) -> None:
        airfoil = self.parsec.get_airfoil(100)
        upper, lower = airfoil.curve.nodes[0], airfoil.curve.nodes[-1]

        self.assertAlmostEqual(upper[0], 1)
        self.assertAlmostEqual(lower[0], 1)
        self.assertAlmostEqual(upper[1], 0)
        self.assertAlmostEqual(lower[1], 0)

    def test_nose(self) -> None:
        airfoil = self.parsec.get_airfoil(100)
        nose = airfoil.curve.nodes[airfoil.noseindex]

        self.assertAlmostEqual(nose[0], 0)
        self.assertAlmostEqual(nose[1], 0)

    def test_surfaces(self) -> None:
        airfoil = self.parsec.get_airfoil(200)

        self.assertAlmostEqual(float(self.parsec.upper_at([0.3])[0]), 0.08, 3)
        self.assertAlmostEqual(float(self.parsec.lower_at([0.4])[0]), -0.02, 3)
        self.assertAlmostEqual(airfoil.thickness, 0.1, 2)

    def test_nose_resolution(self) -> None:
        nodes = np.array([list(p) for p in self.parsec.get_airfoil(60).curve.nodes])
        diff = np.diff(nodes, axis=0)
        heading = np.unwrap(np.arctan2(diff[:, 1], diff[:, 0]))

        self.assertLess(float(np.degrees(np.abs(np.diff(heading)).max())), 15)

    def test_numpoints(self) -> None:
        self.assertEqual(self.parsec.get_airfoil(80).numpoints, 81)

    def test_fit_roundtrip(self) -> None:
        airfoil = self.parsec.get_airfoil(100)
        fit = ParsecAirfoil.fit(airfoil)

        self.assertLess(fit.rms_error, 2e-4)

    def test_fit_airfoil_file(self) -> None:
        airfoil = Profile2D.import_from_dat(import_dir + "/testprofile.dat").normalized()
        fit = ParsecAirfoil.fit(airfoil)

        self.assertLess(fit.rms_error, 1.5e-3)
        self.assertLess(fit.max_error, 4e-3)


if __name__ == "__main__":
    unittest.main()
