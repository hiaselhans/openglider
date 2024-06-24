from __future__ import annotations

from typing import TYPE_CHECKING
import euklid
import logging

from openglider.airfoil import Profile3D
from openglider.utils.dataclass import dataclass, Field

from openglider.mesh import Mesh, triangulate
from openglider.vector.unit import Length

if TYPE_CHECKING:
    from openglider.glider.cell import Cell

logger = logging.getLogger(__name__)

@dataclass
class MiniRib:
    yvalue: float
    front_cut: float
    back_cut: float | None=None
    name: str="unnamed_minirib"
    material_code: str="unnamed_material"
    seam_allowance: Length = Length("10mm")
    function: euklid.vector.Interpolation = Field(default_factory=lambda: euklid.vector.Interpolation([]))

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

    def get_mesh(self, cell: Cell, filled: bool=True, max_area: float=None) -> Mesh:
        vertices = [(p[0], p[1]) for p in self.get_hull(cell).nodes[:-1]]
        boundary = [list(range(len(vertices))) + [0]]
        hole_centers: list[tuple[float, float]] = []

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
            
            #for hole in self.holes:
            #    if hole_mesh := hole.get_mesh(self):
            #        rib_mesh += hole_mesh

        return minirib_mesh
    

    
