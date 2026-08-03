from __future__ import annotations

import logging
from collections.abc import Iterable
import math
from xml.etree import ElementTree
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import openglider
import openglider.mesh
import openglider.rs
import svglib.svglib
from PIL import Image
from reportlab.graphics.shapes import Drawing, Group, Line, Path as ReportPath, PolyLine, Polygon
from openglider.vector.drawing import Layout, PlotPart
from openglider.vector.unit import Percentage
from openglider.glider.rib.rib import Rib
from openglider.glider.cell.cell import Cell
from openglider import glider

if TYPE_CHECKING:
    from openglider.glider.cell.panel import Panel


logger = logging.getLogger(__name__)


UVMapMode = Literal["mirrored", "stacked"]


class SVGTexture:
    def __init__(self, file_path: str | Path, dpi: int = 300):
        self.file_path = Path(file_path)
        self.dpi = dpi
        self.width, self.height = self._read_svg_size(self.file_path)
        self._drawing: Drawing | None = None
        self._normalized_vectors: list[openglider.rs.vector.PolyLine2D] | None = None
        self._raster: Image.Image | None = None
        self._raster_by_max_dim: dict[tuple[int, float], Image.Image] = {}

    @staticmethod
    def _parse_svg_length(value: str | None) -> float | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None

        for suffix in ("px", "pt", "pc", "mm", "cm", "in"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break

        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _read_svg_size(cls, file_path: Path) -> tuple[float, float]:
        try:
            root = ElementTree.parse(file_path).getroot()
        except ElementTree.ParseError as err:
            raise ValueError(f"could not read svg file: {file_path}") from err

        width = cls._parse_svg_length(root.get("width"))
        height = cls._parse_svg_length(root.get("height"))

        if width is not None and height is not None:
            return max(width, 1.0), max(height, 1.0)

        view_box = root.get("viewBox") or root.get("viewbox")
        if view_box:
            parts = [part for part in view_box.replace(",", " ").split() if part]
            if len(parts) == 4:
                try:
                    return max(float(parts[2]), 1.0), max(float(parts[3]), 1.0)
                except ValueError:
                    pass

        raise ValueError(f"svg file has no usable size information: {file_path}")

    def _normalize_point(self, x: float, y: float) -> tuple[float, float]:
        u = 0.0 if self.width == 0 else x / self.width
        v = 1.0 if self.height == 0 else 1.0 - y / self.height
        return u, v

    def _get_drawing(self) -> Drawing:
        if self._drawing is None:
            drawing = svglib.svglib.svg2rlg(str(self.file_path))
            if drawing is None:
                raise ValueError(f"could not read svg file: {self.file_path}")
            self._drawing = drawing
        return self._drawing

    def _walk_nodes(self, node: Drawing | Group) -> Iterable[object]:
        if hasattr(node, "contents"):
            for child in node.contents:
                yield child
                if isinstance(child, (Drawing, Group)):
                    yield from self._walk_nodes(child)

    def _extract_path_lines(self, path: ReportPath) -> list[openglider.rs.vector.PolyLine2D]:
        lines: list[openglider.rs.vector.PolyLine2D] = []
        if not path.points:
            return lines

        points = path.points
        operators = path.operators

        cursor = 0
        current_line: list[tuple[float, float]] = []
        first_point: tuple[float, float] | None = None

        for op in operators:
            if op == 0:
                if len(current_line) >= 2:
                    lines.append(openglider.rs.vector.PolyLine2D(current_line))
                x = points[cursor]
                y = points[cursor + 1]
                cursor += 2
                current_line = [self._normalize_point(x, y)]
                first_point = current_line[0]
            elif op == 1:
                x = points[cursor]
                y = points[cursor + 1]
                cursor += 2
                current_line.append(self._normalize_point(x, y))
            elif op == 2:
                if cursor + 5 < len(points):
                    x = points[cursor + 4]
                    y = points[cursor + 5]
                    current_line.append(self._normalize_point(x, y))
                cursor += 6
            elif op == 3:
                if first_point is not None:
                    current_line.append(first_point)
                if len(current_line) >= 2:
                    lines.append(openglider.rs.vector.PolyLine2D(current_line))
                current_line = []
                first_point = None

        if len(current_line) >= 2:
            lines.append(openglider.rs.vector.PolyLine2D(current_line))

        return lines

    def _extract_vectors(self, drawing: Drawing) -> list[openglider.rs.vector.PolyLine2D]:
        vectors: list[openglider.rs.vector.PolyLine2D] = []

        for node in self._walk_nodes(drawing):
            if isinstance(node, Line):
                p1 = self._normalize_point(float(node.x1), float(node.y1))
                p2 = self._normalize_point(float(node.x2), float(node.y2))
                vectors.append(openglider.rs.vector.PolyLine2D([p1, p2]))
            elif isinstance(node, PolyLine):
                points = [self._normalize_point(float(x), float(y)) for x, y in zip(node.points[0::2], node.points[1::2])]
                if len(points) >= 2:
                    vectors.append(openglider.rs.vector.PolyLine2D(points))
            elif isinstance(node, Polygon):
                points = [self._normalize_point(float(x), float(y)) for x, y in zip(node.points[0::2], node.points[1::2])]
                if len(points) >= 2:
                    points.append(points[0])
                    vectors.append(openglider.rs.vector.PolyLine2D(points))
            elif isinstance(node, ReportPath):
                vectors.extend(self._extract_path_lines(node))

        return vectors

    def get_vectors(self, bbox: tuple[float, float, float, float]) -> list[openglider.rs.vector.PolyLine2D]:
        """Return normalized SVG outlines remapped into the requested bbox.

        The ReportLab parse is performed lazily because this path is only needed
        for plotfile-style vector overlays, not for the raster texture pipeline.
        """
        if self._normalized_vectors is None:
            self._normalized_vectors = self._extract_vectors(self._get_drawing())
        return [self._map_to_bbox(polyline, bbox) for polyline in self._normalized_vectors]

    def _map_to_bbox(
        self,
        polyline: openglider.rs.vector.PolyLine2D,
        bbox: tuple[float, float, float, float],
    ) -> openglider.rs.vector.PolyLine2D:
        min_x, max_x, min_y, max_y = bbox
        width = max(max_x - min_x, 1e-9)
        height = max(max_y - min_y, 1e-9)

        mapped = [(min_x + p[0] * width, min_y + p[1] * height) for p in polyline]
        return openglider.rs.vector.PolyLine2D(mapped)

    def _get_raster(self) -> Image.Image:
        if self._raster is None:
            px_w = max(1, int(round(self.width * self.dpi / 72.0)))
            px_h = max(1, int(round(self.height * self.dpi / 72.0)))
            width, height, rgba = openglider.rs.svg_mod.render_svg_rgba(str(self.file_path), px_w, px_h)
            self._raster = Image.frombytes("RGBA", (int(width), int(height)), bytes(rgba))
        return self._raster

    def get_raster_bounded(
        self,
        max_dim: int = 8192,
        precision: float = 1.0,
        cache: bool = True,
    ) -> Image.Image:
        """Return full texture raster capped to max_dim without giant intermediates."""
        max_dim = max(1, int(max_dim))
        precision = max(0.1, min(float(precision), 1.0))
        cache_key = (max_dim, round(precision, 3))
        if cache:
            cached = self._raster_by_max_dim.get(cache_key)
            if cached is not None:
                return cached

        px_w, px_h = self._get_bounded_raster_size(max_dim=max_dim, precision=precision)
        width, height, rgba = openglider.rs.svg_mod.render_svg_rgba(str(self.file_path), px_w, px_h)
        image = Image.frombytes("RGBA", (int(width), int(height)), bytes(rgba))
        if cache:
            self._raster_by_max_dim[cache_key] = image
        return image

    def _get_bounded_raster_size(self, max_dim: int, precision: float) -> tuple[int, int]:
        px_w = max(1, int(round(self.width * self.dpi / 72.0)))
        px_h = max(1, int(round(self.height * self.dpi / 72.0)))
        scale = min(1.0, max_dim / max(px_w, px_h))
        render_scale = min(scale, precision)
        render_dpi = max(10, int(math.floor(self.dpi * render_scale)))
        px_w = max(1, int(round(self.width * render_dpi / 72.0)))
        px_h = max(1, int(round(self.height * render_dpi / 72.0)))
        return px_w, px_h

    def sample_color(self, u: float, v: float) -> tuple[int, int, int]:
        image = self._get_raster()
        width, height = image.size

        u = min(max(u, 0.0), 1.0)
        v = min(max(v, 0.0), 1.0)

        px = min(width - 1, max(0, int(round(u * (width - 1)))))
        py = min(height - 1, max(0, int(round((1.0 - v) * (height - 1)))))
        color = image.getpixel((px, py))
        if isinstance(color, tuple) and len(color) >= 3:
            return (int(color[0]), int(color[1]), int(color[2]))
        return (int(color), int(color), int(color))

class UVMap:
    def __init__(self, glider: glider.ParametricGlider) -> None:
        self.glider = glider
        self.glider3d = self.glider.get_glider_3d()
        self.cell_x_values = self.glider.shape.rib_x_values

    def _get_length(self, x: Percentage, rib: Rib) -> float:
        ik_front = rib.profile_2d.get_ik(0)
        ik = rib.profile_2d.get_ik(x)

        length = rib.profile_2d.curve.get(ik_front, ik).get_length()

        if x.si < 0:
            length *= -1

        return length * rib.chord

    def _get_panel(self, cell_no: int, cell: Cell, panel: Panel) -> openglider.rs.vector.PolyLine2D:
        p1 = (self.cell_x_values[cell_no], self._get_length(panel.cut_back.x_left, cell.rib1))
        p2 = (self.cell_x_values[cell_no + 1], self._get_length(panel.cut_back.x_right, cell.rib2))
        p3 = (self.cell_x_values[cell_no + 1], self._get_length(panel.cut_front.x_right, cell.rib2))
        p4 = (self.cell_x_values[cell_no], self._get_length(panel.cut_front.x_left, cell.rib1))
        return openglider.rs.vector.PolyLine2D([p1, p2, p3, p4])

    def _collect_panels(
        self,
        include_mirror: bool = True,
    ) -> tuple[list[tuple[Panel, openglider.rs.vector.PolyLine2D]], list[tuple[Panel, openglider.rs.vector.PolyLine2D]]]:
        upper: list[tuple[Panel, openglider.rs.vector.PolyLine2D]] = []
        lower: list[tuple[Panel, openglider.rs.vector.PolyLine2D]] = []

        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel in cell.panels:
                panel_polygon = self._get_panel(cell_no, cell, panel)
                target = lower if panel.is_lower() else upper
                target.append((panel, panel_polygon))

                if include_mirror and (cell_no > 0 or not self.glider3d.has_center_cell):
                    target.append((panel, panel_polygon.mirror()))

        return upper, lower

    @staticmethod
    def _get_bbox(polylines: Iterable[openglider.rs.vector.PolyLine2D]) -> tuple[float, float, float, float]:
        points = [p for polyline in polylines for p in polyline]
        if not points:
            return (0.0, 1.0, 0.0, 1.0)

        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)
        return min_x, max_x, min_y, max_y

    def get_panels(
        self,
        mode: UVMapMode = "mirrored",
    ) -> tuple[list[tuple[Panel, openglider.rs.vector.PolyLine2D]], list[tuple[Panel, openglider.rs.vector.PolyLine2D]]]:
        upper, lower = self._collect_panels(include_mirror=True)

        if mode == "mirrored":
            return upper, lower

        upper_bbox = self._get_bbox([polyline for _, polyline in upper])
        lower_bbox = self._get_bbox([polyline for _, polyline in lower])
        gap = 0.05 * max(upper_bbox[3] - upper_bbox[2], lower_bbox[3] - lower_bbox[2], 1.0)
        offset_y = (lower_bbox[3] + gap) - upper_bbox[2]
        diff = openglider.rs.vector.Vector2D([0.0, offset_y])
        upper_shifted = [(panel, polyline.move(diff)) for panel, polyline in upper]
        return upper_shifted, lower

    def _get_actor_uv_bbox(self, uv_poly_map: dict[tuple[int, int], openglider.rs.vector.PolyLine2D]) -> tuple[float, float, float, float]:
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")

        has_points = False
        for (cell_no, _), poly in uv_poly_map.items():
            for p in poly:
                has_points = True
                min_x = min(min_x, p[0])
                max_x = max(max_x, p[0])
                min_y = min(min_y, p[1])
                max_y = max(max_y, p[1])

            if cell_no > 0 or not self.glider3d.has_center_cell:
                for p in poly.mirror():
                    has_points = True
                    min_x = min(min_x, p[0])
                    max_x = max(max_x, p[0])
                    min_y = min(min_y, p[1])
                    max_y = max(max_y, p[1])

        if not has_points:
            return (0.0, 1.0, 0.0, 1.0)

        return (min_x, max_x, min_y, max_y)

    def _get_panel_shape(
        self,
        cell_no: int,
        panel: Panel,
        shape: object | None = None,
    ) -> openglider.rs.vector.PolyLine2D:
        """Panel corners using ShapePlot's planform-side projection.

        This mirrors the logic in ShapePlot.draw_design:
        - lower side uses max(cut, 0)
        - upper side uses max(-cut, 0)

        Coordinates are in raw Shape units (metres), with y measured from LE
        toward TE (always non-negative before lower-side stacking offset).
        """
        if shape is None:
            shape = self.glider.shape.get_half_shape()

        if panel.is_lower():
            def normalize_x(val: float | Percentage) -> float:
                return max(float(val), 0.0)
        else:
            def normalize_x(val: float | Percentage) -> float:
                return max(float(-val), 0.0)

        p_fl = shape.get_point(cell_no, normalize_x(panel.cut_front.x_left))  # type: ignore[union-attr]
        p_bl = shape.get_point(cell_no, normalize_x(panel.cut_back.x_left))   # type: ignore[union-attr]
        p_br = shape.get_point(cell_no + 1, normalize_x(panel.cut_back.x_right))  # type: ignore[union-attr]
        p_fr = shape.get_point(cell_no + 1, normalize_x(panel.cut_front.x_right))  # type: ignore[union-attr]

        return openglider.rs.vector.PolyLine2D([
            (float(p_bl[0]), float(p_bl[1])),   # back_left
            (float(p_br[0]), float(p_br[1])),   # back_right
            (float(p_fr[0]), float(p_fr[1])),   # front_right
            (float(p_fl[0]), float(p_fl[1])),   # front_left
        ])

    def _stacked_params(
        self,
        half_shape: object | None = None,
    ) -> tuple[float, float, float, float]:
        """Return (max_upper_y, max_lower_y, upper_offset, y_min) in Shape units.

        All values use the same physical coordinate system as _get_panel_shape so
        that remap_uvs_stacked and the SVG layout are consistent.
        """
        if half_shape is None:
            half_shape = self.glider.shape.get_half_shape()
        upper_polys: list[openglider.rs.vector.PolyLine2D] = []
        lower_polys: list[openglider.rs.vector.PolyLine2D] = []
        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel in cell.panels:
                poly = self._get_panel_shape(cell_no, panel, half_shape)
                (lower_polys if panel.is_lower() else upper_polys).append(poly)

        upper_bbox = self._get_bbox(upper_polys) if upper_polys else (0.0, 0.0, 0.0, 0.0)
        lower_bbox = self._get_bbox(lower_polys) if lower_polys else (0.0, 0.0, 0.0, 0.0)
        max_upper_y = upper_bbox[3]
        max_lower_y = lower_bbox[3]
        size = max(max_upper_y, max_lower_y, 1e-3)
        gap = 0.05 * size
        upper_offset = (lower_bbox[3] + gap) - upper_bbox[2]
        y_min = min(upper_bbox[2] + upper_offset, lower_bbox[2])
        return max_upper_y, max_lower_y, upper_offset, y_min

    def _get_stacked_uv_polys(self) -> dict[tuple[int, int], openglider.rs.vector.PolyLine2D]:
        """Panel polygons for the stacked UV template.

        Lower panels stay at their physical shape coordinates. Upper panels are
        shifted upward by the computed gap so the exported SVG remains visually
        stacked instead of overlapping at the origin.
        """
        half_shape = self.glider.shape.get_half_shape()
        uv_poly_map: dict[tuple[int, int], openglider.rs.vector.PolyLine2D] = {}
        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel_idx, panel in enumerate(cell.panels):
                uv_poly_map[(cell_no, panel_idx)] = self._get_panel_shape(
                    cell_no, panel, half_shape
                )

        _, _, upper_offset, _ = self._stacked_params(half_shape)
        diff = openglider.rs.vector.Vector2D([0.0, upper_offset])
        for key in list(uv_poly_map.keys()):
            cn, pi = key
            if not self.glider3d.cells[cn].panels[pi].is_lower():
                uv_poly_map[key] = uv_poly_map[key].move(diff)
        return uv_poly_map

    def get_textured_panels_actor(
        self,
        texture: SVGTexture | str | Path,
        numribs: int = 3,
        mode: UVMapMode = "stacked",
        precision: float = 1.0,
        cache_texture: bool = True,
        draw_edges: bool = False,
        boundary_only: bool = False,
    ) -> openglider.rs.wgpu.MeshActor:
        texture_map = texture if isinstance(texture, SVGTexture) else SVGTexture(texture)
        panel_mesh = openglider.mesh.Mesh(name="textured_panels")

        if mode == "stacked":
            uv_poly_map = self._get_stacked_uv_polys()
        else:  # "mirrored" — arc-length based layout
            uv_poly_map = {
                (cell_no, panel_idx): self._get_panel(cell_no, cell, panel)
                for cell_no, cell in enumerate(self.glider3d.cells)
                for panel_idx, panel in enumerate(cell.panels)
            }

        # Use the same robust bilinear remap for both modes; only the polygon source differs.
        overall_bbox = self._get_actor_uv_bbox(uv_poly_map)

        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel_idx, panel in enumerate(cell.panels):
                mesh_temp = panel.get_mesh(cell, numribs=numribs)
                uv_poly = uv_poly_map[(cell_no, panel_idx)]
                pts = list(uv_poly)
                do_mirror = cell_no > 0 or not self.glider3d.has_center_cell
                mesh_for_mirror = mesh_temp.copy() if do_mirror else None

                mesh_temp.remap_uvs_bilinear(
                    (pts[0][0], pts[0][1]), (pts[1][0], pts[1][1]),
                    (pts[2][0], pts[2][1]), (pts[3][0], pts[3][1]),
                    overall_bbox,
                )
                panel_mesh += mesh_temp

                if do_mirror:
                    mirrored = mesh_for_mirror.mirror("y")
                    mpts = list(uv_poly.mirror())
                    mirrored.remap_uvs_bilinear(
                        (mpts[1][0], mpts[1][1]), (mpts[0][0], mpts[0][1]),
                        (mpts[3][0], mpts[3][1]), (mpts[2][0], mpts[2][1]),
                        overall_bbox,
                    )
                    panel_mesh += mirrored

        image = texture_map.get_raster_bounded(8192, precision=precision, cache=cache_texture)
        # WGPU mandates MAX_TEXTURE_DIMENSION_2D ≤ 8192 on all conformant devices.
        _MAX_TEX = 8192
        if image.width > _MAX_TEX or image.height > _MAX_TEX:
            scale = min(_MAX_TEX / image.width, _MAX_TEX / image.height)
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                Image.LANCZOS,
            )
        panel_mesh.set_texture_rgba(image.width, image.height, image.tobytes())
        return openglider.rs.wgpu.MeshActor(panel_mesh, draw_edges=draw_edges, boundary_only=boundary_only)

    def get_layout(self, mode: UVMapMode = "mirrored") -> Layout:
        if mode == "stacked":
            # Same two-shape layout as the 3D texture so the exported SVG template
            # is directly usable as a texture overlay.
            uv_poly_map = self._get_stacked_uv_polys()
            all_polys: list[openglider.rs.vector.PolyLine2D] = []
            for (cell_no, _), poly in uv_poly_map.items():
                all_polys.append(poly.close())
                if cell_no > 0 or not self.glider3d.has_center_cell:
                    all_polys.append(poly.mirror().close())
            points = all_polys
        else:
            upper, lower = self.get_panels(mode=mode)
            points = [panel_points.close() for _, panel_points in upper + lower]

        layout = Layout()
        layout.parts.append(PlotPart(marks=points))
        layout = layout.scale(100)
        return layout

