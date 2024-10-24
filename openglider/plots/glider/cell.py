from __future__ import annotations
from typing import TYPE_CHECKING, Any
from collections.abc import Callable
import logging
import math

import euklid
import numpy as np
from openglider.airfoil import get_x_value
from openglider.glider.cell.cell import FlattenedCell
from openglider.glider.cell.panel import Panel, PANELCUT_TYPES
from openglider.plots.config import PatternConfig
from openglider.plots.cuts import Cut, CutResult
from openglider.plots.glider.diagonal import DribPlot, StrapPlot
from openglider.plots.glider.minirib import MiniRibPlot
from openglider.plots.usage_stats import MaterialUsage
from openglider.utils.cache import cached_property
from openglider.utils.config import Config
from openglider.vector.drawing import PlotPart
from openglider.vector.text import Text
from openglider.vector.unit import Percentage

if TYPE_CHECKING:
    from openglider.glider.cell import Cell

logger = logging.getLogger(__name__)

class PanelPlot:
    DefaultConf = PatternConfig
    plotpart: PlotPart
    config: PatternConfig

    panel: Panel
    cell: Cell

    def __init__(self, panel: Panel, cell: Cell, flattended_cell: FlattenedCellWithAllowance, config: Config | None=None):
        self.panel = panel
        self.cell = cell
        self.config = self.DefaultConf(config)

        self._flattened_cell = flattended_cell.copy()

        self.inner = flattended_cell.inner
        self.ballooned = flattended_cell.ballooned
        self.outer = flattended_cell
        self.outer_orig = flattended_cell.outer_orig

        self.x_values = self.cell.rib1.profile_2d.x_values

        self.logger = logging.getLogger(r"{self.__class__.__module__}.{self.__class__.__name__}")

    def flatten(self) -> PlotPart:
        plotpart = PlotPart(material_code=str(self.panel.material), name=self.panel.name)

        cut_types: dict[PANELCUT_TYPES, type[Cut]] = {
            PANELCUT_TYPES.folded: self.config.cut_entry,
            PANELCUT_TYPES.parallel: self.config.cut_trailing_edge,
            PANELCUT_TYPES.orthogonal: self.config.cut_design,
            PANELCUT_TYPES.singleskin: self.config.cut_entry,
            PANELCUT_TYPES.cut_3d: self.config.cut_3d,
            PANELCUT_TYPES.round: self.config.cut_round
        }

        ik_front = self.panel.cut_front._get_ik_values(self.cell, x_values=self.config.midribs, exact=True)
        ik_back = self.panel.cut_back._get_ik_values(self.cell, x_values=self.config.midribs, exact=True)

        allowance_front = -self.panel.cut_front.seam_allowance
        allowance_back = self.panel.cut_back.seam_allowance

        # cuts -> cut-line, index left, index right
        self.cut_front = cut_types[self.panel.cut_front.cut_type](amount=allowance_front)
        self.cut_back = cut_types[self.panel.cut_back.cut_type](amount=allowance_back)

        inner_front = [(line, ik) for line, ik in zip(self.inner, ik_front)]
        inner_back = [(line, ik) for line, ik in zip(self.inner, ik_back)]

        shape_3d_amount_front = [-x for x in self.panel.cut_front.cut_3d_amount]
        shape_3d_amount_back = self.panel.cut_back.cut_3d_amount

        # zero-out 3d-shaping if there is none
        if self.panel.cut_front.cut_type != PANELCUT_TYPES.cut_3d:
            dist = np.linspace(shape_3d_amount_front[0], shape_3d_amount_front[-1], len(shape_3d_amount_front))
            shape_3d_amount_front = list(dist)

        if self.panel.cut_back.cut_type != PANELCUT_TYPES.cut_3d:
            dist = np.linspace(shape_3d_amount_back[0], shape_3d_amount_back[-1], len(shape_3d_amount_back))
            shape_3d_amount_back = list(dist)

        left = inner_front[0][0].get(inner_front[0][1], inner_back[0][1])
        right = inner_front[-1][0].get(inner_front[-1][1], inner_back[-1][1])

        outer_left = left.offset(-self.cell.rib1.seam_allowance.si)
        outer_right = right.offset(self.cell.rib2.seam_allowance.si)

        cut_front_result = self.cut_front.apply(inner_front, outer_left, outer_right, shape_3d_amount_front)
        cut_back_result = self.cut_back.apply(inner_back, outer_left, outer_right, shape_3d_amount_back)

        panel_left: euklid.vector.PolyLine2D | None = None
        if cut_front_result.index_left < cut_back_result.index_left:
            panel_left = outer_left.get(cut_front_result.index_left, cut_back_result.index_left).fix_errors()
        panel_back = cut_back_result.outline.copy()

        panel_right: euklid.vector.PolyLine2D | None = None
        if cut_back_result.index_right > cut_front_result.index_right:
            panel_right = outer_right.get(cut_back_result.index_right, cut_front_result.index_right).fix_errors()
        panel_front = cut_front_result.outline.copy()

        # spitzer schnitt
        # rechts
        # TODO: FIX!
        # if cut_front_result.index_right >= cut_back_result.index_right:
        #     panel_right = euklid.vector.PolyLine2D([])

        #     _cuts = panel_front.cut_with_polyline(panel_back, startpoint=len(panel_front) - 1)
        #     try:
        #         ik_front, ik_back = next(_cuts)
        #         panel_back = panel_back.get(0, ik_back)
        #         panel_front = panel_front.get(0, ik_front)
        #     except StopIteration:
        #         pass  # todo: fix!!

        # # lechts
        # if cut_front_result.index_left >= cut_back_result.index_left:
        #     panel_left = euklid.vector.PolyLine2D([])

        #     _cuts = panel_front.cut_with_polyline(panel_back, startpoint=0)
        #     try:
        #         ik_front, ik_back = next(_cuts)
        #         panel_back = panel_back.get(ik_back, len(panel_back)-1)
        #         panel_front = panel_front[ik_front, len(panel_back)-1]
        #     except StopIteration:
        #         pass  # todo: fix as well!

        panel_back = panel_back.get(len(panel_back)-1, 0)
        if panel_right:
            envelope = panel_right.reverse() + panel_back
        else:
            envelope = panel_back

        if panel_left:
            envelope += panel_left.reverse()
        envelope += panel_front
        envelope += euklid.vector.PolyLine2D([envelope.nodes[0]])

        plotpart.layers["envelope"].append(envelope)

        if self.config.debug:
            plotpart.layers["debug"].append(euklid.vector.PolyLine2D([line.get(ik) for line, ik in inner_front]))
            plotpart.layers["debug"].append(euklid.vector.PolyLine2D([line.get(ik) for line, ik in inner_back]))
            for front, back in zip(inner_front, inner_back):
                plotpart.layers["debug"].append(front[0].get(front[1], back[1]))

        # sewings
        plotpart.layers["stitches"] += [
            self.inner[0].get(cut_front_result.inner_indices[0], cut_back_result.inner_indices[0]),
            self.inner[-1].get(cut_front_result.inner_indices[-1], cut_back_result.inner_indices[-1])
            ]

        # folding line
        self.front_curve = euklid.vector.PolyLine2D([
                line.get(x) for line, x in zip(self.inner, cut_front_result.inner_indices)
            ])
        self.back_curve = euklid.vector.PolyLine2D([
                line.get(x) for line, x in zip(self.inner, cut_back_result.inner_indices)
            ])

        plotpart.layers["marks"] += [
            self.front_curve,
            self.back_curve
        ]

        plotpart.layers["cuts"].append(envelope.copy())

        self._insert_text(plotpart)
        self._insert_controlpoints(plotpart)
        self._insert_attachment_points(plotpart)
        self._insert_diagonals(plotpart)
        self._insert_rigidfoils(plotpart, cut_front_result, cut_back_result)
        self._insert_miniribs(plotpart, cut_front_result, cut_back_result)

        self._align_upright(plotpart)

        self.plotpart = plotpart
        return plotpart
    
    def get_endcurves(self) -> tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]:
        ik_values = self.panel._get_ik_values(self.cell, self.config.midribs, exact=True)
        front = euklid.vector.PolyLine2D([
            line.get(ik[0]) for line, ik in zip(self.inner, ik_values)
        ])
        back = euklid.vector.PolyLine2D([
            line.get(ik[1]) for line, ik in zip(self.inner, ik_values)
        ])

        return front, back


    def get_material_usage(self) -> MaterialUsage:
        part = self.flatten()
        envelope = part.layers["envelope"].polylines[0]
        area = envelope.get_area()

        return MaterialUsage().consume(self.panel.material, area)


    def get_point(self, x: float | Percentage) -> tuple[euklid.vector.Vector2D, euklid.vector.Vector2D]:
        ik = get_x_value(self.x_values, x)

        return (
            self.ballooned[0].get(ik),
            self.ballooned[1].get(ik)
        )

    def get_p1_p2(self, x: float, is_right: bool) -> tuple[euklid.vector.Vector2D, euklid.vector.Vector2D]:
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
        mark: Callable[[euklid.vector.Vector2D, euklid.vector.Vector2D], dict[str, list[euklid.vector.PolyLine2D]]],
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
            allowance = self.panel.cut_back.seam_allowance
            curve = self.panel.cut_back.get_curve_2d(self.cell, self.config.midribs, exact=True)
        else:
            allowance = self.panel.cut_front.seam_allowance
            curve = self.panel.cut_front.get_curve_2d(self.cell, self.config.midribs, exact=True).reverse()

        text_width = allowance.si * 0.8 * len(text)
        ik_p1 = curve.walk(0, curve.get_length()*0.15)

        p1 = curve.get(ik_p1)
        ik_p2 = curve.walk(ik_p1, text_width)
        p2 = curve.get(ik_p2)

        part_text = Text(text, p1, p2,
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
            self.front_curve.offset(-float(self.cut_front.amount))
        )

        back = (
            self.back_curve,
            self.back_curve.offset(-float(self.cut_back.amount))
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
                        
    def draw_straight_line(
            self,
            y: float,
            start: float,
            end: float,
            cut_front_result: CutResult,
            cut_back_result: CutResult
            ) -> euklid.vector.PolyLine2D | None:
        logger.warning(f"straight line {y} {start} {end}")
        if start > max(self.panel.cut_back.x_left, self.panel.cut_back.x_right):
            return None
        if end < min(self.panel.cut_front.x_left, self.panel.cut_front.x_right):
            return None

        flattened_cell = self.cell.get_flattened_cell()

        ik_min = cut_front_result.get_inner_index(y)
        ik_max = cut_back_result.get_inner_index(y)

        line = flattened_cell.at_position(Percentage(y))

        ik_front = self.cell.rib1.profile_2d(start)
        ik_back = self.cell.rib1.profile_2d(end)
        #ik_front = mix(self.cell.rib1.profile_2d(start), self.cell.rib2.profile_2d(start), y)
        #ik_back = mix(self.cell.rib1.profile_2d(end), self.cell.rib2.profile_2d(end), y)
        
        ik_front = max(ik_front, ik_min)
        ik_back = min(ik_back, ik_max)

        logger.warning(f"ok2 {ik_front} {ik_back}")
        if ik_front < ik_back:
            return line.get(ik_front, ik_back)
        
        return None
    
    def _insert_rigidfoils(self, plotpart: PlotPart, cut_front_result: CutResult, cut_back_result: CutResult) -> None:
        for rigidfoil in self.cell.rigidfoils:
            line = self.draw_straight_line(rigidfoil.y, rigidfoil.x_start, rigidfoil.x_end, cut_front_result, cut_back_result)
            if line is not None:
                plotpart.layers["marks"].append(line)

                # laser dots
                plotpart.layers["L0"].append(euklid.vector.PolyLine2D([line.get(0)]))
                plotpart.layers["L0"].append(euklid.vector.PolyLine2D([line.get(len(line)-1)]))

    def _insert_miniribs(self, plotpart: PlotPart, cut_front_result: CutResult, cut_back_result: CutResult) -> list[tuple[float, float]]:
        result: list[tuple[float, float]] = []
        for minirib in self.cell.miniribs:

            back_cut = minirib.back_cut or 1.
            line1 = self.draw_straight_line(minirib.yvalue, -back_cut, -minirib.front_cut, cut_front_result, cut_back_result)
            line2 = self.draw_straight_line(minirib.yvalue, minirib.front_cut, back_cut, cut_front_result, cut_back_result)

            result.append((
                line1 and line1.get_length() or 0.,
                line2 and line2.get_length() or 0.
            ))

            for line in (line1, line2):
                if line is not None:
                    plotpart.layers["marks"].append(line)

                    # laser dots
                    plotpart.layers["L0"].append(euklid.vector.PolyLine2D([line.get(0)]))
                    plotpart.layers["L0"].append(euklid.vector.PolyLine2D([line.get(len(line)-1)]))

        return result


class FlattenedCellWithAllowance(FlattenedCell):
    outer: tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]
    outer_orig: tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]

    def copy(self, **kwargs: Any) -> FlattenedCellWithAllowance:
        def copy_tuple(t: tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]) -> tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]:
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
        
        self._flattened_cell = None
    
    @cached_property("cell", "config.midribs")
    def flattened_cell(self) -> FlattenedCellWithAllowance:
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

    def get_panels(self, panels: list[Panel] | None=None) -> list[PlotPart]:
        cell_panels = []
        self.cell.calculate_3d_shaping(numribs=self.config.midribs)

        if panels is None:
            panels = self.cell.panels

        for panel in panels:
            plot = self.PanelPlot(panel, self.cell, self.flattened_cell, config=self.config)
            dwg = plot.flatten()
            cell_panels.append(dwg)
            self.consumption += plot.get_material_usage()
        
        return cell_panels

    def get_panels_lower(self) -> list[PlotPart]:
        panels = [p for p in self.cell.panels if p.is_lower()]
        return self.get_panels(panels)

    def get_panels_upper(self) -> list[PlotPart]:
        panels = [p for p in self.cell.panels if not p.is_lower()]
        return self.get_panels(panels)

    def get_dribs(self) -> list[PlotPart]:
        diagonals = self.cell.diagonals[:]
        diagonals.sort(key=lambda d: d.name)
        dribs = []
        for drib in diagonals[::-1]:
            drib_plot = self.DribPlot(drib, self.cell, self.config)
            dribs.append(drib_plot.flatten())
            self.consumption_drib += drib_plot.get_material_usage()

        return dribs

    def get_straps(self) -> tuple[list[PlotPart], list[PlotPart]]:
        straps = self.cell.straps[:]
        straps.sort(key=lambda d: (d.is_upper, d.get_average_x().si))
        upper = []
        lower = []
        for strap in straps:
            plot = self.StrapPlot(strap, self.cell, self.config)
            dwg = plot.flatten()
            if strap.is_upper:
                upper.append(dwg)
            else:
                lower.append(dwg)
            self.consumption_straps += plot.get_material_usage()

        return upper, lower
    
    def get_rigidfoils(self) -> list[PlotPart]:
        rigidfoils = []
        for rigidfoil in self.cell.rigidfoils:
            rigidfoils.append(rigidfoil.get_flattened(self.cell))
        
        return rigidfoils
    

    def get_miniribs(self) -> list[PlotPart]:
        miniribs = self.cell.miniribs[:]
        miniribs.sort(key=lambda d: d.name)
        mribs = []
        for mrib in miniribs[::-1]:
            mrib_plot = self.MiniRibPlot(mrib, self.cell, self.config)
            mribs.append(mrib_plot.flatten())
            self.consumption_mribs += mrib_plot.get_material_usage()
        
        return mribs
