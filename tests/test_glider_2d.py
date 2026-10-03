import unittest

import tempfile
from tests.helpers import GliderTestCase
from openglider import jsonify

TEMPDIR =  tempfile.gettempdir()

class GliderTestCase2D(GliderTestCase):
    def test_create_glider(self) -> None:
        glider = self.parametric_glider.get_glider_3d()
        self.assertAlmostEqual(glider.span, self.parametric_glider.shape.span, 2)

    def test_get_panels_skips_empty_material_entries(self) -> None:
        baseline_panels = self.parametric_glider.get_panels()
        self.assertGreater(len(baseline_panels[0]), 0)

        original_get = self.parametric_glider.tables.material_cells.get

        def get_with_empty_first_material(row_no: int, keywords: list[str] | None=None, **kwargs: object) -> object:
            materials = original_get(row_no, keywords=keywords, **kwargs)
            if row_no == 0 and materials:
                materials = materials.copy()
                materials[0] = None
            return materials

        self.parametric_glider.tables.material_cells.get = get_with_empty_first_material  # type: ignore[method-assign]
        try:
            panels = self.parametric_glider.get_panels()
        finally:
            self.parametric_glider.tables.material_cells.get = original_get  # type: ignore[method-assign]

        self.assertEqual(len(panels[0]), len(baseline_panels[0]) - 1)

    def test_export(self) -> None:
        exp = jsonify.dumps(self.parametric_glider)
        imp = jsonify.loads(exp)['data']
        self.assertEqualGlider2D(self.parametric_glider, imp)

        #def test_export_ods(self) -> None:

    def test_set_area(self) -> None:
        self.parametric_glider.shape.set_area(10)
        self.assertAlmostEqual(self.parametric_glider.shape.area, 10)

if __name__ == '__main__':
    unittest.main(verbosity=2)