from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Literal
from collections.abc import Callable

import openglider.rs
from openglider.rs import drawing

from openglider.airfoil import get_x_value
from openglider.glider.cell.diagonals import DiagonalSide
from openglider.glider.cell.panel import PANELCUT_TYPES
from openglider.glider.rib.rigidfoils import RigidFoilBase
from openglider.plots.config import PatternConfig
from openglider.plots.glider.layer_styles import add_line, add_lines, initialize_part_layer_strokes
from openglider.plots.usage_stats import MaterialUsage
from openglider.utils.config import Config
from openglider.vector.text import Text
from openglider.vector.unit import Length, Percentage



if TYPE_CHECKING:
    from openglider.glider.rib import Rib
    from openglider.glider import Glider


Vector2D = openglider.rs.vector.Vector2D

logger = logging.getLogger(__name__)
def _merge_parts(dst: drawing.Part, src: drawing.Part) -> None:
    for layer_name, layer in src.layers.items():
        add_lines(dst, layer_name, list(layer.lines))
        for text in layer.texts:
            dst.add_text(layer_name, text)


def _part_bbox(part: drawing.Part) -> tuple[float, float, float, float]:
    return part.bbox() or (0.0, 0.0, 0.0, 0.0)


class RigidFoilPlot:
    rigidfoil: RigidFoilBase
    ribplot: RibPlot

    drawing: drawing.Part
    inner_curve: openglider.rs.vector.PolyLine2D | None = None
    outer_curve: openglider.rs.vector.PolyLine2D | None = None
    center_curve: openglider.rs.vector.PolyLine2D | None = None

    def __init__(self, rigidfoil: RigidFoilBase, ribplot: RibPlot) -> None:
        self.rigidfoil = rigidfoil
        self.ribplot = ribplot
        self.drawing = initialize_part_layer_strokes(drawing.Part())

    def add_text(self) -> None:
        (_, p1), (_, p2) = self.get_cap("back")

        add_lines(self.drawing, self.ribplot.layer_name_text, Text(
            self.rigidfoil.name, p1, p2, align="center", valign=0.6
        ).get_vectors())

    def get_cap(self, side: Literal["front", "back"], outer_distance: float | None = None) -> tuple[tuple[Vector2D, Vector2D], tuple[Vector2D, Vector2D]]:
        if side == "front":
            position = 0
            angle = math.pi/2
        elif side == "back":
            position = -1
            angle = -math.pi/2
        else:
            raise ValueError("side must be 'front' or 'back'")
        
        if self.center_curve is None:
            raise ValueError("Setup not called")

        if outer_distance is None:
            outer_distance = self.get_outer_distance().si
        inner_distance = self.get_inner_distance().si

        center_point = self.center_curve.nodes[position]
        normal = self.center_curve.normvectors().nodes[position]

        outer_point = center_point + normal * outer_distance
        inner_point = center_point - normal * inner_distance
        # back cap
        diff = openglider.rs.vector.Rotation2D(angle).apply(inner_point - outer_point).normalized() * self.rigidfoil.cap_length.si

        return (
            (inner_point, outer_point),
            (inner_point+diff, outer_point+diff)
        )
    
    def get_outer_distance(self) -> Length:
        distance = self.ribplot.rib.convert_to_chordlength(self.rigidfoil.distance)
        return self.ribplot.rib.seam_allowance + distance + self.rigidfoil.diameter/2
    
    def get_inner_distance(self) -> Length:
        if self.rigidfoil.inner_allowance:
            allowance = self.rigidfoil.inner_allowance
        else:
            allowance = self.ribplot.rib.seam_allowance
        
        return (self.rigidfoil.diameter/2+allowance)
    
    def setup(self, glider: Glider) -> tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]:
        if any([x is None for x in [self.inner_curve, self.outer_curve, self.center_curve]]):
            curve = self.rigidfoil.get_center_line(self.ribplot.rib, glider)

            d_outer = self.get_outer_distance()
            d_inner = self.get_inner_distance()

            
            self.center_curve = curve.fix_errors()
            self.inner_curve = self.center_curve.offset(-d_inner.si)
            self.outer_curve = self.center_curve.offset(d_outer.si)

        return self.center_curve, self.inner_curve, self.outer_curve  # type: ignore
    
    def insert_mark(self) -> None:
        assert self.center_curve is not None

        rigidfoil_outline = self.rigidfoil.get_flattened(self.center_curve)

        add_line(self.drawing, self.ribplot.layer_name_marks, rigidfoil_outline)
        add_line(self.ribplot.plotpart, self.ribplot.layer_name_rigidfoils, rigidfoil_outline)
    
    def flatten(self, glider: Glider) -> drawing.Part:
        curve, inner_curve, outer_curve = self.setup(glider)
        plotpart = self.drawing

        controlpoints: list[tuple[float, list[openglider.rs.vector.PolyLine2D]]] = []
        for x in self.ribplot.config.get_controlpoints(self.ribplot.rib):
            for mark in self.ribplot.insert_mark(x, self.ribplot.config.marks_controlpoint, insert=False):
                controlpoints.append((x, mark))

        # add marks into the profile
        add_line(self.ribplot.plotpart, self.ribplot.layer_name_laser_dots, openglider.rs.vector.PolyLine2D([curve.get(0)]))
        add_line(self.ribplot.plotpart, self.ribplot.layer_name_laser_dots, openglider.rs.vector.PolyLine2D([curve.get(len(curve)-1)]))

        back_cap = self.get_cap("back")
        plotpart.add_line(self.ribplot.layer_name_marks, openglider.rs.vector.PolyLine2D(list(back_cap[0])))

        front_cap = self.get_cap("front")
        plotpart.add_line(self.ribplot.layer_name_marks, openglider.rs.vector.PolyLine2D(list(front_cap[0])))
        
        outline_nodes = inner_curve.nodes[:]
        outline_nodes += list(back_cap[1])
        outline_nodes += outer_curve.reverse().nodes
        outline_nodes += openglider.rs.vector.PolyLine2D(list(front_cap[1])).reverse().nodes
        outline = openglider.rs.vector.PolyLine2D(outline_nodes)

        for x, controlpoint in controlpoints:
            p = controlpoint[0].nodes[0]
            fits_x = self.rigidfoil.start < x and x < self.rigidfoil.end
            if fits_x or outline.contains(p):
                add_lines(plotpart, self.ribplot.layer_name_laser_dots, controlpoint)
                
        plotpart.add_line(self.ribplot.layer_name_outline, outline.fix_errors().close())

        self.insert_mark()
        self.add_text()

        return plotpart



class RibPlot:
    x_values: list[float]
    inner: openglider.rs.vector.PolyLine2D
    outer: openglider.rs.vector.PolyLine2D

    config: PatternConfig
    DefaultConf = PatternConfig
    RigidFoilPlotFactory = RigidFoilPlot

    rib: Rib

    layer_name_outline = "cuts"
    layer_name_sewing = "sewing"
    layer_name_rigidfoils = "marks"
    layer_name_text = "text"
    layer_name_marks = "marks"
    layer_name_laser_dots = "L0"
    layer_name_crossports = "cuts"

    def __init__(self, rib: Rib, config: Config | None=None):
        self.rib = rib
        self.config = self.DefaultConf(config)

        #self.plotpart = self.x_values = self.inner = self.outer = None

    def get_panel_free_zones(self, glider: Glider) -> list[tuple[Percentage, Percentage]]:
        panels: list[list[tuple[Percentage, Percentage]]] = []
        for cell in glider.cells:
            if len(cell.panels) < 1:
                continue
            if cell.rib1 == self.rib:
                panels.append([
                    (panel.cut_front.x_left, panel.cut_back.x_left) for panel in cell.panels
                ])
            if cell.rib2 == self.rib:
                panels.append([
                    (panel.cut_front.x_right, panel.cut_back.x_right) for panel in cell.panels
                ])
        
        result: list[tuple[Percentage, Percentage]] = []
        last_cut = Percentage(-1)
        current_indices = [0] * len(panels)

        while True:
            # go through all panels and check for gaps
            gap_end = None

            while gap_end is None:
                for cell_index in range(len(panels)):
                    while current_indices[cell_index] < len(panels[cell_index]):
                        panel_index = current_indices[cell_index]
                        panel = panels[cell_index][panel_index]

                        if panel[0] > last_cut:
                            # we have a gap => update gap and break the inner loop
                            if gap_end is None:
                                gap_end = panel[0]
                                break
                            elif gap_end < panel[0]:
                                gap_end = panel[0]
                                break
                        else:
                            # no gap => reset
                            gap_end = None
                            last_cut = max(last_cut, panel[1])
                        
                        current_indices[cell_index] += 1

                # break the loop when we are at the end
                if all([current_indices[i] >= len(panels[i]) for i in range(len(panels))]):
                    break
            
            if gap_end is not None:
                result.append((last_cut, gap_end))
                last_cut = gap_end

            # break the loop when we are at the end
            if all([current_indices[i] >= len(panels[i]) for i in range(len(panels))]):
                break
            
        if last_cut < Percentage(1):
            result.append((last_cut, Percentage(1)))

        return result
    
    def get_panel_cuts(self, glider: Glider) -> list[tuple[Percentage, bool]]:
        cuts_entry = self._get_panel_cuts(glider, True)
        cuts_all = self._get_panel_cuts(glider, False)

        cuts_design = set(cuts_all) - set(cuts_entry)
        
        all_cuts_with_type = [(x, True) for x in cuts_entry] + [(x, False) for x in cuts_design]
        all_cuts_with_type.sort(key=lambda x: x[0])

        return all_cuts_with_type



    def _get_panel_cuts(self, glider: Glider, connected: bool) -> list[Percentage]:
        panel_cuts: set[Percentage] = set()

        for cell in glider.cells:
            if self.rib not in cell.ribs:
                continue

            if not connected:
                panels = cell.panels
            else:
                panels = cell.get_connected_panels()

            if cell.rib1 == self.rib:
                # panel-cuts
                for panel in panels:
                    panel_cuts.add(panel.cut_front.x_left)
                    panel_cuts.add(panel.cut_back.x_left)
            
            elif cell.rib2 == self.rib:
                for panel in panels:
                    panel_cuts.add(panel.cut_front.x_right)
                    panel_cuts.add(panel.cut_back.x_right)
            
        return list(panel_cuts)



    def flatten(self, glider: Glider, add_rigidfoils_to_plot: bool=True) -> drawing.Part:
        self.plotpart = initialize_part_layer_strokes(
            drawing.Part(name=self.rib.name, material_code=str(self.rib.material))
        )
        prof2d = self.rib.get_hull()

        self.x_values = prof2d.x_values
        self.inner = prof2d.curve.scale(self.rib.chord)
        self.inner_normals = self.inner.normvectors()
        self.outer = self.inner.offset(self.rib.seam_allowance.si, simple=False)

        self._insert_attachment_points(glider)
        holes = self.insert_holes()

        for cell in glider.cells:
            if self.rib not in cell.ribs:
                continue

            if cell.rib1 == self.rib:
                for diagonal in cell.diagonals + cell.straps:
                    self.insert_drib_mark(diagonal.side1)

            elif cell.rib2 == self.rib:
                for diagonal in cell.diagonals + cell.straps:  # type: ignore
                    self.insert_drib_mark(diagonal.side2)

        for cut, is_entry in self.get_panel_cuts(glider):
            if -0.99 < cut.si and cut.si < 0.99:
                if is_entry:
                    self.insert_mark(cut, self.config.marks_panel_cut, force_layer_name=self.layer_name_outline)
                elif self.config.insert_design_cuts:
                    self.insert_mark(cut, self.config.marks_panel_cut)

        self._insert_text()
        self.insert_controlpoints()

        # insert cut
        envelope = self.draw_outline(glider)

        area = envelope.get_area()
        for hole in holes:
            area -= hole.get_area()

        self.weight = MaterialUsage().consume(self.rib.material, area)

        rigidfoils = self.draw_rigidfoils(glider)
        if add_rigidfoils_to_plot and rigidfoils:
            diff = max([_part_bbox(r)[1] for r in rigidfoils])
            min_x = _part_bbox(self.plotpart)[0]
            for rigidfoil in rigidfoils:
                moved = rigidfoil.move(openglider.rs.vector.Vector2D([-(diff-min_x+0.2), 0]))
                _merge_parts(self.plotpart, moved)

        return self.plotpart

    def _get_inner_outer(self, x_value: Percentage | float) -> tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]:
        ik = get_x_value(self.x_values, x_value)

        inner = self.inner.get(ik)
        outer = inner + self.inner_normals.get(ik) * self.rib.seam_allowance.si

        return inner, outer

    def insert_mark(
        self,
        position: float | Percentage,
        mark_function: Callable[[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D], dict[str, list[openglider.rs.vector.PolyLine2D]]],
        insert: bool=True,
        force_layer_name: str | None = None
        ) -> list[list[openglider.rs.vector.PolyLine2D]]:

        marks = []
        #if mark_function_func := getattr(mark_function, "__func__", None):
        #    mark_function = mark_function_func

        if mark_function is None:
            return

        inner, outer = self._get_inner_outer(position)

        for mark_layer, mark in mark_function(inner, outer).items():
            if insert:
                if force_layer_name:
                    mark_layer = force_layer_name
                add_lines(self.plotpart, mark_layer, mark)

            marks.append(mark)
        
        return marks

    def insert_controlpoints(self, controlpoints: list[float]=None) -> None:
        if controlpoints is None:
            controlpoints = list(self.config.get_controlpoints(self.rib))

        x_end = None
        if self.rib.trailing_edge_extra is not None and self.rib.trailing_edge_extra.si < 0:
            x_end = 1. + self.rib.convert_to_percentage(self.rib.trailing_edge_extra).si
        for x in controlpoints:
            if x_end is None or abs(x) <= x_end:
                self.insert_mark(x, self.config.marks_controlpoint)

    def get_point(self, x: float | Percentage, y: float=-1.) -> openglider.rs.vector.Vector2D:
        x = float(x)
        assert x >= 0
        p = self.rib.profile_2d.profilepoint(x, y)
        return p * self.rib.chord

    def insert_drib_mark(self, side: DiagonalSide) -> None:        
        if side.is_lower:
            return  # disabled
            self.insert_mark(side.start_x, self.config.marks_diagonal_front)
            self.insert_mark(side.end_x, self.config.marks_diagonal_back)
        elif side.is_upper:
            self.insert_mark(side.start_x(self.rib), self.config.marks_diagonal_back)
            self.insert_mark(side.end_x(self.rib), self.config.marks_diagonal_front)
        else:
            p1 = self.get_point(side.start_x(self.rib), side.height)
            p2 = self.get_point(side.end_x(self.rib), side.height)
            add_line(self.plotpart, self.layer_name_marks, openglider.rs.vector.PolyLine2D([p1, p2]))

    def insert_holes(self) -> list[openglider.rs.vector.PolyLine2D]:
        holes: list[drawing.Part] = []
        for hole in self.rib.holes:
            holes.append(hole.get_flattened(self.rib, num=200, layer_name=self.layer_name_crossports))
        
        curves: list[openglider.rs.vector.PolyLine2D] = []
        for plotpart in holes:
            _merge_parts(self.plotpart, plotpart)
            cut_layer = plotpart.layers.get(self.layer_name_crossports)
            if cut_layer is not None:
                curves += list(cut_layer.lines)

        return curves
    
    def get_outside_ik(self, x: float) -> float:
        ik_inner = get_x_value(self.x_values, x)
        inner_point = self.inner.get(ik_inner)
        outer_point = inner_point + self.inner_normals.get(ik_inner)#

        ik = self.outer.cut(inner_point, outer_point, min(ik_inner, len(self.outer)-1))
        return ik[0]

    def draw_outline(self, glider: Glider) -> openglider.rs.vector.PolyLine2D:
        """
        Cut trailing edge of outer rib
        """
        if self.rib.trailing_edge_extra is not None and self.rib.trailing_edge_extra.si < 0.:
            # cut trailing edge
            x = 1. + self.rib.convert_to_percentage(self.rib.trailing_edge_extra).si
            inner_start = get_x_value(self.x_values, -x)
            start = self.get_outside_ik(-x)

            inner_end = get_x_value(self.x_values, x)
            stop = self.get_outside_ik(x)

            trailing_edge = [
                self.inner.get(inner_end),
                self.inner.get(inner_start),
                self.outer.get(start)
            ]        
        else:
            inner_start = 0
            inner_end = len(self.inner)-1

            p1 = self.inner.nodes[0] + openglider.rs.vector.Vector2D([0, 1])
            p2 = self.inner.nodes[0] + openglider.rs.vector.Vector2D([0, -1])
            cuts = self.outer.cut(p1, p2)

            if len(cuts) != 2:
                raise Exception("could not cut airfoil TE")

            start = cuts[0][0]
            stop = cuts[1][0]

            if self.rib.trailing_edge_extra is not None:
                trailing_edge = [
                    self.outer.get(stop) + openglider.rs.vector.Vector2D([self.rib.trailing_edge_extra.si, 0]),
                    self.outer.get(start) + openglider.rs.vector.Vector2D([self.rib.trailing_edge_extra.si, 0]),
                    self.outer.get(start)
                    ]
            else:
                trailing_edge = [
                    self.outer.get(start)
                ]

        outline = None
        panel_free_zones = self.get_panel_free_zones(glider)

        seams: list[tuple[float, float]] = []
        seam_last_x = inner_start
        for x1, x2 in panel_free_zones:
            ik1 = get_x_value(self.x_values, x1)
            ik2 = get_x_value(self.x_values, x2)

            seams.append((seam_last_x, ik1))
            seam_last_x = ik2
        
        seams.append((seam_last_x, inner_end))

        inner = []

        for panel_start, panel_end in seams:
            inner.append(self.inner.get(panel_start, panel_end))

        if self.rib.sharknose and self.rib.sharknose.straight_reinforcement_allowance is not None:
            for x1, x2 in panel_free_zones[:]:
                if x1 < self.rib.sharknose.start and x2 > self.rib.sharknose.end:
                    continue
                x1 = max(self.rib.sharknose.start, x1)
                x2 = min(self.rib.sharknose.end, x2)
                
                sharknose_start = self.get_outside_ik(x1.si)
                sharknose_end = self.get_outside_ik(x2.si)

                line1 = self.outer.get(start, sharknose_start).nodes
                line2 = self.outer.get(sharknose_end, stop).nodes

                allowance_diff = self.rib.sharknose.straight_reinforcement_allowance - self.rib.seam_allowance
                outline_lst = line1[:]

                if allowance_diff > Length("0.1mm"): # TODO: what is a reasonable diff?
                    p1 = line1[-1]
                    p2 = line2[0]
                    
                    diff = p2 - p1
                    normal = openglider.rs.vector.Vector2D([diff[1], -diff[0]]).normalized()

                    outline_lst.append(p1 + normal * allowance_diff.si)
                    outline_lst.append(p2 + normal * allowance_diff.si)

                outline_lst += line2
                outline_lst += trailing_edge

                outline = openglider.rs.vector.PolyLine2D(outline_lst)
        
        if outline is None:
            outline = openglider.rs.vector.PolyLine2D(
                self.outer.get(start, stop).nodes + trailing_edge
            ).fix_errors()

        add_line(self.plotpart, self.layer_name_outline, outline)
        add_lines(self.plotpart, self.layer_name_sewing, inner)

        return outline

    def walk(self, x: float, amount: float) -> float:
        ik = get_x_value(self.x_values, x)

        ik_new = self.inner.walk(ik, amount)

        return self.inner.get(ik_new)[0]/self.rib.chord

    def _insert_attachment_points(self, glider: Glider) -> None:
        for attachment_point in self.rib.attachment_points:
            positions = attachment_point.get_x_values(self.rib)

            for position in positions:
                self.insert_mark(position, self.config.marks_attachment_point)

    def _insert_text(self) -> None:
        text = f"p{self.rib.name}"
        if self.config.rib_text_in_seam:
            inner, outer = self._get_inner_outer(self.config.rib_text_pos)
            diff = outer - inner

            p1 = inner + diff * 0.5
            p2 = p1 + openglider.rs.vector.Rotation2D(-math.pi/2).apply(diff)

            _text = Text(text, p1, p2, size=(outer-inner).length()*0.5, valign=0)
            #_text = Text(text, p1, p2, size=0.05)
        else:
            p1 = self.get_point(self.config.rib_text_pos, -1)
            p2 = self.get_point(self.config.rib_text_pos, 1)

            _text = Text(text, p1, p2, size=0.01, align="center")


        add_lines(self.plotpart, self.layer_name_text, _text.get_vectors())
    
    def draw_rigidfoils(self, glider: Glider) -> list[drawing.Part]:
        result = []

        # rigidfoils
        for i, rigid in enumerate(self.rib.get_rigidfoils()):
            plt = self.RigidFoilPlotFactory(rigidfoil=rigid, ribplot=self)
            result.append(plt.flatten(glider))

        return result


class SingleSkinRibPlot(RibPlot):
    skin_cut: Percentage | None = None

    def _get_inner_outer(self, x_value: Percentage | float) -> tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]:
        # TODO: shift when after the endpoint

        if self.skin_cut is None or x_value < self.skin_cut:
            return super()._get_inner_outer(x_value)
        else:
            hull = self.rib.get_hull()
            segments = hull.curve.get_segments()
            ik = hull.get_ik(x_value)

            segment = segments[min(int(ik), len(segments)-1)].normalized()
            normal = openglider.rs.vector.Rotation2D(math.pi/2).apply(segment)


            p1 = hull.curve.get(ik) * self.rib.chord
            p2 = p1 + normal * self.rib.seam_allowance.si
            return p1, p2
        
    def insert_controlpoints(self, controlpoints: list[float]=None) -> None:
        if self.skin_cut is not None:
            controlpoints = [x for x in self.config.get_controlpoints(self.rib) if x < self.skin_cut.si]

        return super().insert_controlpoints(controlpoints)

    def _get_singleskin_cut(self, glider: Glider) -> Percentage:
        if self.skin_cut is None:
            singleskin_cut = None

            for cell in glider.cells:
                # only a back cut can be a singleskin_cut
                # asserts there is only one removed singleskin Panel!
                # maybe asserts no singleskin rib on stabilo
                if cell.rib1 == self.rib:
                    for panel in cell.panels:
                        if panel.cut_back.cut_type == PANELCUT_TYPES.singleskin:
                            singleskin_cut = panel.cut_back.x_left
                            break
                if cell.rib2 == self.rib:
                    for panel in cell.panels:
                        if panel.cut_back.cut_type == PANELCUT_TYPES.singleskin:
                            singleskin_cut = panel.cut_back.x_right
                            break
            
            if singleskin_cut is None:
                raise ValueError(f"no singleskin cut found for rib: {self.rib.name}")

            self.skin_cut = singleskin_cut

        return self.skin_cut

    def flatten(self, glider: Glider, add_rigidfoils_to_plot: bool=True) -> drawing.Part:
        self._get_singleskin_cut(glider)
        return super().flatten(glider, add_rigidfoils_to_plot=add_rigidfoils_to_plot)

    def draw_outline(self, glider: Glider) -> openglider.rs.vector.PolyLine2D:
        """
        Cut trailing edge of outer rib
        """
        outer_rib = self.outer
        inner_rib = self.inner

        p1 = inner_rib.get(0) + openglider.rs.vector.Vector2D([0, 1])
        p2 = inner_rib.get(0) + openglider.rs.vector.Vector2D([0, -1])
        cuts = outer_rib.cut(p1, p2)

        start = cuts[0][0]

        contour = openglider.rs.vector.PolyLine2D([])

        # outer is going from the back back until the singleskin cut

        singleskin_cut_left = self._get_singleskin_cut(glider)
        single_skin_cut = self.rib.profile_2d(singleskin_cut_left)

        if self.rib.trailing_edge_extra is not None:
            buerzl = openglider.rs.vector.PolyLine2D([
                inner_rib.get(0),
                inner_rib.get(0) + openglider.rs.vector.Vector2D([self.rib.trailing_edge_extra.si, 0]),
                outer_rib.get(start) + openglider.rs.vector.Vector2D([self.rib.trailing_edge_extra.si, 0]),
                outer_rib.get(start)
                ])
        else:
            buerzl = openglider.rs.vector.PolyLine2D([
                inner_rib.get(0),
                outer_rib.get(start)
            ])
        contour += outer_rib.get(start, single_skin_cut)
        contour += inner_rib.get(single_skin_cut, len(inner_rib)-1)
        contour += buerzl

        add_line(self.plotpart, self.layer_name_outline, contour)
        add_line(self.plotpart, self.layer_name_sewing, self.inner)

        return contour
