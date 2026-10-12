from __future__ import annotations
import collections
import logging
from typing import Any, TypeAlias

from openglider.utils.cache import cached_function
import openglider.rs
from openglider.rs import drawing

from openglider.glider.cell.cell import Cell
from openglider.glider.cell.panel.panel import Panel
from openglider.glider.glider import Glider
from openglider.utils.config import Config

from openglider.plots.glider.cell import CellPlotMaker as DefaultCellPlotMaker
from openglider.plots.glider.ribs import RibPlot, SingleSkinRibPlot
from openglider.plots.glider.minirib import MiniRibPlot
from openglider.plots.config import PatternConfig
from openglider.plots.usage_stats import MaterialUsage
from openglider.vector.mapping import Quad
from openglider.vector.unit import Length

logger = logging.getLogger(__name__)

PlotPartDict = collections.OrderedDict[Cell, list[drawing.Part]]
PanelMarkLayers = dict[str, list[openglider.rs.vector.PolyLine2D]]
PanelMarks = dict[Panel, list[openglider.rs.vector.PolyLine2D]]

class PlotMaker:
    glider_3d: Glider
    config: PatternConfig
    
    panels: drawing.Layout
    ribs: list[drawing.Part]
    dribs: PlotPartDict
    straps: collections.OrderedDict[Cell, tuple[list[drawing.Part], list[drawing.Part]]]
    rigidfoils: list[drawing.Part]
    miniribs: PlotPartDict
    seam_allowance: Length

    DefaultConf: TypeAlias = PatternConfig
    CellPlotMaker: TypeAlias = DefaultCellPlotMaker
    SingleSkinRibPlot = SingleSkinRibPlot
    RibPlot = RibPlot
    MibiRibPlot = MiniRibPlot
    
    def __init__(self, glider_3d: Glider, config: Config | None=None):
        self.glider_3d = glider_3d
        self.config = self.DefaultConf(config)
        self.panels = drawing.Layout()
        self.ribs = []

        self.dribs = collections.OrderedDict()
        self.straps = collections.OrderedDict()
        self.rigidfoils = []
        self.miniribs = collections.OrderedDict()
        self.extra_parts: list[drawing.Part] = []
        self._cellplotmakers: dict[Cell, DefaultCellPlotMaker] = dict()

        self.weight: dict[str, MaterialUsage] = {}

    def __json__(self) -> dict[str, Any]:
        return {
            "glider3d": self.glider_3d,
            "config": self.config,
            "panels": self.panels,
            "extra_parts": self.extra_parts,
            #"dribs": self.dribs,
            "ribs": self.ribs,
            "miniribs": self.miniribs
        }

    @classmethod
    def __from_json__(cls, dct: dict[str, Any]) -> PlotMaker:
        ding = cls(dct["glider3d"], dct["config"])
        ding.panels = dct["panels"]
        ding.ribs = dct["ribs"]
        ding.extra_parts = dct.get("extra_parts", [])
        # ding.dribs = dct["dribs"]

        return ding

    def _get_cellplotmaker(self, cell: Cell) -> CellPlotMaker:
        if cell not in self._cellplotmakers:
            self._cellplotmakers[cell] = self.CellPlotMaker(cell, self.config)
            self._cellplotmakers[cell].prepare()

        return self._cellplotmakers[cell]

    @staticmethod
    def _layout_bbox(layout: drawing.Layout) -> tuple[float, float, float, float]:
        return layout.bbox() or (0.0, 1.0, 0.0, 1.0)

    @classmethod
    def _layout_width_height(cls, layout: drawing.Layout) -> tuple[float, float]:
        min_x, max_x, min_y, max_y = cls._layout_bbox(layout)
        return max(max_x - min_x, 0.0), max(max_y - min_y, 0.0)

    @staticmethod
    def _group_by_material(layout: drawing.Layout) -> dict[str, drawing.Layout]:
        grouped: dict[str, drawing.Layout] = {}
        for part in layout.parts:
            material = part.material_code or "default"
            grouped.setdefault(material, drawing.Layout())
            grouped[material].add_part(part.copy())
        return grouped

    @classmethod
    def _build_panel_export_branches(
        cls,
        panels: drawing.Layout,
    ) -> tuple[drawing.Layout, drawing.Layout | None]:
        # main area -> remove texture_left layer
        panels_main = panels.copy()
        panels_main.pop_layer("texture_left")

        # mirrored side -> remove texture_right layer, mirror and filter parts with texture_left content
        panels_left = panels.copy()
        panels_left.pop_layer("texture_right")
        panels_left_parts: list[drawing.Part] = []

        for part in panels_left.parts:
            texture_left_layer = part.layers.get("texture_left")
            if texture_left_layer is not None and texture_left_layer.has_content():
                panels_left_parts.append(part)

        panels_left.parts = panels_left_parts

        if not panels_left.parts:
            return panels_main, None
        
        panels_left = panels_left.mirror("y")
        main_bbox = cls._layout_bbox(panels_main)
        left_bbox = cls._layout_bbox(panels_left)

        main_border = cls._border_part(panels)
        if main_border is not None:
            dy = main_bbox[3] - main_bbox[2]
            panels_left.add_part(main_border.move(openglider.rs.vector.Vector2D([0.0, -dy])))

        y = main_bbox[3] - left_bbox[2]
        panels_left = panels_left.move(openglider.rs.vector.Vector2D([0.0, y]))        

        return panels_main, panels_left

    @classmethod
    def _border_part(
        cls,
        layout: drawing.Layout,
        border: float = 0.1,
        x_bounds: tuple[float, float] | None = None,
    ) -> drawing.Part | None:
        bbox = layout.bbox()
        if bbox is None:
            return None

        min_x, max_x, min_y, max_y = bbox
        if x_bounds is not None:
            min_x, max_x = x_bounds
        poly = openglider.rs.vector.PolyLine2D([
            openglider.rs.vector.Vector2D([min_x - border, min_y - border]),
            openglider.rs.vector.Vector2D([max_x + border, min_y - border]),
            openglider.rs.vector.Vector2D([max_x + border, max_y + border]),
            openglider.rs.vector.Vector2D([min_x - border, max_y + border]),
            openglider.rs.vector.Vector2D([min_x - border, min_y - border]),
        ])

        part = drawing.Part()
        with part.layer("border") as layer:
            layer.style.stroke = "black"
            layer.style.stroke_width = 0.25
            layer.add_line(poly)
        return part

    @classmethod
    def _add_label(cls, layout: drawing.Layout, label: str) -> None:
        bbox = layout.bbox()
        if bbox is None:
            return

        min_x, _max_x, min_y, _max_y = bbox
        p1 = openglider.rs.vector.Vector2D([min_x, min_y])
        p2 = openglider.rs.vector.Vector2D([min_x + 1.0, min_y])
        text = drawing.Text(label, p1, p2, size=0.1, valign=-1.0, align=-1.0)

        part = drawing.Part()
        with part.layer("text") as layer:
            layer.style.stroke = "black"
            layer.style.stroke_width = 0.25
            layer.add_text(text)
        layout.add_part(part)

    @staticmethod
    def _map_point_from_quad(
        point: tuple[float, float],
        src_quad: Quad,
        dst_quad: Quad,
    ) -> tuple[float, float] | None:
        try:
            l, m = src_quad.to_local(openglider.rs.vector.Vector2D([point[0], point[1]]))
            mapped = dst_quad.to_global(l, m)
        except (ValueError, ZeroDivisionError, OverflowError):
            return None

        return float(mapped[0]), float(mapped[1])

    @cached_function("glider_3d")
    def _get_texture_panel_marks(self) -> list[dict[Panel, PanelMarkLayers]]:
        texture_obj = self.glider_3d.texture
        result: list[dict[Panel, PanelMarkLayers]] = [dict() for _ in self.glider_3d.cells]
        if texture_obj is None:
            return result

        texture_bbox = texture_obj.uv_map._get_texture_bbox()
        texture_vectors = texture_obj.texture.get_vectors(
            (
                (texture_bbox[0], texture_bbox[2]),
                (texture_bbox[1], texture_bbox[3]),
            )
        )
        if not texture_vectors:
            return result

        uv_map = texture_obj.uv_map

        def snap_to_panel_boundary(point: tuple[float, float], panel: Panel) -> tuple[float, float]:
            x, y = point
            y = min(max(y, 0.0), 1.0)

            front = float(panel.cut_front.x_left) + y * (float(panel.cut_front.x_right) - float(panel.cut_front.x_left))
            back = float(panel.cut_back.x_left) + y * (float(panel.cut_back.x_right) - float(panel.cut_back.x_left))

            distances = (
                (abs(y - 0.0), "span_left"),
                (abs(y - 1.0), "span_right"),
                (abs(x - front), "front"),
                (abs(x - back), "back"),
            )

            min_dist, edge = min(distances, key=lambda item: item[0])
            if min_dist > 5e-3:
                return x, y

            if edge == "span_left":
                return x, 0.0
            if edge == "span_right":
                return x, 1.0
            if edge == "front":
                return front, y

            return back, y

        for cell_no, cell in enumerate(self.glider_3d.cells):
            pm = self._get_cellplotmaker(cell)
            for panel in cell.panels:
                panel_poly = uv_map.get_panel_polygon(cell_no, panel)
                if len(panel_poly) != 4:
                    continue

                mirror_panel_marks = (not self.glider_3d.has_center_cell) or cell_no > 0

                def project_texture_marks(
                    source_panel_poly: openglider.rs.vector.PolyLine2D,
                    source_texture_vectors: list[openglider.rs.vector.PolyLine2D],
                ) -> list[openglider.rs.vector.PolyLine2D]:
                    src_quad = Quad(*source_panel_poly.nodes)
                    dst_quad = Quad(
                        openglider.rs.vector.Vector2D([float(panel.cut_back.x_left), 0.0]),
                        openglider.rs.vector.Vector2D([float(panel.cut_back.x_right), 1.0]),
                        openglider.rs.vector.Vector2D([float(panel.cut_front.x_right), 1.0]),
                        openglider.rs.vector.Vector2D([float(panel.cut_front.x_left), 0.0]),
                    )

                    projected_lines: list[openglider.rs.vector.PolyLine2D] = []
                    for texture_line in source_texture_vectors:
                        clipped_segments = texture_line.clip(source_panel_poly)
                        if not clipped_segments:
                            continue

                        for clipped in clipped_segments:
                            mapped_points: list[tuple[float, float]] = []
                            for p in clipped:
                                mapped = self._map_point_from_quad((float(p[0]), float(p[1])), src_quad, dst_quad)
                                if mapped is not None:
                                    mapped_points.append(mapped)

                            if len(mapped_points) < 2:
                                continue

                            mapped_points[0] = snap_to_panel_boundary(mapped_points[0], panel)
                            mapped_points[-1] = snap_to_panel_boundary(mapped_points[-1], panel)

                            projected = pm.panel_plots[panel].get_curve(openglider.rs.vector.PolyLine2D(mapped_points))
                            if projected is not None and len(projected) >= 2:
                                projected_lines.append(projected)

                    return projected_lines

                panel_layers: PanelMarkLayers = {}
                projected_lines = project_texture_marks(
                    panel_poly,
                    texture_vectors,
                )
                if projected_lines:
                    panel_layers["texture_right"] = projected_lines

                if mirror_panel_marks:
                    mirrored_lines = project_texture_marks(
                        panel_poly.mirror(),
                        texture_vectors,
                    )
                    if mirrored_lines:
                        panel_layers["texture_left"] = mirrored_lines

                if panel_layers:
                    result[cell_no][panel] = panel_layers

        return result

    def _get_cell_panel_marks(
        self,
        cell_no: int,
        extra_marks: PanelMarks | None = None,
    ) -> dict[Panel, PanelMarkLayers]:
        merged_marks: dict[Panel, PanelMarkLayers] = {}
        texture_marks = self._get_texture_panel_marks()

        if cell_no < len(texture_marks) and texture_marks[cell_no]:
            merged_marks.update({
                panel: {layer_name: marks[:] for layer_name, marks in panel_layers.items()}
                for panel, panel_layers in texture_marks[cell_no].items()
            })

        if extra_marks:
            for panel, marks in extra_marks.items():
                merged_marks.setdefault(panel, {})
                merged_marks[panel].setdefault("marks", [])
                merged_marks[panel]["marks"] += marks

        return merged_marks

    def get_panels_for_cell(
        self,
        cell_no: int,
        extra_marks: PanelMarks | None = None,
    ) -> drawing.Layout:
        cell = self.glider_3d.cells[cell_no]
        pm = self._get_cellplotmaker(cell)
        merged_marks = self._get_cell_panel_marks(cell_no, extra_marks=extra_marks)
        panel_marks = merged_marks if merged_marks else None

        lower = pm.get_panels_lower(extra_marks=panel_marks)
        upper = pm.get_panels_upper(extra_marks=panel_marks)
        layout_lower = drawing.Layout.stack_column(
            [drawing.Layout([part]) for part in lower],
            self.config.patterns_align_dist_y,
        )
        layout_upper = drawing.Layout.stack_column(
            [drawing.Layout([part]) for part in upper],
            self.config.patterns_align_dist_y,
        )

        if self.config.layout_seperate_panels:
            layout_lower = layout_lower.rotate(180, radians=False, center=None)
            return drawing.Layout.stack_row([layout_lower, layout_upper], 2 * self.config.patterns_align_dist_x)

        return drawing.Layout.stack_column(
            [
                drawing.Layout.stack_row(
                    [drawing.Layout([part]) for part in row],
                    self.config.patterns_align_dist_x,
                )
                for row in [upper, lower]
                if row
            ],
            self.config.patterns_align_dist_y,
            center_x=False,
        )

    def get_panels(self, extra_marks: list[dict[Panel, list[openglider.rs.vector.PolyLine2D]]] | None = None) -> drawing.Layout:
        self.panels = drawing.Layout()
        panels_upper: list[drawing.Layout] = []
        panels_lower: list[drawing.Layout] = []

        weight = MaterialUsage()

        for cell_no, cell in enumerate(self.glider_3d.cells):
            logger.info(f"Plotting Cell: {cell_no}")
            pm = self._get_cellplotmaker(cell)
            merged_marks = self._get_cell_panel_marks(
                cell_no,
                extra_marks=extra_marks[cell_no] if extra_marks is not None and cell_no < len(extra_marks) else None,
            )

            _extra_marks = merged_marks if merged_marks else None
            lower = pm.get_panels_lower(extra_marks=_extra_marks)
            upper = pm.get_panels_upper(extra_marks=_extra_marks)
            panels_lower.append(drawing.Layout.stack_column([drawing.Layout([part]) for part in lower], self.config.patterns_align_dist_y))
            panels_upper.append(drawing.Layout.stack_column([drawing.Layout([part]) for part in upper], self.config.patterns_align_dist_y))

            panel_weight = pm.consumption
            if cell_no > 0 or not self.glider_3d.has_center_cell:
                panel_weight *= 2

            weight += panel_weight


        if self.config.layout_seperate_panels:
            layout_lower = drawing.Layout.stack_row(panels_lower, self.config.patterns_align_dist_x)
            layout_lower = layout_lower.rotate(180, radians=False, center=None)
            layout_upper = drawing.Layout.stack_row(panels_upper, self.config.patterns_align_dist_x)

            self.panels = drawing.Layout.stack_row([layout_lower, layout_upper], 2*self.config.patterns_align_dist_x)

        else:
            self.panels = drawing.Layout.stack_column(
                [drawing.Layout.stack_row(row, self.config.patterns_align_dist_x) for row in [panels_upper, panels_lower] if row],
                self.config.patterns_align_dist_y,
                center_x=False,
            )

        self.weight["panels"] = weight

        return self.panels

    def get_ribs(self, rotate: bool=False) -> None:
        from openglider.glider.rib.singleskin import SingleSkinRib

        weight = MaterialUsage()
        self.ribs = []
        for rib_no, rib in enumerate(self.glider_3d.ribs):
            if rib_no == 0 and self.glider_3d.has_center_cell:
                continue

            if rib.profile_2d.thickness < 1e-5:
                continue
            
            logger.info(f"plotting rib {rib.name}")
            rib_plot: SingleSkinRibPlot | RibPlot
            if isinstance(rib, SingleSkinRib):
                rib_plot = self.SingleSkinRibPlot(rib, self.config)
            else:
                rib_plot = self.RibPlot(rib, self.config)

            rib_plot.flatten(self.glider_3d)

            for hole in rib.holes:
                self.extra_parts += hole.get_parts(rib)

            rib_weight = rib_plot.weight
            if rib_no == 0:
                if self.glider_3d.has_center_cell:
                    rib_weight = MaterialUsage()
            else:
                rib_weight *= 2
            
            weight += rib_weight

            if rotate:
                rib_plot.plotpart = rib_plot.plotpart.rotate(-90, radians=False, center=None)
            self.ribs.append(rib_plot.plotpart)
        
        self.weight["ribs"] = weight

    def get_dribs(self) -> PlotPartDict:
        self.dribs.clear()
        weight = MaterialUsage()

        for cell in self.glider_3d.cells:
            logger.info(f"plotting diagonals for cell {cell.name}")
            # missing attachmentpoints []
            pm = self._get_cellplotmaker(cell)
            dribs = pm.get_dribs()
            self.dribs[cell] = dribs[:]

            weight += pm.consumption_drib *2


        self.weight["dribs"] = weight

        return self.dribs

    def get_straps(self) -> collections.OrderedDict[Cell, tuple[list[drawing.Part], list[drawing.Part]]]:
        self.straps.clear()
        weight = MaterialUsage()

        for cell in self.glider_3d.cells:
            logger.info(f"plotting straps for cell {cell.name}")
            # missing attachmentpoints []
            pm = self._get_cellplotmaker(cell)
            upper, lower = pm.get_straps()
            self.straps[cell] = (
                upper,
                lower
            )
            weight += pm.consumption_straps *2

        self.weight["straps"] = weight

        return self.straps

    def get_rigidfoils(self) -> tuple[list[drawing.Part], list[dict[Panel, list[openglider.rs.vector.PolyLine2D]]]]:
        self.rigidfoils.clear()
        extra_marks: list[dict[Panel, list[openglider.rs.vector.PolyLine2D]]] = []

        for cell in self.glider_3d.cells:
            logger.info(f"plotting rigidfoils for cell: {cell.name}")
            rigidfoils, _extra_marks = self._get_cellplotmaker(cell).get_rigidfoils()
            self.rigidfoils += rigidfoils
            extra_marks.append(_extra_marks)
        
        return self.rigidfoils, extra_marks
    
    def get_miniribs(self) -> PlotPartDict:
        self.miniribs.clear()
        weight = MaterialUsage()

        for cell in self.glider_3d.cells:
            logger.info(f"plotting miniribs for cell: {cell.name}")
            pm = self._get_cellplotmaker(cell)
            miniribs = pm.get_miniribs()
            self.miniribs[cell] = miniribs
            weight += pm.consumption_mribs *2

        self.weight["mribs"] = weight

        return self.miniribs

    def get_all_grouped(self) -> drawing.Layout:
        # create x-raster
        self.ribs = [rib.rotate(-90, radians=False, center=None) for rib in self.ribs]

        panels = self.panels
        panels_main, panels_left = self._build_panel_export_branches(panels)
        ribs = drawing.Layout.stack_row([drawing.Layout([rib]) for rib in self.ribs], self.config.patterns_align_dist_x)

        def stack_grid(dct: PlotPartDict) -> drawing.Layout:
            layout_lst = [
                drawing.Layout.stack_column([drawing.Layout([part]) for part in part_list], self.config.patterns_align_dist_y)
                for part_list in dct.values()
            ]
            return drawing.Layout.stack_row(layout_lst, self.config.patterns_align_dist_x)

        dribs = stack_grid(self.dribs)
        straps_upper = drawing.Layout.stack_row([
            drawing.Layout.stack_column([drawing.Layout([part]) for part in c[0]], self.config.patterns_align_dist_y)
            for c in self.straps.values()
        ], distance=self.config.patterns_align_dist_x)
        straps_lower = drawing.Layout.stack_row([
            drawing.Layout.stack_column([drawing.Layout([part]) for part in c[1][::-1]], self.config.patterns_align_dist_y)
            for c in list(self.straps.values())[::-1]
        ], distance=self.config.patterns_align_dist_x)
        straps = straps_upper.append_left(straps_lower, distance=self.config.patterns_align_dist_x)
        rigidfoils = drawing.Layout.stack_row([drawing.Layout([part]) for part in self.rigidfoils], self.config.patterns_align_dist_x)
        miniribs = stack_grid(self.miniribs)
        panels_bbox = panels_main.bbox()
        panels_x_bounds = None if panels_bbox is None else (panels_bbox[0], panels_bbox[1])

        def group(layout: drawing.Layout, prefix: str) -> list[drawing.Layout]:
            grouped = self._group_by_material(layout)
            results: list[drawing.Layout] = []
            for material_name, material_layout in grouped.items():
                border = self._border_part(
                    material_layout,
                    x_bounds=panels_x_bounds if prefix == "panels" else None,
                )
                if border is not None:
                    material_layout.add_part(border)
                self._add_label(material_layout, f"{prefix}_{material_name}")
                results.append(material_layout)
            return results

        panels_grouped = group(panels_main.copy(), "panels")
        ribs_grouped = group(ribs, "ribs")
        dribs_grouped = group(dribs, "dribs")
        straps_grouped = group(straps, "straps")
        miniribs_grouped = group(miniribs, "miniribs")

        self._add_label(panels_main, "panels_all")

        all_layouts = [panels_main]
        if panels_left is not None:
            all_layouts.append(panels_left)
        all_layouts += panels_grouped
        all_layouts += ribs_grouped
        all_layouts += dribs_grouped
        all_layouts += straps_grouped
        all_layouts += miniribs_grouped

        if len(rigidfoils.parts):
            border = self._border_part(rigidfoils)
            if border is not None:
                rigidfoils.add_part(border)
            self._add_label(rigidfoils, "rigidfoils")
            all_layouts.append(rigidfoils)

        if len(self.extra_parts):
            extra_parts = drawing.Layout.stack_row([drawing.Layout([part]) for part in self.extra_parts], self.config.patterns_align_dist_x)
            all_layouts += group(extra_parts, "extra_parts")

        return drawing.Layout.stack_column(all_layouts, 0.1, center_x=True)

    def unwrap(self) -> PlotMaker:
        _, extra_marks = self.get_rigidfoils()
        self.get_panels(extra_marks=extra_marks)
        self.get_ribs()
        self.get_dribs()
        self.get_straps()
        self.get_miniribs()
        return self
