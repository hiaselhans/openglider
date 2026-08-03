from __future__ import annotations

from tests.helpers import GliderTestCase

from openglider.glider.uv_map import UVMap


class UVMapStackedLayoutTest(GliderTestCase):
    def test_stacked_panel_shape_preserves_shape_curves(self) -> None:
        uv_map = UVMap(self.parametric_glider)
        shape = self.parametric_glider.shape.get_half_shape()
        panel = self.glider.cells[0].panels[0]

        def normalize_x(value: float) -> float:
            if panel.is_lower():
                return max(float(value), 0.0)
            return max(float(-value), 0.0)

        polygon = uv_map._get_panel_shape(0, panel, shape)

        expected = [
            shape.get_point(0, normalize_x(panel.cut_back.x_left)),
            shape.get_point(1, normalize_x(panel.cut_back.x_right)),
            shape.get_point(1, normalize_x(panel.cut_front.x_right)),
            shape.get_point(0, normalize_x(panel.cut_front.x_left)),
        ]

        for actual, target in zip(polygon, expected):
            self.assertAlmostEqual(float(actual[0]), float(target[0]))
            self.assertAlmostEqual(float(actual[1]), float(target[1]))

    def test_stacked_layout_separates_upper_above_lower(self) -> None:
        uv_map = UVMap(self.parametric_glider)
        stacked = uv_map._get_stacked_uv_polys()

        upper_y = []
        lower_y = []
        for (cell_no, panel_idx), polyline in stacked.items():
            panel = self.glider.cells[cell_no].panels[panel_idx]
            ys = [float(point[1]) for point in polyline]
            if panel.is_lower():
                lower_y.extend(ys)
            else:
                upper_y.extend(ys)

        self.assertTrue(upper_y)
        self.assertTrue(lower_y)
        self.assertGreater(min(upper_y), max(lower_y))
