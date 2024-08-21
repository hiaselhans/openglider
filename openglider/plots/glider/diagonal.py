import logging
import math

import euklid
from openglider.glider.cell import DiagonalRib
from openglider.glider.cell.cell import Cell
from openglider.plots.config import PatternConfig
from openglider.plots.usage_stats import MaterialUsage
from openglider.materials import cloth
from openglider.utils.config import Config
from openglider.vector.drawing import PlotPart
from openglider.vector.text import Text


logger = logging.getLogger(__name__)


class DribPlot:
    DefaultConf = PatternConfig
    front: euklid.vector.PolyLine2D | None = None
    back: euklid.vector.PolyLine2D | None = None

    def __init__(self, drib: DiagonalRib, cell: Cell, config: Config):
        # We are unwrapping the left side of the wing (flying direction).
        # rib1 -> inside -> left side
        # rib2 -> outside -> right side
        # seen from the bottom => mirror
        self.drib = drib
        self.cell = cell
        self.config = self.DefaultConf(config)

        inner, outer = self.drib.get_flattened(self.cell)
        front = back = None

        if self.drib.curve_factor is not None:
            if self.drib.num_folds > 0:
                raise ValueError()
            front, back = self.drib.get_side_curves(inner, outer, 100)

        center_left = inner.get(inner.walk(0, inner.get_length()/2))
        center_right = outer.get(outer.walk(0, outer.get_length()/2))
        self.angle = (center_right - center_left).angle() + math.pi

        if not self.drib.is_lower:
            self.angle += math.pi
        rotation_center = euklid.vector.Vector2D([0,0])
        self.inner_1 = inner.rotate(-self.angle, rotation_center)
        self.inner_2 = outer.rotate(-self.angle, rotation_center)

        self.outer_1 = self.inner_1.offset(-self.cell.rib1.seam_allowance.si)
        self.outer_2 = self.inner_2.offset(self.cell.rib2.seam_allowance.si)
        
        self.front = self.back = None
        if front is not None:
            self.front = euklid.vector.PolyLine2D(front).rotate(-self.angle, rotation_center)
        if back is not None:
            self.back = euklid.vector.PolyLine2D(back).rotate(-self.angle, rotation_center)


    def get_left(self, x: float) -> tuple[euklid.vector.Vector2D, euklid.vector.Vector2D]:
        return self.get_p1_p2(x, outer=False)

    def get_right(self, x: float) -> tuple[euklid.vector.Vector2D, euklid.vector.Vector2D]:
        return self.get_p1_p2(x, outer=True)

    def validate(self, x: float, right_side: bool=False) -> bool:
        if not right_side:
            side_obj = self.drib.side1
            rib = self.cell.rib1
        else:
            side_obj = self.drib.side2
            rib = self.cell.rib2

        if not side_obj.is_lower and not side_obj.is_upper:
            raise ValueError(f"invalid height: {side_obj.height}")

        boundary = [side_obj.start_x(rib), side_obj.end_x(rib)]
        boundary.sort()

        if not boundary[0] <= x <= boundary[1]:
            raise ValueError(f"not in boundaries: {x} ({boundary[0]} / {boundary[1]}")

        return True

    def get_p1_p2(self, x: float, outer: bool=False) -> tuple[euklid.vector.Vector2D, euklid.vector.Vector2D]:
        self.validate(x, right_side=outer)

        if not outer:
            side_obj = self.drib.side1
            rib = self.cell.rib1
            inner = self.inner_1
            outer = self.outer_1
        else:
            side_obj = self.drib.side2
            rib = self.cell.rib2
            inner = self.inner_2
            outer = self.outer_2

        x_range = [
            side_obj.start_x(rib),
            side_obj.end_x(rib)
        ]
        x_range.sort()
        
        
        if x_range[0] > x or x_range[1] < x:
            raise ValueError(f"invalid x: {x} ({side_obj.start_x} / {side_obj.end_x}")

        foil = rib.profile_2d

        if self.drib.is_lower:
            x1 = side_obj.start_x(rib)
        else:
            x1 = side_obj.end_x(rib)
        x2 = x

        ik_1 = foil(x1)
        ik_2 = foil(x2)
        length = foil.curve.get(ik_1, ik_2).get_length() * rib.chord

        ik_new = inner.walk(0, length)
        return inner.get(ik_new), outer.get(ik_new)
    
    def _insert_center_marks(self, plotpart: PlotPart) -> None:
        def insert_center_mark(inner: euklid.vector.PolyLine2D, outer: euklid.vector.PolyLine2D) -> None:
            ik = inner.walk(0, inner.get_length()/2)
            p1 = inner.get(ik)
            p2 = outer.get(ik)

            for layer_name, marks in self.config.marks_diagonal_center(p1, p2).items():
                plotpart.layers[layer_name] += marks

        # put center marks only on lower sides of diagonal ribs, always on straight ones
        if self.drib.side1.is_lower or self.drib.is_upper:
            insert_center_mark(self.inner_1, self.outer_2)

        if self.drib.side2.is_lower or self.drib.is_upper:
            insert_center_mark(self.inner_2, self.outer_1)
    
    def _insert_controlpoints(self, plotpart: PlotPart) -> None:
        x: float
        sides = (
            (False, self.cell.rib1),
            (True, self.cell.rib2)
        )

        for is_outer, rib in sides:
            for x in self.config.get_controlpoints(rib):
                try:
                    p1, p2 = self.get_p1_p2(x, is_outer)
                    for layer_name, marks in self.config.marks_controlpoint(p1, p2).items():
                        plotpart.layers[layer_name] += marks
                except ValueError:
                    continue

    def _insert_attachment_points(self, plotpart: PlotPart) -> None:
        def _add_mark(name: str, p1: euklid.vector.Vector2D, p2: euklid.vector.Vector2D, mirror: bool) -> None:
            for layer_name, marks in self.config.marks_attachment_point(p1, p2).items():
                plotpart.layers[layer_name] += marks
            left = p1 + (p1-p2)
            right = p1
            if mirror:
                right, left = left, right
            plotpart.layers["marks"] += Text(name, left, right).get_vectors()

        for attachment_point in self.cell.rib1.attachment_points:
            try:
                p1, p2 = self.get_left(attachment_point.rib_pos.si)
            except ValueError:
                continue
            _add_mark(attachment_point.name, p1, p2, True)

        for attachment_point in self.cell.rib2.attachment_points:
            try:
                p1, p2 = self.get_right(attachment_point.rib_pos.si)
            except ValueError:
                continue
            _add_mark(attachment_point.name, p1, p2, False)

    def _insert_text(self, plotpart: PlotPart, reverse: bool=False) -> None:
        if reverse:
            node_index = -1
        else:
            node_index = 0
        # text_p1 = left_out[0] + self.config.drib_text_position * (right_out[0] - left_out[0])
        val_valign = 0.6
        if self.drib.num_folds == 0:
            val_valign = -1

        if self.front is not None:
            front_curve = euklid.vector.PolyLine2D([self.inner_1.nodes[0]] + self.front.nodes + [self.inner_2.nodes[0]])
            ik0 = front_curve.walk(0, 0.01)
            ik1 = front_curve.walk(ik0, self.cell.rib1.seam_allowance.si * 0.6 * len(self.drib.name))
            p0 = front_curve.get(ik0)
            p1 = front_curve.get(ik1)
        else:
            p0 = self.inner_1.nodes[node_index]
            p1 = self.inner_2.nodes[node_index]

        plotpart.layers["text"] += Text(f" {self.drib.name} ",
                                        p0,
                                        p1,
                                        size=self.drib.fold_allowance * 0.6,
                                        height=0.6,
                                        valign=val_valign).get_vectors()

    def flatten(self) -> PlotPart:
        return self._flatten(self.drib.num_folds)

    def _flatten(self, num_folds: int) -> PlotPart:
        plotpart = PlotPart(material_code=self.drib.material_code, name=self.drib.name)

        if num_folds > 0:
            alw2 = self.drib.fold_allowance
            cut_front = self.config.cut_diagonal_fold(amount=alw2, num_folds=num_folds)
            cut_back = self.config.cut_diagonal_fold(amount=-alw2, num_folds=num_folds)
            
            cut_front_result = cut_front.apply([(self.inner_1, len(self.inner_1) - 1), (self.inner_2, len(self.inner_2) - 1)], self.outer_2, self.outer_1)
            cut_back_result = cut_back.apply([(self.inner_1, 0), (self.inner_2, 0)], self.outer_2, self.outer_1)
            
            plotpart.layers["cuts"] += [self.outer_2.get(cut_front_result.index_left, cut_back_result.index_left) +
                                        cut_back_result.outline +
                                        self.outer_1.get(cut_back_result.index_right, cut_front_result.index_right) +
                                        cut_front_result.outline.reverse()
            ]

            plotpart.layers["marks"].append(euklid.vector.PolyLine2D([self.inner_1.get(0), self.inner_2.get(0)]))
            plotpart.layers["marks"].append(euklid.vector.PolyLine2D([self.inner_1.get(len(self.inner_1) - 1), self.inner_2.get(len(self.inner_2) - 1)]))

        else:
            outer: list[euklid.vector.Vector2D] = self.outer_1.copy().nodes
            outer.append(self.inner_1.nodes[-1])

            if self.back:
                outer += self.back.nodes

            outer.append(self.inner_2.nodes[-1])
            outer += self.outer_2.reverse().nodes
            outer.append(self.inner_2.nodes[0])

            if self.front:
                outer += self.front.nodes[::-1]
            
            outer += [
                self.inner_1.nodes[0],
                self.outer_1.nodes[0]
            ]
            #outer += euklid.vector.PolyLine2D([self.left_out.get(p1)])
            plotpart.layers["cuts"].append(euklid.vector.PolyLine2D(outer))

        for curve in self.drib.get_holes(self.cell)[0]:
            curve = curve.rotate(-self.angle, euklid.vector.Vector2D([0,0]))
            plotpart.layers["cuts"].append(curve)

        plotpart.layers["stitches"] += [self.inner_1, self.inner_2]

        self._insert_attachment_points(plotpart)
        self._insert_center_marks(plotpart)
        self._insert_controlpoints(plotpart)

        # mirror -> watch from above
        #p1 = euklid.vector.Vector2D([0, 0])
        #p2 = euklid.vector.Vector2D([1, 0])
        #plotpart = plotpart.mirror(p1, p2)
        self._insert_text(plotpart)
        
        self.plotpart = plotpart
        return self.plotpart
    
    def get_material_usage(self) -> MaterialUsage:
        dwg = self.plotpart

        curves = dwg.layers["cuts"].polylines #was 'envelope' maybe a problem if numfolds > 0
        usage = MaterialUsage()
        material = cloth.get(dwg.material_code)

        if curves:
            area = curves[0].get_area()
        
            for curve in self.drib.get_holes(self.cell)[0]:
                area -= curve.get_area()
                
            usage.consume(material, area)

        return usage 


class StrapPlot(DribPlot):
    def flatten(self) -> PlotPart:
        self.drib.material_code
        self.drib.name
        return self._flatten(self.drib.num_folds)
