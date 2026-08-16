from __future__ import annotations

from tests.helpers import GliderTestCase

import openglider.rs
from openglider.glider.texture.texture import SVGTexture
from openglider.glider.texture.uv_map import mirrored, stacked


class UVMapStackedLayoutTest(GliderTestCase):
    def test_split_classes_exist_and_layouts(self) -> None:
        stacked_map = stacked(self.parametric_glider)
        mirrored_map = mirrored(self.parametric_glider)

        stacked_layout = stacked_map.get_layout()
        mirrored_layout = mirrored_map.get_layout()

        self.assertTrue(stacked_layout.parts)
        self.assertTrue(mirrored_layout.parts)

    def test_svg_texture_uses_viewbox_origin_in_normalization(self) -> None:
        svg = '''
        <svg width="20" height="40" viewBox="-10 -20 20 40">
            <path d="M -10 -20 L 10 20"/>
        </svg>
        '''

        texture = SVGTexture(svg_data=svg, dpi=300)
        vectors = texture.get_vectors((0.0, 1.0, 0.0, 1.0))

        self.assertEqual(len(vectors), 1)
        points = list(vectors[0])
        self.assertAlmostEqual(points[0][0], 0.0)
        self.assertAlmostEqual(points[0][1], 1.0)
        self.assertAlmostEqual(points[1][0], 1.0)
        self.assertAlmostEqual(points[1][1], 0.0)

    def test_svg_texture_applies_group_transform_stack(self) -> None:
        svg = '''
        <svg width="10" height="10" viewBox="0 0 10 10">
            <g transform="scale(1,-1)">
                <path d="M 1 2 L 3 4 M 5 6 L 7 8"/>
            </g>
        </svg>
        '''

        texture = SVGTexture(svg_data=svg, dpi=300)
        vectors = texture.get_vectors((0.0, 1.0, 0.0, 1.0))

        self.assertEqual(len(vectors), 2)
        first = list(vectors[0])
        second = list(vectors[1])
        self.assertAlmostEqual(first[0][0], 0.1)
        self.assertAlmostEqual(first[0][1], 1.2)
        self.assertAlmostEqual(first[1][0], 0.3)
        self.assertAlmostEqual(first[1][1], 1.4)
        self.assertAlmostEqual(second[0][0], 0.5)
        self.assertAlmostEqual(second[0][1], 1.6)
        self.assertAlmostEqual(second[1][0], 0.7)
        self.assertAlmostEqual(second[1][1], 1.8)