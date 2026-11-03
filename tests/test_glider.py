import random
import unittest
from types import SimpleNamespace

from openglider.glider.glider import Glider
from openglider.gui.qt import QtWidgets
from openglider.gui.views.airfoils import AirfoilEntry, ApplyAirfoilsDialog, _KEY_ROLE
from tests.helpers import GliderTestCase


class TestGlider(GliderTestCase):
    #def __init__(self):
    #    unittest.TestCase.__init__(self)

    def test_numpoints(self) -> None:
        numpoints = random.randint(1, 100)*2+1
        self.glider.profile_numpoints = numpoints
        self.assertEqual(self.glider.profile_numpoints, numpoints)

    def test_profile_3d_x_values_refresh_with_numpoints(self) -> None:
        rib = self.glider.ribs[0]
        old_x_values = rib.profile_3d.x_values[:]

        self.glider.profile_numpoints = self.glider.profile_numpoints + 2

        self.assertEqual(rib.profile_3d.x_values, rib.profile_2d.x_values)
        self.assertNotEqual(rib.profile_3d.x_values, old_x_values)

    def test_span(self) -> None:
        span = random.random() * 100
        self.glider.span = span
        self.assertAlmostEqual(self.glider.span, span)

    def test_area(self) -> None:
        area = random.random() * 100
        self.glider.area = area
        self.assertAlmostEqual(self.glider.area, area)

    def test_aspectratio(self) -> None:
        ar = random.randint(4, 15) + random.random()
        area_bak = self.glider.area
        for i in range(15):
            self.glider.aspect_ratio = ar  # -> Do some times and its precise
        self.assertAlmostEqual(area_bak, self.glider.area)
        self.assertAlmostEqual(ar, self.glider.aspect_ratio, 3)

    def test_scale(self) -> None:
        ar = self.glider.aspect_ratio
        self.glider.scale(1+random.random())
        self.assertAlmostEqual(ar, self.glider.aspect_ratio)

    def test_flatten(self) -> None:
        y = random.random()*len(self.glider.cells)
        self.glider.get_midrib(y).flatten()

    def copy_complete(self) -> None:
        self.glider.copy_complete()

    def test_mean_rib(self) -> None:
        for cell in self.glider.cells:
            cell.mean_airfoil(10)

    def test_apply_airfoils_creates_new_revision_entry(self) -> None:
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        app_obj = SimpleNamespace()
        app_obj.glider_projects = [self.project]
        app_obj.state = SimpleNamespace(projects=SimpleNamespace(selected_element=self.project.name))
        app_obj.glider_list = SimpleNamespace(render=lambda: None)
        app_obj.current_glider_changed = lambda: None
        app_obj.update_menu = lambda: None
        app_obj.airfoil_view = SimpleNamespace(refresh=lambda: None)
        app_obj.add_glider_calls = []

        def add_glider(glider, focus=True, increase_revision=False):
            app_obj.add_glider_calls.append((glider, focus, increase_revision))

        app_obj.add_glider = add_glider

        entry = AirfoilEntry(
            key="demo-airfoil",
            source="test",
            name="demo-airfoil",
            airfoil=self.project.glider.profiles[0].copy(),
        )

        dialog = ApplyAirfoilsDialog(app_obj, [entry])
        item = QtWidgets.QListWidgetItem()
        item.setData(_KEY_ROLE, entry.key)
        dialog.selected_list.addItem(item)

        dialog._apply()

        self.assertEqual(len(app_obj.add_glider_calls), 1)
        self.assertTrue(app_obj.add_glider_calls[0][2])
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Accepted)


if __name__ == '__main__':
    unittest.main(verbosity=2)
