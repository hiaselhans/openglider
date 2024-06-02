from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
import euklid
import logging

import pyfoil

import openglider.airfoil

from openglider.airfoil import Profile3D
from openglider.utils.dataclass import dataclass, Field
from openglider.mesh import Mesh, triangulate
from openglider.vector.unit import Length, Percentage

if TYPE_CHECKING:
    from openglider.glider.cell import Cell
    from openglider.glider.cell.panel import Panel

logger = logging.getLogger(__name__)

@dataclass
class MiniRib:
    yvalue: float
    front_cut: float
    back_cut: float | None=None
    chord: float = 0.3
    name: str="unnamed_minirib"
    material_code: str="unnamed_material"
    seam_allowance: Length = Length("10mm")
    function: euklid.vector.Interpolation = Field(default_factory=lambda: euklid.vector.Interpolation([]))
    hole_num: int=4
    hole_border_side :float=0.2
    hole_border_front_back: float=0.15


    class Config:
        arbitrary_types_allowed = True

    def __post_init__(self) -> None:
        p1_x = 2/3

        if self.function is None or len(self.function.nodes) == 0:
            if self.front_cut > 0:
                if self.back_cut is None:
                    back_cut = 1.
                else:
                    back_cut = self.back_cut
                points = [[self.front_cut, 1], [self.front_cut + (back_cut - self.front_cut) * (1-p1_x), 0]]  #
            else:
                points = [[0, 0]]

            if self.back_cut is not None and self.back_cut < 1.:
                points = points + [[self.front_cut + (self.back_cut-self.front_cut) * p1_x, 0], [self.back_cut, 1]]
            else:
                points = points + [[1., 0.]]

            curve = euklid.spline.BSplineCurve(points).get_sequence(100)
            self.function = euklid.vector.Interpolation(curve.nodes)

    def get_multiplier(self, x: float) -> float:
        within_back_cut = self.back_cut is None or abs(x) <= self.back_cut
        if self.front_cut <= abs(x) and within_back_cut:
            return min(1, max(0, self.function.get_value(abs(x))))
        else:
            return 1.
        
    def convert_to_percentage(self, value: Percentage | Length) -> Percentage:
        if isinstance(value, Percentage):
            return value
        
        return Percentage(value.si/self.chord)
    
    def get_offset_outline(self, cell:Cell, margin: Percentage | Length) -> pyfoil.Airfoil:
        profile_3d = self.get_profile_3d(cell)
        self.profile_2d = profile_3d.flatten()
        if margin == 0.:
            return self.profile_2d
        else:
            if isinstance(margin, Percentage):
                margin = margin/self.chord
            
            envelope = self.profile_2d.curve.offset(-margin.si, simple=False).nodes
            
            return pyfoil.Airfoil(envelope)
        
    def get_flattened(self, cell:Cell) -> euklid.vector.PolyLine2D:
        profile_3d = self.get_profile_3d(cell)
        return profile_3d.flatten().curve
   

    def get_profile_3d(self, cell: Cell) -> Profile3D:
        shape_with_bal = cell.basic_cell.midrib(self.yvalue, True, arc_argument=True).curve.nodes
        shape_wo_bal = cell.basic_cell.midrib(self.yvalue, False).curve.nodes

        points: list[euklid.vector.Vector3D] = []
        for xval, with_bal, without_bal in zip(
                cell.x_values, shape_with_bal, shape_wo_bal):
            factor = self.get_multiplier(xval)  # factor ballooned/unb. (0-1)
            point = without_bal + (with_bal - without_bal) * factor
            points.append(point)

        return Profile3D(curve=euklid.vector.PolyLine3D(points), x_values=cell.x_values)

    def _get_lengths(self, cell: Cell) -> tuple[float, float]:
        flattened_cell = cell.get_flattened_cell()
        left, right = flattened_cell.ballooned
        line = left.mix(right, self.yvalue)

        if self.back_cut is None:
            back_cut = 1.
        else:
            back_cut = self.back_cut

        ik_front_bot = (cell.rib1.profile_2d(self.front_cut) + cell.rib2.profile_2d(self.front_cut))/2
        ik_back_bot = (cell.rib1.profile_2d(back_cut) + cell.rib2.profile_2d(back_cut))/2


        ik_back_top = (cell.rib1.profile_2d(-self.front_cut) + cell.rib2.profile_2d(-self.front_cut))/2
        ik_front_top = (cell.rib1.profile_2d(-back_cut) + cell.rib2.profile_2d(-back_cut))/2

        return line.get(ik_front_top, ik_back_top).get_length(), line.get(ik_front_bot, ik_back_bot).get_length()

    def get_nodes(self, cell: Cell) -> tuple[euklid.vector.PolyLine2D, euklid.vector.PolyLine2D]:
        profile_3d = self.get_profile_3d(cell)
        profile_2d = profile_3d.flatten()
        contour = profile_2d.curve

        start_bottom = profile_2d.get_ik(self.front_cut*profile_2d.curve.nodes[0][0])
        end_bottom = profile_2d.get_ik(profile_2d.curve.nodes[0][0])
        start_top = profile_2d.get_ik(-self.front_cut*profile_2d.curve.nodes[0][0])
        end_top = profile_2d.get_ik(-profile_2d.curve.nodes[0][0])

        nodes_top = contour.get(end_top, start_top)
        nodes_bottom = contour.get(start_bottom, end_bottom)

        return nodes_top, nodes_bottom

    def rename_parts(self) -> None:
        for hole_no, hole in enumerate(self.holes):
            hole.name = self.hole_naming_scheme.format(hole_no, rib=self)


    def get_hull(self, cell: Cell) -> euklid.vector.PolyLine2D:
        """returns the outer contour of the normalized mesh in form
           of a Polyline"""
        
        nodes_top, nodes_bottom = self.get_nodes(cell)

        return euklid.vector.PolyLine2D(nodes_top.nodes+nodes_bottom.nodes)

    def align_all(self, cell: Cell, data: euklid.vector.PolyLine2D) -> euklid.vector.PolyLine3D:
        """align 2d coordinates to the 3d pos of the minirib"""
        projection_plane: euklid.plane.Plane = self.get_profile_3d(cell).projection_layer

        nodes_3d: list[euklid.vector.Vector3D] = []
        
        for p in data:
            nodes_3d.append(
                projection_plane.p0 + projection_plane.x_vector * p[0] + projection_plane.y_vector * p[1]
            )
        
        return euklid.vector.PolyLine3D(nodes_3d)


    def get_mesh(self, cell:Cell, filled: bool=True, max_area: float=None, hole_res: int = 40) -> Mesh:
        vertices = [(p[0], p[1]) for p in self.get_hull(cell).nodes[:-1]]
        boundary = [list(range(len(vertices))) + [0]]
        

        holes, hole_centers = self.get_holes(cell, hole_res)

        for curve in holes:
            start_index = len(vertices)
            hole_vertices = curve.tolist()[:-1]
            hole_indices = list(range(len(hole_vertices))) + [0]
            vertices+= hole_vertices
            boundary.append([start_index + i for i in hole_indices])



        if not filled:
            segments = []
            for lst in boundary:
                segments += triangulate.Triangulation.get_segments(lst)
            return Mesh.from_indexed(
                self.align_all(cell, euklid.vector.PolyLine2D(vertices)).nodes,
                {'minirib': [(segment, {}) for segment in segments]},
                {}
            )
        else:
            tri = triangulate.Triangulation(vertices, boundary, hole_centers)
            if max_area is not None:
                tri.meshpy_max_area = max_area
            
            tri.name = self.name
            mesh = tri.triangulate()

            points = self.align_all(cell, euklid.vector.PolyLine2D(mesh.points))
            boundaries = {self.name: list(range(len(points)))}


            minirib_mesh = Mesh.from_indexed(points.nodes, polygons={"miniribs": [(tri, {}) for tri in mesh.elements]} , boundaries=boundaries)
 

        return minirib_mesh
    

    def get_holes(self, cell: Cell, points: int=40) -> tuple[list[euklid.vector.PolyLine2D], list[euklid.vector.Vector2D]]:
        
        nodes_top, nodes_bottom = self.get_nodes(cell)

        len_top=nodes_top.get_length()
        len_bot=nodes_bottom.get_length()

        def get_point(x: float, y: float) -> euklid.vector.Vector2D:
            p1 = nodes_top.get(nodes_top.walk(0, len_top*x))
            p2 = nodes_bottom.get(nodes_bottom.walk(0, len_bot*(1-x)))

            return p1 + (p2-p1)*y
        
        holes = []
        centers = []
        
        if self.hole_num == 4:
            holes = [
                euklid.spline.BSplineCurve([
                    get_point(0.9,0.9),
                    get_point(0.85,0.9),
                    get_point(0.85,0.1),
                    get_point(0.95,0.1),
                    get_point(0.95,0.9),
                    get_point(0.9,0.9),   
                ]).get_sequence(points),
                
                euklid.spline.BSplineCurve([
                    get_point(0.75,0.9),
                    get_point(0.7,0.9),
                    get_point(0.7,0.1),
                    get_point(0.8,0.1),
                    get_point(0.8,0.9),
                    get_point(0.75,0.9),   
                ]).get_sequence(points),

                euklid.spline.BSplineCurve([
                    get_point(0.625,0.9),
                    get_point(0.575,0.9),
                    get_point(0.575,0.1),
                    get_point(0.65,0.1),
                    get_point(0.65,0.9),
                    get_point(0.625,0.9),   
                ]).get_sequence(points),

                euklid.spline.BSplineCurve([
                    get_point(0.5,0.9),
                    get_point(0.475,0.9),
                    get_point(0.475,0.1),
                    get_point(0.525,0.1),
                    get_point(0.525,0.9),
                    get_point(0.5,0.9),   
                ]).get_sequence(points),


                

            ]

            centers = [

                get_point(0.9, 0.5),
                get_point(0.75, 0.5),
                get_point(0.625, 0.5),
                get_point(0.5, 0.5),
            ]

        return holes, centers

