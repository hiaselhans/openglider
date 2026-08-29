from __future__ import annotations
from typing import Callable
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
import logging
import math

import openglider.rs
from openglider.airfoil import get_x_value
from openglider.glider.cell.cell import FlattenedCell
from openglider.glider.cell.panel import Panel
from openglider.glider.cell.panel.panel import FlattenedPanel
from openglider.glider.cell.rigidfoil import EntryStrap
from openglider.plots.config import PatternConfig
from openglider.plots.glider.diagonal import DribPlot, StrapPlot
from openglider.plots.glider.minirib import MiniRibPlot
from openglider.plots.usage_stats import MaterialUsage
from openglider.utils.config import Config
from openglider.vector.drawing import PlotPart
from openglider.vector.text import Text
from openglider.vector.unit import Length, Percentage

if TYPE_CHECKING:
    from openglider.glider.cell import Cell

logger = logging.getLogger(__name__)

class PanelPlot:
    DefaultConf = PatternConfig
    plotpart: PlotPart | None = None
    config: PatternConfig
    flattened_panel: FlattenedPanel | None = None
    flattened_cell: FlattenedCellWithAllowance

    panel: Panel
    cell: Cell

    def __init__(self, panel: Panel, cell: Cell, flattened_cell: FlattenedCellWithAllowance, config: Config | None=None):
        self.panel = panel
        self.cell = cell
        self.config = self.DefaultConf(config)

        self._flattened_cell = flattened_cell.copy()

        self.inner = flattened_cell.inner
        self.ballooned = flattened_cell.ballooned
        self.outer = flattened_cell
        self.outer_orig = flattened_cell.outer_orig

        self.x_values = self.cell.rib1.profile_2d.x_values

    def prepare(self) -> None:
        cut_types = self.config.get_cut_types()
        self.flattened_panel = self.panel.get_flattened(self.cell, self.config.midribs, cut_types=cut_types)

    def flatten(self, extra_marks: list[openglider.rs.vector.PolyLine2D] | None=None) -> PlotPart:
        assert self.flattened_panel is not None, "Call prepare() before flatten()"
        self.plotpart = PlotPart(material_code=str(self.panel.material), name=self.panel.name)

        self.plotpart.layers["envelope"].append(self.flattened_panel.envelope)

        if self.config.debug:
            inner_curves = self.flattened_panel.flattened_cell.inner
            ik_front = self.flattened_panel.cut_front.inner_indices
            ik_back = self.flattened_panel.cut_back.inner_indices

            for curve, ikf, ikb in zip(inner_curves, ik_front, ik_back):
                self.plotpart.layers["debug"].append(curve.get(ikf, ikb))

        # sewings
        self.plotpart.layers["stitches"] += [
            self.inner[0].get(self.flattened_panel.cut_front.inner_indices[0], self.flattened_panel.cut_back.inner_indices[0]),
            self.inner[-1].get(self.flattened_panel.cut_front.inner_indices[-1], self.flattened_panel.cut_back.inner_indices[-1])
            ]

        # folding line
        self.front_curve = openglider.rs.vector.PolyLine2D([
                line.get(x) for line, x in zip(self.inner, self.flattened_panel.cut_front.inner_indices)
            ])
        self.back_curve = openglider.rs.vector.PolyLine2D([
                line.get(x) for line, x in zip(self.inner, self.flattened_panel.cut_back.inner_indices)
            ])

        self.plotpart.layers["marks"] += [
            self.front_curve,
            self.back_curve
        ]

        if extra_marks is not None:
            for mark in extra_marks:
                if len(mark) < 2:
                    self.plotpart.layers["L0"].append(mark.copy())
                else:
                    self.plotpart.layers["marks"].append(mark.copy())

        self.plotpart.layers["cuts"].append(self.flattened_panel.envelope.copy())

        self._insert_text(self.plotpart)
        self._insert_controlpoints(self.plotpart)
        self._insert_attachment_points(self.plotpart)
        self._insert_diagonals(self.plotpart)
        self._insert_miniribs(self.plotpart)

        self._align_upright(self.plotpart)

        return self.plotpart

    def get_endcurves(self) -> tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]:
        ik_values = self.panel.get_ik_values(self.cell, self.config.midribs, exact=True)
        front = openglider.rs.vector.PolyLine2D([
            line.get(ik[0]) for line, ik in zip(self.inner, ik_values)
        ])
        back = openglider.rs.vector.PolyLine2D([
            line.get(ik[1]) for line, ik in zip(self.inner, ik_values)
        ])

        return front, back


    def get_material_usage(self) -> MaterialUsage:
        assert self.plotpart is not None
        envelope = self.plotpart.layers["envelope"].polylines[0]
        area = envelope.get_area()

        return MaterialUsage().consume(self.panel.material, area)


    def get_point(self, x: float | Percentage) -> tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]:
        ik = get_x_value(self.x_values, x)

        return (
            self.ballooned[0].get(ik),
            self.ballooned[1].get(ik)
        )

    def get_p1_p2(self, x: float, is_right: bool) -> tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]:
        if is_right:
            front, back = self.panel.cut_front.x_right, self.panel.cut_back.x_right
        else:
            front, back = self.panel.cut_front.x_left, self.panel.cut_back.x_left

        if front <= x <= back:
            ik = get_x_value(self.x_values, x)

            p1 = self.ballooned[is_right].get(ik)
            p2 = self.outer_orig[is_right].get(ik)

            return p1, p2
        
        raise ValueError("not in range")

    def insert_mark(
        self,
        mark: Callable[[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D], dict[str, list[openglider.rs.vector.PolyLine2D]]],
        x: float | Percentage,
        plotpart: PlotPart,
        is_right: bool
        ) -> None:
        if mark is None:
            return

        if is_right:
            x_front = self.panel.cut_front.x_right
            x_back = self.panel.cut_back.x_right
        else:
            x_front = self.panel.cut_front.x_left
            x_back = self.panel.cut_back.x_left

        if x_front <= x <= x_back:
            ik = get_x_value(self.x_values, x)
            p1 = self.ballooned[is_right].get(ik)
            p2 = self.outer_orig[is_right].get(ik)

            for layer_name, mark_lines in mark(p1, p2).items():
                plotpart.layers[layer_name] += mark_lines

    def _align_upright(self, plotpart: PlotPart) -> PlotPart:
        ik_front = self.front_curve.walk(0, self.front_curve.get_length()/2)
        ik_back = self.back_curve.walk(0, self.back_curve.get_length()/2)

        p1 = self.front_curve.get(ik_front)
        p2 = self.back_curve.get(ik_back)
        
        vector = p2-p1

        angle = vector.angle() - math.pi/2

        plotpart.rotate(-angle)
        return plotpart

    def _insert_text(self, plotpart: PlotPart) -> None:
        text = self.panel.name

        if self.config.layout_seperate_panels and not self.panel.is_lower():
            curve = self.panel.cut_back.get_curve_2d(self.cell, self.config.midribs, exact=True)
        else:
            curve = self.panel.cut_front.get_curve_2d(self.cell, self.config.midribs, exact=True).reverse()

        letter_width = Length("8mm")
        text_width = letter_width.si * len(text)
        ik_p1 = curve.walk(0, curve.get_length()*0.15)

        p1 = curve.get(ik_p1)
        ik_p2 = curve.walk(ik_p1, text_width)
        p2 = curve.get(ik_p2)

        part_text = Text(text, p1, p2,
                         size=letter_width,
                         align="left",
                         valign=-0.9,
                         height=0.8)
        plotpart.layers["text"] += part_text.get_vectors()

    def _insert_controlpoints(self, plotpart: PlotPart) -> None:
        # insert chord-wise controlpoints
        for x in self.config.get_controlpoints(self.cell.rib1):
            self.insert_mark(self.config.marks_controlpoint, x, plotpart, False)
        for x in self.config.get_controlpoints(self.cell.rib2):
            self.insert_mark(self.config.marks_controlpoint, x, plotpart, True)
        
        # insert horizontal (spanwise) controlpoints
        x_dots = 2

        front = (
            self.front_curve,
            self.front_curve.offset(float(self.panel.cut_front.seam_allowance))
        )

        back = (
            self.back_curve,
            self.back_curve.offset(-float(self.panel.cut_back.seam_allowance))
        )

        for i in range(x_dots):
            x = (i+1)/(x_dots+1)

            for inner, outer in (front, back):
                p1 = inner.get(inner.walk(0, inner.get_length() * x))
                p2 = outer.get(outer.walk(0, outer.get_length() * x))
                for layer_name, mark in self.config.marks_controlpoint(p1, p2).items():
                    plotpart.layers[layer_name] += mark


    def _insert_diagonals(self, plotpart: PlotPart) -> None:
        for strap in self.cell.straps + self.cell.diagonals:
            is_upper = strap.is_upper
            is_lower = strap.is_lower

            if is_upper or is_lower:
                self.insert_mark(self.config.marks_diagonal_center, strap.side1.center_x(), plotpart, False)
                self.insert_mark(self.config.marks_diagonal_center, strap.side2.center_x(), plotpart, True)

                # more than 25cm? -> add start / end marks too
                if strap.side1.get_curve(self.cell.rib1).get_length() > self.config.diagonal_endmark_min_length:
                    self.insert_mark(self.config.marks_diagonal_front, strap.side1.start_x(self.cell.rib1), plotpart, False)
                    self.insert_mark(self.config.marks_diagonal_back, strap.side1.end_x(self.cell.rib1), plotpart, False)

                if strap.side2.get_curve(self.cell.rib2).get_length() > self.config.diagonal_endmark_min_length:
                    self.insert_mark(self.config.marks_diagonal_back, strap.side2.start_x(self.cell.rib2), plotpart, True)
                    self.insert_mark(self.config.marks_diagonal_front, strap.side2.end_x(self.cell.rib2), plotpart, True)

            else:
                if strap.side1.is_lower:
                    self.insert_mark(self.config.marks_diagonal_center, strap.side1.center, plotpart, False)
                
                if strap.side2.is_lower:
                    self.insert_mark(self.config.marks_diagonal_center, strap.side2.center, plotpart, True)

    def _insert_attachment_points(self, plotpart: PlotPart, insert_left: bool=True, insert_right: bool=True) -> None:
        def insert_side_mark(name: str, positions: list[float], is_right: bool) -> None:
            try:
                p1, p2 = self.get_p1_p2(positions[0], is_right)
                diff = p1 - p2
                if is_right:
                    start = p1 + diff
                    end = start + diff
                else:
                    end = p1 + diff
                    start = end + diff                   


                text_align = "left" if is_right else "right"
                plotpart.layers["text"] += Text(name, start, end, size=0.01, align=text_align, valign=0, height=0.8).get_vectors()  # type: ignore
                
                for layer_name, mark in self.config.marks_attachment_point(p1, p2).items():
                    plotpart.layers[layer_name] += mark
            except  ValueError:
                pass

            for position in positions:
                self.insert_mark(self.config.marks_attachment_point, position, plotpart, is_right)

        if insert_left:
            for attachment_point in self.cell.rib1.attachment_points:
                # left side
                positions = attachment_point.get_x_values(self.cell.rib1)
                insert_side_mark(attachment_point.name, positions, False)

        if insert_right:
            for attachment_point in self.cell.rib2.attachment_points:
                # left side
                positions = attachment_point.get_x_values(self.cell.rib2)
                insert_side_mark(attachment_point.name, positions, True)
        
        for cell_attachment_point in self.cell.attachment_points:

            cell_pos = cell_attachment_point.cell_pos

            cut_f_l = self.panel.cut_front.x_left
            cut_f_r = self.panel.cut_front.x_right
            cut_b_l = self.panel.cut_back.x_left
            cut_b_r = self.panel.cut_back.x_right
            cut_f = cut_f_l + cell_pos * (cut_f_r - cut_f_l)
            cut_b = cut_b_l + cell_pos * (cut_b_r - cut_b_l)

            positions = [cell_attachment_point.rib_pos.si]
            
            for rib_pos_no, rib_pos in enumerate(positions):

                if cut_f <= cell_attachment_point.rib_pos.si <= cut_b:
                    left, right = self.get_point(rib_pos)

                    p1 = left + (right - left) * cell_pos
                    d = (right - left).normalized() * 0.008 # 8mm
                    if cell_pos == 1:
                        p2 = p1 + d
                    else:
                        p2 = p1 - d
                        
                    if cell_pos in (1, 0):
                        x1, x2 = self.get_p1_p2(rib_pos, bool(cell_pos))
                        for layer_name, mark in self.config.marks_attachment_point(x1, x2).items():
                            plotpart.layers[layer_name] += mark
                    else:
                        for layer_name, mark in self.config.marks_attachment_point(p1, p2).items():
                            plotpart.layers[layer_name] += mark
                    
                    if self.config.insert_attachment_point_text and rib_pos_no == 0:
                        text_align = "left" if cell_pos > 0.7 else "right"

                        if text_align == "right":
                            d1 = (self.get_point(cut_f_l)[0] - left).length()
                            d2 = (self.get_point(cut_b_l)[0] - left).length()
                        else:
                            d1 = (self.get_point(cut_f_r)[1] - right).length()
                            d2 = (self.get_point(cut_b_r)[1] - right).length()

                        bl = self.ballooned[0]
                        br = self.ballooned[1]

                        text_height = 0.01 * 0.8
                        dmin = text_height + 0.001

                        if d1 < dmin and d2 + d1 > 2*dmin:
                            offset = dmin - d1
                            ik = get_x_value(self.x_values, rib_pos)
                            left = bl.get(bl.walk(ik, offset))
                            right = br.get(br.walk(ik, offset))
                        elif d2 < dmin and d1 + d2 > 2*dmin:
                            offset = dmin - d2
                            ik = get_x_value(self.x_values, rib_pos)
                            left = bl.get(bl.walk(ik, -offset))
                            right = br.get(br.walk(ik, -offset))

                        if self.config.layout_seperate_panels and self.panel.is_lower():
                            # rotated later
                            p2 = left
                            p1 = right
                            # text_align = text_align
                        else:
                            p1 = left
                            p2 = right
                            # text_align = text_align
                        plotpart.layers["text"] += Text(f" {cell_attachment_point.name} ", p1, p2,
                                                        size=0.01,  # 1cm
                                                        align=text_align, valign=0, height=0.8).get_vectors()  # type: ignore
                        
    def get_straight_line(
            self,
            y: float,
            start: float,
            end: float,
            ) -> openglider.rs.vector.PolyLine2D | None:
        assert self.flattened_panel is not None, "Call prepare() before draw_straight_line()"

        if start > max(self.panel.cut_back.x_left, self.panel.cut_back.x_right):
            return None
        if end < min(self.panel.cut_front.x_left, self.panel.cut_front.x_right):
            return None

        flattened_cell = self.cell.get_flattened_cell()

        ik_min = self.flattened_panel.cut_front.get_inner_index(y)
        ik_max = self.flattened_panel.cut_back.get_inner_index(y)

        line = flattened_cell.at_position(Percentage(y))

        ik_front = self.cell.rib1.profile_2d(start)
        ik_back = self.cell.rib1.profile_2d(end)
        
        ik_front = max(ik_front, ik_min)
        ik_back = min(ik_back, ik_max)

        if ik_front < ik_back:
            return line.get(ik_front, ik_back)
        
        return None

    def get_area_point(self, x: float, y: float) -> openglider.rs.vector.Vector2D | None:
        assert self.flattened_panel is not None, "Call prepare() before draw_point()"

        # Texture-projected lines can land numerically on panel limits.
        # Keep y within the valid span and nudge exact borders inward.
        y_safe = min(max(float(y), 0.0), 1.0)
        if y_safe <= 0.0:
            y_safe = 1e-9
        elif y_safe >= 1.0:
            y_safe = 1.0 - 1e-9

        if x > max(self.panel.cut_back.x_left, self.panel.cut_back.x_right):
            return None
        if x < min(self.panel.cut_front.x_left, self.panel.cut_front.x_right):
            return None

        try:
            ik_min = self.flattened_panel.cut_front.get_inner_index(y_safe)
            ik_max = self.flattened_panel.cut_back.get_inner_index(y_safe)
        except ValueError:
            return None

        ik = get_x_value(self.x_values, x)

        if ik_min <= ik <= ik_max:
            line = self.cell.get_flattened_cell().at_position(Percentage(y_safe))
            return line.get(ik)
        
        return None

    def get_curve(self, curve: openglider.rs.vector.PolyLine2D) -> openglider.rs.vector.PolyLine2D | None:
        assert self.flattened_panel is not None, "Call prepare() before draw_curve()"

        result: list[openglider.rs.vector.Vector2D] = []
        for point in curve:
            p = self.get_area_point(point.x, point.y)
            if p is not None:
                result.append(p)
        return openglider.rs.vector.PolyLine2D(result) if result else None
    
    def _insert_miniribs(self, plotpart: PlotPart) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for minirib in self.cell.miniribs:

            back_cut = minirib.back_cut or 1.
            line1 = self.get_straight_line(minirib.yvalue, -back_cut, -minirib.front_cut)
            line2 = self.get_straight_line(minirib.yvalue, minirib.front_cut, back_cut)

            result.append((
                line1.get_length() if line1 is not None else 0.,
                line2.get_length() if line2 is not None else 0.
            ))

            for line in (line1, line2):
                if line is not None:
                    plotpart.layers["marks"].append(line)

                    # laser dots
                    plotpart.layers["L0"].append(openglider.rs.vector.PolyLine2D([line.get(0)]))
                    plotpart.layers["L0"].append(openglider.rs.vector.PolyLine2D([line.get(len(line)-1)]))

        return result


class FlattenedCellWithAllowance(FlattenedCell):
    outer: tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]
    outer_orig: tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]

    def copy(self, **kwargs: Any) -> FlattenedCellWithAllowance:
        def copy_tuple(t: tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]) -> tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]:
            return (
                t[0].copy(),
                t[1].copy()
            )
        return FlattenedCellWithAllowance(
            inner=self.inner.copy(),
            ballooned=copy_tuple(self.ballooned),
            outer=copy_tuple(self.outer),
            outer_orig=copy_tuple(self.outer_orig)
        )

class CellPlotMaker:
    run_check = True
    DefaultConf = PatternConfig
    DribPlot = DribPlot
    StrapPlot = StrapPlot
    PanelPlot = PanelPlot
    MiniRibPlot = MiniRibPlot

    def __init__(self, cell: Cell, config: Config | None=None):
        self.cell = cell
        self.config = self.DefaultConf(config)
        
        self.consumption = MaterialUsage()
        self.consumption_drib = MaterialUsage()
        self.consumption_straps = MaterialUsage()
        self.consumption_mribs = MaterialUsage()

        self.prepare()

    def prepare(self) -> None:
        flattened_cell = self.get_flattened_cell()
        self.cell.calculate_3d_shaping(numribs=self.config.midribs)
        self.panel_plots = {
            panel: self.PanelPlot(panel, self.cell, flattened_cell, config=self.config)
            for panel in self.cell.panels
        }
        for panel_plot in self.panel_plots.values():
            panel_plot.prepare()
    
    def get_flattened_cell(self) -> FlattenedCellWithAllowance:
        flattened_cell = self.cell.get_flattened_cell(self.config.midribs)

        left_bal, right_bal = flattened_cell.ballooned

        allowance_left = self.cell.rib1.seam_allowance.si
        allowance_right = self.cell.rib2.seam_allowance.si

        outer_left = left_bal.offset(-allowance_left)
        outer_right = right_bal.offset(allowance_right)

        outer_orig = (
            left_bal.offset(-allowance_left, simple=True),
            right_bal.offset(allowance_right, simple=True)
        )

        outer = (
            outer_left.fix_errors(),
            outer_right.fix_errors()
        )

        return FlattenedCellWithAllowance(
            inner=flattened_cell.inner,
            ballooned=flattened_cell.ballooned,
            outer=outer,
            outer_orig=outer_orig
        )

    def get_panels(self, panels: list[Panel] | None=None, extra_marks: dict[Panel, list[openglider.rs.vector.PolyLine2D]] | None = None) -> list[PlotPart]:
        cell_panels: list[PlotPart] = []

        if panels is None:
            panels = self.cell.panels

        for panel in panels:
            plot = self.panel_plots[panel]
            panel_marks = None
            if extra_marks is not None and panel in extra_marks:
                panel_marks = extra_marks[panel]
            
            dwg = plot.flatten(extra_marks=panel_marks)
            cell_panels.append(dwg)
            self.consumption += plot.get_material_usage()
        
        return cell_panels

    def get_panels_lower(self, extra_marks: dict[Panel, list[openglider.rs.vector.PolyLine2D]] | None = None) -> list[PlotPart]:
        panels = [p for p in self.cell.panels if p.is_lower()]
        return self.get_panels(panels, extra_marks=extra_marks)

    def get_panels_upper(self, extra_marks: dict[Panel, list[openglider.rs.vector.PolyLine2D]] | None = None) -> list[PlotPart]:
        panels = [p for p in self.cell.panels if not p.is_lower()]
        return self.get_panels(panels, extra_marks=extra_marks)

    def get_dribs(self) -> list[PlotPart]:
        diagonals = self.cell.diagonals[:]
        diagonals.sort(key=lambda d: d.name)
        dribs: list[PlotPart] = []
        for drib in diagonals[::-1]:
            drib_plot = self.DribPlot(drib, self.cell, self.config)
            dribs.append(drib_plot.flatten())
            self.consumption_drib += drib_plot.get_material_usage()

        return dribs

    def get_straps(self) -> tuple[list[PlotPart], list[PlotPart]]:
        straps = self.cell.straps[:]
        straps.sort(key=lambda d: (d.is_upper, d.get_average_x().si))
        upper: list[PlotPart] = []
        lower: list[PlotPart] = []
        for strap in straps:
            plot = self.StrapPlot(strap, self.cell, self.config)
            dwg = plot.flatten()
            if strap.is_upper:
                upper.append(dwg)
            else:
                lower.append(dwg)
            self.consumption_straps += plot.get_material_usage()

        return upper, lower
    
    def get_rigidfoils(self) -> tuple[list[PlotPart], dict[Panel, list[openglider.rs.vector.PolyLine2D]]]:
        rigidfoils: list[PlotPart] = []
        panel_marks: dict[Panel, list[openglider.rs.vector.PolyLine2D]] = {}
        for rigidfoil in self.cell.rigidfoils:
            if not isinstance(rigidfoil, EntryStrap):
                drawing, marks = rigidfoil.get_flattened(self.cell, self.config.midribs, cut_types=self.config.get_cut_types())
                drawing.rotate(90, radians=False)
                rigidfoils.append(drawing)
            else:
                marks = rigidfoil.get_marks(self.cell, self.config.midribs, cut_types=self.config.get_cut_types())
            for panel in marks:
                panel_marks.setdefault(panel, [])
                panel_marks[panel] += marks[panel]
        
        return rigidfoils, panel_marks
    

    def get_miniribs(self) -> list[PlotPart]:
        miniribs = self.cell.miniribs[:]
        miniribs.sort(key=lambda d: d.name)
        mribs: list[PlotPart] = []
        for mrib in miniribs[::-1]:
            mrib_plot = self.MiniRibPlot(mrib, self.cell, self.config)
            mribs.append(mrib_plot.flatten())
            self.consumption_mribs += mrib_plot.get_material_usage()
        
        return mribs
