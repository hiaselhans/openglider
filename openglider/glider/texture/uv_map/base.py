from __future__ import annotations

from typing import TYPE_CHECKING

import openglider.rs
from openglider.vector.drawing import Layout, PlotPart


from PIL import Image


from collections.abc import Iterable
from pathlib import Path


if TYPE_CHECKING:
    from openglider.glider.cell.cell import Cell
    from openglider.glider.cell.panel import Panel
    from openglider.glider.glider import Glider
    from openglider.glider.shape import ShapeBase
    from openglider.glider.texture.texture import SVGTexture


class _UVMapBase:
    """Shared UV mapping behavior for mirrored and stacked map variants."""

    def __init__(self, shape: ShapeBase, glider: Glider) -> None:
        self._shape = shape
        self.glider3d = glider
        self.cell_x_values = shape.rib_x_values
        self._has_center_cell = bool(self.glider3d.has_center_cell)
        self._texture_bbox_cache: tuple[float, float, float, float] | None = None
        self._panel_index_by_id: dict[int, tuple[int, int]] = {}
        self._uv_panel_mesh_cache: dict[int, openglider.rs.mesh.Mesh] = {}
        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel_idx, panel in enumerate(cell.panels):
                self._panel_index_by_id[id(panel)] = (cell_no, panel_idx)

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

    def _can_mirror(self, cell_no: int) -> bool:
        return cell_no > 0 or not self._has_center_cell

    @staticmethod
    def _clamp01(value: float) -> float:
        return min(max(float(value), 0.0), 1.0)

    @staticmethod
    def _clamp11(value: float) -> float:
        return min(max(float(value), -1.0), 1.0)

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + t * (b - a)

    def _iter_panels(self) -> Iterable[tuple[int, int, Cell, Panel]]:
        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel_idx, panel in enumerate(cell.panels):
                yield cell_no, panel_idx, cell, panel

    def _get_texture_bbox(self) -> tuple[float, float, float, float]:
        if self._texture_bbox_cache is None:
            outlines = []
            for cell_no, panel_idx, cell, panel in self._iter_panels():
                del panel_idx, cell
                outline = self.get_panel_polygon(cell_no, panel)
                outlines.append(outline)
            outline_bbox = self._get_bbox(outlines)

            xlim = max(-outline_bbox[0], outline_bbox[1])
            self._texture_bbox_cache = (-xlim, xlim, outline_bbox[2], outline_bbox[3])

        return self._texture_bbox_cache

    def _normalize_texture_point(self, x: float, y: float) -> tuple[float, float]:
        min_x, max_x, min_y, max_y = self._get_texture_bbox()
        width = max(max_x - min_x, 1e-9)
        height = max(max_y - min_y, 1e-9)
        u = (x - min_x) / width
        v = 1.0 - ((y - min_y) / height)
        return (u, v)

    def _resolve_panel_reference(self, panel: Panel) -> tuple[int, int]:
        """Resolve a panel instance to (cell_no, panel_idx)."""
        cached = self._panel_index_by_id.get(id(panel))
        if cached is not None:
            return cached

        candidate_cells: list[int] = []

        if hasattr(panel, "cell_no"):
            try:
                raw_cell_no = int(getattr(panel, "cell_no"))
                if 0 <= raw_cell_no < len(self.glider3d.cells):
                    candidate_cells.append(raw_cell_no)
                elif 1 <= raw_cell_no <= len(self.glider3d.cells):
                    candidate_cells.append(raw_cell_no - 1)
            except (TypeError, ValueError):
                pass

        if candidate_cells:
            for cell_no in candidate_cells:
                for panel_idx, candidate in enumerate(self.glider3d.cells[cell_no].panels):
                    if candidate is panel or candidate == panel:
                        return cell_no, panel_idx

        # Fallback: global search by identity/equality.
        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel_idx, candidate in enumerate(cell.panels):
                if candidate is panel or candidate == panel:
                    return cell_no, panel_idx

        # Last resort: search by side + name when present.
        panel_name = getattr(panel, "name", None)
        if panel_name:
            for cell_no, cell in enumerate(self.glider3d.cells):
                for panel_idx, candidate in enumerate(cell.panels):
                    if getattr(candidate, "name", None) == panel_name and candidate.is_lower() == panel.is_lower():
                        return cell_no, panel_idx

        raise ValueError("could not resolve panel reference to glider cell/panel index")

    def _transform_panel_local_coordinates_resolved(
        self,
        cell_no: int,
        panel: Panel,
        x: float,
        y: float,
        mirrored: bool = False,
    ) -> tuple[float, float]:
        x_local = self._clamp01(x)
        y_local = self._clamp11(y)
        is_upper = not panel.is_lower()
        tx, ty = self._texture_point_from_panel_local(
            cell_no=cell_no,
            is_upper=is_upper,
            x=x_local,
            y=y_local,
            mirrored=mirrored,
        )
        return self._normalize_texture_point(tx, ty)

    def get_textured_panels_actor(
        self,
        texture: SVGTexture,
        numribs: int = 3,
        precision: float = 1.0,
        cache_texture: bool = True,
        draw_edges: bool = False,
        boundary_only: bool = False,
    ) -> openglider.rs.wgpu.MeshActor:
        """Build a textured panel mesh actor with UVs mapped by this mode."""
        panel_mesh = self.get_textured_panels_mesh(texture, numribs=numribs, precision=precision, cache_texture=cache_texture)
        return openglider.rs.wgpu.MeshActor(panel_mesh, draw_edges=draw_edges, boundary_only=boundary_only)

    def get_textured_panels_mesh(
        self,
        texture: SVGTexture,
        numribs: int = 3,
        precision: float = 1.0,
        cache_texture: bool = True,
    ) -> openglider.rs.mesh.Mesh:
        """Build a textured panel mesh with UVs mapped by this mode."""
        panel_mesh_cached = self._uv_panel_mesh_cache.get(numribs)
        if panel_mesh_cached is None:
            panel_mesh = self._build_uv_panel_mesh(numribs)
            self._uv_panel_mesh_cache[numribs] = panel_mesh.copy()
        else:
            panel_mesh = panel_mesh_cached.copy()

        image = texture.get_raster_bounded(8192, precision=precision, cache=cache_texture)
        # WGPU mandates MAX_TEXTURE_DIMENSION_2D <= 8192 on all conformant devices.
        _MAX_TEX = 8192
        if image.width > _MAX_TEX or image.height > _MAX_TEX:
            scale = min(_MAX_TEX / image.width, _MAX_TEX / image.height)
            image = image.resize(
                (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
                Image.Resampling.LANCZOS,
            )
        panel_mesh.set_texture_rgba(image.width, image.height, image.tobytes())
        return panel_mesh

    def _build_uv_panel_mesh(self, numribs: int) -> openglider.rs.mesh.Mesh:
        """Generate panel mesh with per-vertex UVs for this mapping mode."""
        panel_mesh = openglider.rs.mesh.Mesh(name="textured_panels")
        map_local = self._transform_panel_local_coordinates_resolved

        for cell_no, _panel_idx, cell, panel in self._iter_panels():
            mesh_temp = panel.get_mesh(cell, numribs=numribs)
            uv_original = mesh_temp.get_uv_coords()
            mesh_temp.set_all_objects_textured(True)

            if uv_original is not None:
                uv_mapped = [
                    map_local(cell_no=cell_no, panel=panel, x=u, y=v, mirrored=False)
                    for u, v in uv_original
                ]
                mesh_temp.set_uv_coords(uv_mapped)

            panel_mesh += mesh_temp

            if self._can_mirror(cell_no):
                mesh_mirrored = mesh_temp.copy().mirror("y")
                mesh_mirrored.set_all_objects_textured(True)
                # Keep panel-local UV inputs stable; mirrored mesh mutates UV y values.
                uv_source_m = uv_original if uv_original is not None else mesh_mirrored.get_uv_coords()
                if uv_source_m is not None:
                    uv_mapped_m = [
                        map_local(cell_no=cell_no, panel=panel, x=u, y=v, mirrored=True)
                        for u, v in uv_source_m
                    ]
                    mesh_mirrored.set_uv_coords(uv_mapped_m)
                panel_mesh += mesh_mirrored

        return panel_mesh

    def get_layout(self) -> Layout:
        """Return a 2D layout of mapped panel outlines, including mirrored halves."""
        points: list[openglider.rs.vector.PolyLine2D] = []
        for cell_no, panel_idx, cell, panel in self._iter_panels():
            del panel_idx, cell
            poly = self.get_panel_polygon(cell_no, panel)
            points.append(poly.close())
            if self._can_mirror(cell_no):
                points.append(poly.mirror().close())

        layout = Layout()
        layout.parts.append(PlotPart(marks=points))
        return layout

    def _texture_point_from_panel_local(
        self,
        cell_no: int,
        is_upper: bool,
        x: float,
        y: float,
        mirrored: bool,
    ) -> tuple[float, float]:
        raise NotImplementedError

    def get_panel_polygon(
        self,
        cell_no: int,
        panel: Panel,
    ) -> openglider.rs.vector.PolyLine2D:
        """Return panel polygon in texture coordinates from canonical panel corners."""
        is_upper = not panel.is_lower()

        corners = [
            (0.0, panel.cut_back.x_left),
            (1.0, panel.cut_back.x_right),
            (1.0, panel.cut_front.x_right),
            (0.0, panel.cut_front.x_left),
        ]
        points = [
            self._texture_point_from_panel_local(
                cell_no=cell_no,
                is_upper=is_upper,
                x=x_local,
                y=y_local.si,
                mirrored=False,
            )
            for x_local, y_local in corners
        ]
        return openglider.rs.vector.PolyLine2D(points)