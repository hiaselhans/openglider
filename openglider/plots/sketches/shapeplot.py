from __future__ import annotations

import logging
import math
import io
import re
from os import PathLike
from collections.abc import Iterator

import openglider.rs
import numpy as np
import svglib.svglib
from reportlab.graphics import renderPDF
from openglider.glider.shape import Shape
from openglider.lines.line import Line
from openglider.lines.node import Node
import openglider.plots.marks as marks
from openglider.glider import GliderProject
from openglider.glider.cell.panel import Panel, PanelCut
from openglider.rs import drawing as rs_drawing
from openglider.utils.dataclass import dataclass
from openglider.vector.unit import Percentage

logger = logging.getLogger(__name__)


@dataclass
class ShapePlotConfig:
    design_lower: bool = False
    design_upper: bool = False
    baseline: bool = False
    grid: bool = False
    attachment_points: bool = False
    lines: bool = False
    cells: bool = True
    cell_names: bool = False
    rib_names: bool = False
    straps: bool = False
    diagonals: bool = False

    apply_zrot: bool = False
    scale_area: float | None = None
    scale_span: float | None = None

    def view_layers(self) -> dict[str, bool]:
        layers = {}
        for attribute in self.__annotations__:
            if not attribute.startswith("scale") and attribute != "apply_zrot":
                layers[attribute] = getattr(self, attribute)
            
        return layers
    
    def copy(self) -> ShapePlotConfig:
        new = ShapePlotConfig()
        for attribute in self.__annotations__:
            setattr(new, attribute, getattr(self, attribute))

        return new
    
    def __add__(self, other: ShapePlotConfig) -> ShapePlotConfig:
        new = ShapePlotConfig()

        for attribute in self.__annotations__:
            if not attribute.startswith("scale"):
                setattr(new, attribute, getattr(self, attribute) or getattr(other, attribute))
            else:
                setattr(new, attribute, getattr(self, attribute))

        return new
    


class ShapePlot:
    project: GliderProject
    attachment_point_mark = marks.Cross(name="attachment_point", rotation=np.pi/4)
    a4_width_mm = 297.0
    attachment_text_size_mm = 1.0
    line_text_size_mm = 1.0
    attachment_text_offset_mm = 1.0

    config: ShapePlotConfig | None = None

    shapes: tuple[Shape, Shape] | None = None
    shapes_rot: tuple[Shape, Shape] | None = None

    def __init__(self, project: GliderProject, drawing: rs_drawing.Layout | None=None):
        super().__init__()
        self.project = project
        self.glider_2d = project.glider
        self.glider_3d = project.get_glider_3d()
        self.drawing = drawing or rs_drawing.Layout()

        self.reference_area = self.glider_2d.shape.area
        self.reference_span = self.glider_2d.shape.span

    def _new_part(self, material_code: str = "", name: str | None = None) -> rs_drawing.Part:
        return rs_drawing.Part(name=name, material_code=material_code)

    def _a4_span_scale(self) -> float:
        if self.reference_span <= 0:
            return 1.0
        return self.a4_width_mm / self.reference_span

    def _absolute_size_from_a4_mm(self, size_mm: float) -> float:
        scale = self._a4_span_scale()
        if scale <= 0:
            return size_mm
        return size_mm / scale

    def _scaled_a4_layout(self) -> rs_drawing.Layout:
        layout = self.drawing.copy()
        bbox = layout.bbox()
        if bbox is None:
            return layout

        min_x, max_x, min_y, max_y = bbox
        width = max(max_x - min_x, max_y - min_y)
        height = min(max_x - min_x, max_y - min_y)
        if width <= 0 or height <= 0:
            return layout

        width_a4, height_a4 = 297, 210
        factor = float(min(width_a4 / width, height_a4 / height))
        return layout.scale(factor)

    @staticmethod
    def _material_fill_color(material_code: str) -> str | None:
        match = re.search(r"#([0-9A-Fa-f]{3,8})", material_code)
        if match:
            return f"#{match.group(1)}"
        return None

    def _export_svg_to_pdf(self, path: PathLike, layout: rs_drawing.Layout) -> None:
        svg_data = layout.to_svg_string(0.0).encode("utf-8")
        with io.BytesIO(svg_data) as buffer:
            report = svglib.svglib.svg2rlg(buffer)
            renderPDF.drawToFile(report, str(path))

    def _get_shapes(self, config: ShapePlotConfig | None = None, force: bool=False) -> tuple[Shape, Shape]:
        if config is None:
            if self.config is not None:
                config = self.config
            else:
                config = ShapePlotConfig()

        def get_shape(rot: bool) -> tuple[Shape, Shape]:
            shape_r = self.glider_2d.get_shape()
            if rot:
                zrot = [rib.zrot for rib in self.glider_3d.ribs]
                if any(zrot):
                    baseline_pct = self.glider_2d.config.baseline_pct or Percentage(0.0)
                    shape_r = shape_r.apply_zrot(zrot, baseline_pct)
            shape_l = shape_r.copy().scale(x=-1)

            return shape_r, shape_l


        if config.apply_zrot:
            if force or self.shapes_rot is None:
                self.shapes_rot = get_shape(rot=True)
            
            return self.shapes_rot
        
        else:
            if force or self.shapes is None:
                self.shapes = get_shape(rot=False)

            return self.shapes
    
    def redraw(self, config: ShapePlotConfig, force: bool=False) -> rs_drawing.Layout:
        if config != self.config or force:
            if force:
                self._get_shapes(force=True)
            self.config = config
            self.drawing = rs_drawing.Layout()

            for layer_name, show_layer in config.view_layers().items():
                if show_layer:
                    f = getattr(self, f"draw_{layer_name}")
                    f(left=True)
                    f(left=False)
        
            if config.scale_area:
                self.drawing.scale(math.sqrt(config.scale_area/self.reference_area))
            elif config.scale_span:
                self.drawing.scale(config.scale_span/self.reference_span)
            
        
        return self.drawing

    def copy(self) -> ShapePlot:
        drawing = self.drawing.copy()

        return ShapePlot(self.project, drawing)

    def _get_rib_range(self, left_side: bool) -> range:
        start = 0
        end = self.project.glider.shape.half_cell_num
        if self.glider_2d.shape.has_center_cell and left_side:
            start = 1

        return range(start, end+1)

    
    def _get_cell_range(self, left_side: bool) -> range:
        start = 0
        end = self.project.glider.shape.half_cell_num
        if self.glider_2d.shape.has_center_cell and left_side:
            start = 1

        return range(start, end)
    
    def draw_design_lower(self, left: bool=False) -> ShapePlot:
        return self.draw_design(True, left)
    
    def draw_design_upper(self, left: bool=False) -> ShapePlot:
        return self.draw_design(False, left)

    def draw_design(self, lower: bool=True, left: bool=False, fill: bool=True) -> ShapePlot:
        shapes = self._get_shapes()
        shape = shapes[left]

        panels = self.glider_2d.get_panels()

        for cell_no in self._get_cell_range(left):
            cell_panels = panels[cell_no]

            def match(panel: Panel) -> bool:
                if lower:
                    # -> either on the left or on the right it should go further than 0
                    return panel.cut_back.x_left > 0 or panel.cut_back.x_right > 0
                else:
                    # should start before zero at least once
                    return panel.cut_front.x_left < 0 or panel.cut_front.x_right < 0

            cell_side_panels: Iterator[Panel] = filter(match, cell_panels)

            for panel in cell_side_panels:
                def normalize_x(val: float | Percentage) -> float:
                    if lower:
                        return max(float(val), 0.)
                    else:
                        return max(float(-val), 0.)

                def get_cut_line(cut: PanelCut) -> openglider.rs.vector.PolyLine2D:
                    left = shape.get_point(cell_no, normalize_x(cut.x_left))
                    right = shape.get_point(cell_no+1, normalize_x(cut.x_right))

                    if cut.x_center is not None:
                        center = shape.get_point(cell_no+0.5, normalize_x(cut.x_center))
                        return openglider.rs.spline.BSplineCurve([left, center, right]).get_sequence(8)
                    
                    return openglider.rs.vector.PolyLine2D([left, right])
                
                l1 = get_cut_line(panel.cut_front)
                l2 = get_cut_line(panel.cut_back).reverse()

                part = self._new_part(material_code=f"{panel.material}#{panel.material.color_code}")
                if panel.color_group is not None:
                    layer_name = f"panels_{panel.color_group}"
                else:
                    layer_name = f"panels_{panel.material}#{panel.material.color_code}"
                with part.layer(layer_name) as layer:
                    if fill:
                        layer.style.fill = f"#{panel.material.color_code}"
                    layer.add_line(openglider.rs.vector.PolyLine2D(l1.nodes + l2.nodes + [l1.nodes[0]]))
                self.drawing.add_part(part)

        return self

    def draw_baseline(self, pct: float | None=None, left: bool=False) -> None:
        shapes = self._get_shapes()
        shape = shapes[left]

        if pct is None:
            if self.glider_2d.config.baseline_pct is None:
                pct = 0
            else:
                pct = self.glider_2d.config.baseline_pct.si

        part = self._new_part()
        line = openglider.rs.vector.PolyLine2D([shape.get_point(rib, pct) for rib in self._get_rib_range(left)])
        part.add_line("marks", line)
        self.drawing.add_part(part)

    def draw_grid(self, num: int=11, left: bool=False) -> ShapePlot:
        import numpy as np

        for x in np.linspace(0, 1, num):
            self.draw_baseline(x, left=left)

        self.draw_cells(left=left)
        return self

    def draw_en_marks(self) -> None:
        part = self._new_part()
        shapes = self._get_shapes()

        front, back = shapes[1].ribs[0]
        
        dist = abs(front[1]-back[1])

        def baseline(pct: float) -> openglider.rs.vector.PolyLine2D:
            return openglider.rs.vector.PolyLine2D(
                [shapes[0].get_point(rib, pct) for rib in self._get_rib_range(True)][::-1] +
                [shapes[1].get_point(rib, pct) for rib in self._get_rib_range(False)]
            )

        collapse_side_50 = openglider.rs.vector.PolyLine2D([
            openglider.rs.vector.Vector2D((0, front[1])),
            openglider.rs.vector.Vector2D((-dist, back[1]))
        ])
        collapse_side_75 = openglider.rs.vector.PolyLine2D([
            openglider.rs.vector.Vector2D((0, back[1])),
            openglider.rs.vector.Vector2D((dist, front[1]))
        ])

        diff = openglider.rs.vector.Vector2D([self.glider_2d.shape.span*0.05/2, 0])

        for line in [
            collapse_side_50,
            collapse_side_75.move(diff*-1),
            collapse_side_75.move(diff),
            baseline(0.25),
            baseline(0.5),
        ]:
            part.add_line("marks", line)

        self.drawing.add_part(part)

    def _get_attachment_point_positions(self, left: bool=False) -> dict[str, openglider.rs.vector.Vector2D]:

        points = {}
        shapes = self._get_shapes()
        shape = shapes[left]

        for rib_no, rib in enumerate(self.glider_3d.ribs):
            for attachment_point in rib.attachment_points:
                points[attachment_point.name] = shape.get_point(rib_no, attachment_point.rib_pos)
        
        for cell_no, cell in enumerate(self.glider_3d.cells):
            for cell_attachment_point in cell.attachment_points:
                points[cell_attachment_point.name] = shape.get_point(cell_no + cell_attachment_point.cell_pos, cell_attachment_point.rib_pos)
            
        return points


    def draw_attachment_points(self, add_text: bool=True, left: bool=False) -> None:
        part = self._new_part()
        points = self._get_attachment_point_positions(left=left)
        text_size = self._absolute_size_from_a4_mm(self.attachment_text_size_mm)
        text_offset = self._absolute_size_from_a4_mm(self.attachment_text_offset_mm)

        with part.layer("attachment_points") as layer:
            layer.style.stroke="green"
            layer.style.stroke_width=0.25
            for name, p1 in points.items():
                p2 = p1 + openglider.rs.vector.Vector2D([0.1, 0])

                diff = (p2-p1)*0.2
                cross_left = p1 - diff
                cross_right = p1 + diff

                cross = self.attachment_point_mark(cross_left, cross_right)
                for cross_line in sum(cross.values(), start=[]):
                    layer.add_line(cross_line)

                if add_text and name:
                    text_start = p1 + openglider.rs.vector.Vector2D([0, text_offset])
                    text_end = text_start + openglider.rs.vector.Vector2D([1, 0])
                    text = rs_drawing.Text(f" {name} ", text_start, text_end, size=text_size)
                    layer.add_text(text)

        self.drawing.add_part(part)

    def draw_cells(self, left: bool=False) -> None:
        shapes = self._get_shapes()
        shape = shapes[left]

        cells = []

        for cell_no in self._get_cell_range(left):
            p1 = shape.get_point(cell_no, 0)
            p2 = shape.get_point(cell_no+1, 0)
            p3 = shape.get_point(cell_no+1, 1)
            p4 = shape.get_point(cell_no, 1)
            cells.append(openglider.rs.vector.PolyLine2D([p1,p2,p3,p4,p1]))

        part = self._new_part(material_code="cell_numbers")
        with part.layer("cells") as layer:
            layer.style.stroke="grey"
            layer.style.stroke_width=0.25
            for cell in cells:
                layer.add_line(cell)
        self.drawing.add_part(part)

    def _get_font_size(self) -> float:
        assert self.shapes is not None
        
        cell_range = self._get_cell_range(False)
        min_cell_width = min(
            abs(self.shapes[0].get_point(cell_no+1, 0)[0] - self.shapes[0].get_point(cell_no, 0)[0])
            for cell_no in cell_range
        )
        return min_cell_width * 0.8 / len(str(max(cell_range)))

    def draw_cell_names(self, left: bool=False) -> None:
        shapes = self._get_shapes()
        shape = shapes[left]
        cell_range = self._get_cell_range(left)
        if not cell_range:
            return

        size = self._get_font_size()

        for cell_no in cell_range:
            cell = self.glider_3d.cells[cell_no]
            center = shape.get_point(cell_no + 0.5, 0.5)
            p1 = openglider.rs.vector.Vector2D([center[0] - 0.5, center[1]])
            p2 = openglider.rs.vector.Vector2D([center[0] + 0.5, center[1]])

            text = rs_drawing.Text(cell.name, p1, p2, size=size, valign=0, align=0)
            part = self._new_part(material_code="cell_numbers")
            part.add_text("text", text)
            self.drawing.add_part(part)

    def draw_rib_names(self, left: bool=False) -> ShapePlot:
        shapes = self._get_shapes()
        shape = shapes[left]
        cell_range = self._get_cell_range(left)
        if not cell_range:
            return self

        size = self._get_font_size()

        for rib_no in self._get_rib_range(left):
            rib = self.glider_3d.ribs[rib_no]
            rib_back = shape.get_point(rib_no, 1.)
            y = rib_back[1]

            p1 = openglider.rs.vector.Vector2D([rib_back[0] - 0.5, y])
            p2 = openglider.rs.vector.Vector2D([rib_back[0] + 0.5, y])

            text = rs_drawing.Text(rib.name, p1, p2, size=size, valign=-1.5, align=0)
            part = self._new_part(material_code="rib_numbers")
            part.add_text("text", text)
            self.drawing.add_part(part)
        return self

    def draw_straps(self, left: bool=False) -> ShapePlot:
        shapes = self._get_shapes()
        shape = shapes[left]

        for cell_no in self._get_cell_range(left):
            cell = self.glider_3d.cells[cell_no]
            for diagonal in cell.straps:
                left_x_values = [abs(x) for x in (diagonal.side1.start_x(cell.rib1), diagonal.side1.end_x(cell.rib1))]
                right_x_values = [abs(x) for x in (diagonal.side2.start_x(cell.rib2), diagonal.side2.end_x(cell.rib2))]

                points_left = [shape.get_point(cell_no, p) for p in left_x_values]
                points_right = [shape.get_point(cell_no+1, p) for p in right_x_values]

                part = self._new_part()
                part.add_line("marks", openglider.rs.vector.PolyLine2D(points_left + points_right[::-1] + points_left[:1]))
                self.drawing.add_part(part)

        return self

    def draw_diagonals(self, left: bool=False) -> ShapePlot:
        shapes = self._get_shapes()
        shape = shapes[left]

        for cell_no in self._get_cell_range(left):
            cell = self.glider_3d.cells[cell_no]
            for diagonal in cell.diagonals:
                left_x_values = [abs(x) for x in (diagonal.side1.start_x(cell.rib1), diagonal.side1.end_x(cell.rib1))]
                right_x_values = [abs(x) for x in (diagonal.side2.start_x(cell.rib2), diagonal.side2.end_x(cell.rib2))]

                points_left = [shape.get_point(cell_no, p) for p in left_x_values]
                points_right = [shape.get_point(cell_no+1, p) for p in right_x_values]

                part = self._new_part()
                part.add_line("marks", openglider.rs.vector.PolyLine2D(points_left + points_right[::-1] + points_left[:1]))
                self.drawing.add_part(part)

        return self

    def draw_lines(self, left: bool=True, add_text: bool=False) -> ShapePlot:
        #self.draw_design(lower=True)
        #self.draw_design(lower=True, left=True)
        #self.draw_attachment_points(True)
        #self.draw_attachment_points(True, left=True)
        lower = self.glider_3d.lineset.lower_attachment_points

        attachment_point_positions = self._get_attachment_point_positions(left=False)
        all_nodes = {}
        for node in self.glider_3d.lineset.nodes:
            if node.node_type == node.NODE_TYPE.UPPER:
                all_nodes[node] = attachment_point_positions[node.name]

        def get_node_position(node: Node) -> openglider.rs.vector.Vector2D:
            if node in all_nodes:
                return all_nodes[node]

            nodes = [line.upper_node for line in self.glider_3d.lineset.get_upper_connected_lines(node)]

            if len(nodes) == 0:
                raise ValueError(f"no upper nodes for node {node}, {type(node)}")
            elif len(nodes) == 1:
                position = get_node_position(nodes[0]) + openglider.rs.vector.Vector2D([0, -0.2])
            else:

                node_positions = [get_node_position(node) for node in nodes]

                position = sum(node_positions, openglider.rs.vector.Vector2D()) * (1/len(node_positions))

                direction = openglider.rs.vector.Vector2D()

                for node_pos in node_positions:
                    diff = node_pos - position

                    if diff.dot(openglider.rs.vector.Vector2D([1, -1])) < 0:
                        direction += diff * -1
                    else:
                        direction += diff
                
                rotation = openglider.rs.vector.Rotation2D(-math.pi/2)
                direction.normalized()
            
                position += rotation.apply(direction.normalized()*0.1)
            
            all_nodes[node] = position

            return position

        def all_upper_lines(node: Node) -> list[Line]:
            lines: list[Line] = []
            for line in self.glider_3d.lineset.get_upper_connected_lines(node):
                lines.append(line)
                lines += all_upper_lines(line.upper_node)
            
            return lines
        
        text_size = self._absolute_size_from_a4_mm(self.line_text_size_mm)
        def insert_line(glider_line: Line, index: int) -> None:
            if glider_line.line_type.name == "riser":
                return
            pp = self._new_part()
            line = openglider.rs.vector.PolyLine2D([
                # TODO: fix!
                all_nodes[glider_line.upper_node],
                all_nodes[glider_line.lower_node]
            ])
            if index % 2:
                line = line.scale(openglider.rs.vector.Vector2D([-1, 1]))

            line_start = line.nodes[0] + (line.nodes[1] - line.nodes[0]) * 0.5
            line_end = line_start + openglider.rs.vector.Vector2D([0.1, 0])

            text = rs_drawing.Text(
                glider_line.name,
                line_start,
                line_end,
                size=text_size,
                align=-1,
                valign=0,
                )
            with pp.layer("lines") as layer:
                layer.style.stroke="black"
                layer.style.stroke_width=0.25
                layer.add_line(line)
            pp.add_text("text", text)

            self.drawing.add_part(pp)

        i = 0
        for node in lower:
            get_node_position(node)
            base_lines = self.glider_3d.lineset.get_upper_connected_lines(node)
            base_lines_sorted = self.glider_3d.lineset.sort_lines(base_lines, by_names=True)

            for line in base_lines_sorted:
                if line.line_type.name == "riser":
                    insert_line(line, i)

                for upper_line in all_upper_lines(line.upper_node):
                    insert_line(upper_line, i)
            
                i += 1

        return self

    def export_a4(self, path: PathLike) -> None:
        new = self._scaled_a4_layout()
        self._export_svg_to_pdf(path, new)

    def _repr_svg_(self) -> str:
        return self._scaled_a4_layout()._repr_svg_()
