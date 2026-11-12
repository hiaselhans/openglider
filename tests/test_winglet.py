import os
import tempfile
import unittest

import odfdo

import openglider
from openglider.glider.winglet import WingletGeometry, add_default_winglet
from openglider.plots import Patterns
from openglider.plots.glider import PlotMaker
from openglider.plots.glider.winglet import get_winglet_marks


class TestWinglet(unittest.TestCase):
    def setUp(self) -> None:
        self.plain = openglider.load(openglider.get_demowing_path())
        self.project = openglider.load(openglider.get_demowing_path())
        add_default_winglet(self.project.glider)

    def test_glider_unchanged(self) -> None:
        # the airfoils and ballooning of the winglet at the end of the lists change nothing
        plain = self.plain.glider.get_glider_3d()
        with_winglet = self.project.glider.get_glider_3d()
        for rib, rib_winglet in zip(plain.ribs, with_winglet.ribs):
            self.assertAlmostEqual(rib.chord, rib_winglet.chord, places=9)
            self.assertAlmostEqual(rib.profile_2d.thickness, rib_winglet.profile_2d.thickness, places=9)
        for cell, cell_winglet in zip(plain.cells, with_winglet.cells):
            self.assertAlmostEqual(cell.ballooning[0.5], cell_winglet.ballooning[0.5], places=9)

    def test_stored_in_the_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "winglet.ods")
            self.project.save(path)
            sheets = [table.name for table in odfdo.Document(path).body.get_tables()]
            back = openglider.load(path)

        self.assertIn("Winglet", sheets)
        self.assertEqual(sheets.count("Winglet"), 1)

        winglet, winglet_back = self.project.glider.winglet, back.glider.winglet
        assert winglet is not None and winglet_back is not None
        self.assertEqual(list(winglet.profile_merge_curve.controlpoints.nodes[0]), list(winglet_back.profile_merge_curve.controlpoints.nodes[0]))
        self.assertEqual(list(winglet.ballooning_merge_curve.controlpoints.nodes[0]), list(winglet_back.ballooning_merge_curve.controlpoints.nodes[0]))
        self.assertAlmostEqual(winglet.shape.span, winglet_back.shape.span, places=6)
        self.assertAlmostEqual(winglet.shape.area, winglet_back.shape.area, places=6)
        self.assertEqual(winglet.shape.cell_num, winglet_back.shape.cell_num)
        # the airfoils and ballooning of the winglet are in the lists of the glider
        self.assertEqual(len(self.project.glider.profiles), len(back.glider.profiles))
        self.assertEqual(len(self.project.glider.balloonings), len(back.glider.balloonings))
        self.assertAlmostEqual(self.project.glider.shape.span, back.glider.shape.span, places=6)

    def test_marks_on_the_upper_panels(self) -> None:
        glider = self.project.get_glider_3d()
        plotmaker = PlotMaker(glider, Patterns(self.project).config)

        def count_rings(angle: float) -> int:
            assert self.project.glider.winglet is not None
            self.project.glider.winglet.angle = angle
            winglet = WingletGeometry.from_project(self.project)
            assert winglet is not None
            marks = get_winglet_marks(winglet, glider, plotmaker._get_cellplotmaker)
            self.assertTrue(marks)
            for panel_marks in marks.values():
                for panel in panel_marks:
                    self.assertFalse(panel.is_lower())
            return sum(len(mark) == 1 for panel_marks in marks.values() for found in panel_marks.values() for mark in found)

        # turned, the footprint runs over the ribs onto the cells next to it: no ring is lost
        straight = count_rings(0.)
        self.assertGreater(straight, 0)
        self.assertGreaterEqual(count_rings(20.), straight - 2)

    def test_mesh_stands_on_the_surface(self) -> None:
        winglet = WingletGeometry.from_project(self.project)
        assert winglet is not None
        glider = self.project.get_glider_3d()
        cell_index, span_position = winglet.get_cell(glider)
        nose, _, normal, _, _ = winglet._get_surface_frame(glider.cells[cell_index], span_position)

        # it stands on the ballooned cloth, which bulges up to a few cm over the plane of its nose
        heights = [(point - nose).dot(normal) for point in winglet.get_mesh(glider).point_vectors()]
        self.assertGreater(max(heights), winglet.height)
        self.assertLess(max(heights), winglet.height + 0.03)

        # its root on that cloth, wherever along the chord and across the cell
        from openglider.airfoil import get_x_value
        from openglider.glider.winglet import _Surface
        cell = glider.cells[cell_index]
        surface = _Surface(glider, cell_index, span_position, winglet.chord_start, winglet.chord_end)
        for along in (0.0, 0.3, 0.6, 1.0):
            for across in (-0.05, 0.0, 0.05):
                x = winglet.chord_start + (winglet.chord_end - winglet.chord_start) * along
                cloth = cell.midrib(span_position + across / surface.width)[get_x_value(surface.x_values, -x)]
                self.assertLess((cloth - surface.get(along, across)).length(), 1e-3)


if __name__ == "__main__":
    unittest.main()
