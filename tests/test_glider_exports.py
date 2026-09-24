import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import openglider.rs
from openglider.glider.parametric.glider import ParametricGlider
from openglider.plots.sketches.shapeplot import ShapePlot
from tests.helpers import GliderTestCase, os, unittest
from openglider.plots import PlotMaker
from openglider import jsonify

class TestGlider(GliderTestCase):
    def tempfile(self, name: str) -> str:
        return os.path.join(tempfile.gettempdir(), name)

    def test_import_export_ods(self) -> None:
        path = self.tempfile('kite.ods')
        self.parametric_glider.export_ods(path)

    def test_export_obj(self) -> None:
        path = self.tempfile('kite.obj')
        self.glider.get_mesh(midribs=5).export_obj(path)

    def test_export_dxf(self) -> None:
        path = self.tempfile('kite.dxf')
        self.glider.get_mesh(midribs=5).export_dxf(path)

    def test_export_textured_gltf_from_ods(self) -> None:
        if self.glider.texture is None:
            self.skipTest("No texture available for this glider")

        path = self.tempfile("demokite.gltf")

        mesh = self.glider.get_mesh_all(8, True)
        result = mesh.export_gltf(path)

        self.assertTrue(os.path.exists(path))

        with open(path, "w", encoding="utf-8") as outfile:
            outfile.write(result)

        return
    
        with open(path, "r", encoding="utf-8") as infile:
            exported = json.load(infile)

        self.assertEqual(exported["asset"]["version"], "2.0")
        self.assertIn("meshes", exported)
        self.assertIn("buffers", exported)
        self.assertIn("images", exported)
        self.assertIn("textures", exported)
        self.assertGreaterEqual(len(exported["materials"]), 2)
        self.assertGreaterEqual(len(exported["meshes"][0]["primitives"]), 2)

    def test_export_plots(self) -> None:
        path = self.tempfile('kite_plots.svg')
        dxfile = self.tempfile("kite_plots.dxf")
        ntvfile = self.tempfile("kite_plots.ntv")

        patterns = PlotMaker(self.glider)
        patterns.unwrap()

        all_patterns = patterns.get_all_grouped()

        all_patterns.export_svg(path)
        all_patterns.export_dxf(dxfile)
        all_patterns.export_ntv(ntvfile)

    def test_layout_scale_compensates_stroke_width(self) -> None:
        line = openglider.rs.vector.PolyLine2D([[0.0, 0.0], [10.0, 2.0]])
        style = openglider.rs.drawing.LayerStyle(stroke="black", stroke_width=0.25)
        part = openglider.rs.drawing.Part()
        part.add_layer("cuts", style=style)
        part.add_line("cuts", line)

        layout = openglider.rs.drawing.Layout([part])
        scaled = layout.scale(29.7)

        self.assertAlmostEqual(scaled.parts[0].layers["cuts"].style.stroke_width, 0.25 / 29.7, places=6)

    def test_export_glider_json(self) -> None:
        with open(self.tempfile('kite_3d.json'), "w+") as tmp:
            jsonify.dump(self.glider, tmp)
            tmp.seek(0)
            glider = jsonify.load(tmp)['data']
            
        self.assertEqualGlider(self.glider, glider)

    def test_export_glider_ods(self) -> None:
        path = self.tempfile("kite.ods")
        self.parametric_glider.export_ods(path)
        glider_2d_2 = self.parametric_glider.import_ods(path)
        self.assertEqualGlider2D(self.parametric_glider, glider_2d_2)

    def test_export_glider_json2(self) -> None:
        with open(self.tempfile("kite_2d.json"), "w+") as outfile:
            jsonify.dump(self.parametric_glider, outfile)
            outfile.seek(0)
            glider = jsonify.load(outfile)['data']
        self.assertEqualGlider2D(self.parametric_glider, glider)

    def test_export_import_markdown(self) -> None:
        path = self.tempfile("kite.og.md")
        self.project.save(path)
        reloaded = self.project.__class__.import_markdown(path)
        self.assertEqualGlider2D(self.parametric_glider, reloaded.glider)


if __name__ == '__main__':
    unittest.main(verbosity=2)