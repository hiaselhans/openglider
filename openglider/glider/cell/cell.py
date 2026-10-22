from __future__ import annotations

import logging
import math
from openglider.airfoil import Profile3D, Profile2D
from typing import Any, Literal
from collections.abc import Sequence

import openglider.rs
from openglider.airfoil import Profile3D
from openglider.glider.ballooning.base import BallooningBase
from openglider.glider.cell.attachment_point import CellAttachmentPoint
from openglider.glider.cell.ballooning_modifier import BallooningModifier
from openglider.glider.cell.basic_cell import BasicCell
from openglider.glider.cell.diagonals import DiagonalRib, TensionStrap
from openglider.glider.cell.panel import PANELCUT_TYPES, Panel, PanelCut
from openglider.glider.cell.rigidfoil import EntryStrap, PanelRigidFoil
from openglider.glider.rib import MiniRib, Rib
from openglider.mesh import Mesh
from openglider.utils import consistent_value, linspace
from openglider.utils.cache import (HashedList, cached_function,
                                    cached_property, hash_list)
from openglider.utils.dataclass import BaseModel, Field
from openglider.vector.unit import Percentage

logger = logging.getLogger(__file__)


class FlattenedCell(BaseModel):
    inner: list[openglider.rs.vector.PolyLine2D]
    ballooned: tuple[openglider.rs.vector.PolyLine2D, openglider.rs.vector.PolyLine2D]

    def at_position(self, y: Percentage) -> openglider.rs.vector.PolyLine2D:
        if y.si == 0:
            return self.ballooned[0]
        elif y.si == 1:
            return self.ballooned[1]
        else:
            return self.ballooned[0].mix(self.ballooned[1], y.si)

class Cell(BaseModel):
    rib1: Rib
    rib2: Rib

    ballooning: BallooningBase
    ballooning_modifiers: list[BallooningModifier] = Field(default_factory=lambda: [])
    ballooning_reference: Literal["local", "cell"] = "local"

    panels: list[Panel] = Field(default_factory=lambda: [])
    diagonals: list[DiagonalRib] = Field(default_factory=lambda: [])
    straps: list[TensionStrap] = Field(default_factory=lambda: [])
    rigidfoils: list[PanelRigidFoil | EntryStrap] = Field(default_factory=lambda: [])
    attachment_points: list[CellAttachmentPoint] = Field(default_factory=lambda: [])
    miniribs: list[MiniRib] = Field(default_factory=lambda: [])

    flatten_from_midribs: bool = True
    name: str = "unnamed"

    def __json__(self) -> dict[str, object]:
        data = self.model_dump(exclude={"straps"})
        data["straps"] = self.straps
        return data
    
    def __hash__(self) -> int:
        return hash_list(self.rib1, self.rib2, *self.miniribs, *self.diagonals)

    def rename_panels(self, cell_no: int, seperate_upper_lower: bool=True) -> None:
        if seperate_upper_lower:
            upper = [panel for panel in self.panels if not panel.is_lower()]
            lower = [panel for panel in self.panels if panel.is_lower()]
            def sort_func(panel: Panel) -> float:
                return abs(panel.mean_x())
            upper.sort(key=sort_func)
            lower.sort(key=sort_func)

            for panel_no, panel in enumerate(upper):
                panel.name = f"{cell_no}pu{panel_no+1}"
            for panel_no, panel in enumerate(lower):
                panel.name = f"{cell_no}pl{panel_no+1}"

        else:
            self.panels.sort(key=lambda panel: panel.mean_x())
            for panel_no, panel in enumerate(self.panels):
                panel.name = f"{cell_no}p{panel_no+1}"
    
    def rename_diagonals(self, diagonals: Sequence[DiagonalRib | TensionStrap], cell_no: int, naming_scheme: str) -> None:
        upper: list[DiagonalRib | TensionStrap] = []
        lower: list[DiagonalRib | TensionStrap] = []

        for diagonal in diagonals:
            if diagonal.get_average_x() > 0:
                lower.append(diagonal)
            else:
                upper.append(diagonal)
        
        lower.sort(key=lambda d: d.get_average_x())
        upper.sort(key=lambda d: -d.get_average_x())

        for i, d in enumerate(lower):
            d.name = naming_scheme.format(cell=self, cell_no=cell_no, diagonal=d, diagonal_no=i+1, side="l")

        for i, d in enumerate(upper):
            d.name = naming_scheme.format(cell=self, cell_no=cell_no, diagonal=d, diagonal_no=i+1, side="u")



    def rename_parts(self, cell_no: int, seperate_upper_lower: bool=False) -> None:
        self.rename_diagonals(self.diagonals, cell_no, "{cell.name}d{diagonal_no}")
        self.rename_diagonals(self.straps, cell_no, "{cell.name}s{side}{diagonal_no}")

        for minirib_no, minirib in enumerate(self.miniribs):
            minirib.name = f"{self.name}mr{minirib_no+1}"

        self.rename_panels(cell_no, seperate_upper_lower=seperate_upper_lower)

    @cached_property('prof1', 'prof2')
    def width(self) -> float:
        # get the distance between the two profiles
        # project the base point of prof2 on the line of prof1

        diff = self.rib2.pos - self.rib1.pos
        rib1_chord_line = self.rib1.rotation_matrix.apply(openglider.rs.vector.Vector2D([1, 0]))

        return diff.cross(rib1_chord_line).length()

    @cached_property('rib1', 'rib2', 'ballooning_phi')
    def basic_cell(self) -> BasicCell:
        profile1 = self.rib1.profile_3d
        profile2 = self.rib2.profile_3d

        profile_numpoints = self.rib1.profile_2d.numpoints
        profile_x_values = self.rib1.profile_2d.x_values

        if self.rib2.profile_2d.numpoints != profile_numpoints:
            raise ValueError(f"numpoints not matching {self.name}: {profile_numpoints}, {self.rib2.profile_2d.numpoints}")

        if len(profile1) != profile_numpoints:
            profile1 = self.rib1.get_profile_3d(x_values=profile_x_values)
        if len(profile2) != profile_numpoints:
            profile2 = self.rib2.get_profile_3d(x_values=profile_x_values)
        
        return BasicCell(prof1=profile1, prof2=profile2, ballooning_phi=list(self.ballooning_phi))

    def get_normvector(self) -> openglider.rs.vector.Vector3D:
        p1 = self.rib1.point(-1)
        p2 = self.rib2.point(0)

        p4 = self.rib1.point(0)
        p3 = self.rib2.point(-1)

        return (p1-p2).cross(p3-p4).normalized()

    @cached_property('miniribs', 'rib1', 'rib2')
    def rib_profiles_3d(self) -> list[Profile3D]:
        """
        Get all the ribs 3d-profiles, including miniribs
        """
        profiles = [self.rib1.profile_3d]
        profiles += [self._make_profile3d_from_minirib(mrib) for mrib in self.miniribs]
        profiles += [self.rib2.profile_3d]

        return profiles

    def get_connected_panels(self, skip: PANELCUT_TYPES | None=None) -> list[Panel]:
        panels: list[Panel] = []
        self.panels.sort(key=lambda panel: panel.mean_x())

        p0 = self.panels[0]
        for p in self.panels[1:]:
            if p.cut_front.cut_type != skip and  p.cut_front == p0.cut_back:
                p0 = Panel(p0.cut_front, p.cut_back, material=p0.material)
            else:
                panels.append(p0)
                p0 = p

        panels.append(p0)
        return panels

    def _make_profile3d_from_minirib(self, minirib: MiniRib) -> Profile3D:
        # self.basic_cell.prof1 = self.prof1
        # self.basic_cell.prof2 = self.prof2
        shape_with_ballooning = self.basic_cell.midrib(minirib.yvalue, ballooning=True, arc_argument=True).curve.nodes
        shape_without_ballooning = self.basic_cell.midrib(minirib.yvalue, ballooning=False).curve.nodes
        points: list[openglider.rs.vector.Vector3D] = []
        for xval, with_bal, without_bal in zip(
                self.x_values, shape_with_ballooning, shape_without_ballooning):
            fakt = minirib.get_multiplier(xval)  # factor ballooned/unb. (0-1)
            point = without_bal + (with_bal - without_bal) * fakt
            points.append(point)
        return Profile3D(curve=openglider.rs.vector.PolyLine3D(points), x_values=self.x_values)

    @cached_property('rib_profiles_3d')
    def _child_cells(self) -> list[BasicCell]:
        """
        get all the sub-cells within the current cell,
        (separated by miniribs)
        """
        # TODO: test / fix
        child_cells: list[BasicCell] = []
        
        for child_no in range(len(self.rib_profiles_3d)-1):
            leftrib = self.rib_profiles_3d[child_no]
            rightrib = self.rib_profiles_3d[child_no+1]
            child_cells.append(BasicCell(
                prof1=leftrib,
                prof2=rightrib,
                ballooning_phi=[],
                name=f"{self.name}_{child_no}"
            ))
        
        if not self.miniribs:
            return child_cells
        
        ballooning_angles = self.basic_cell.ballooning_phi

        for index, xvalue in enumerate(self.x_values):
            phi_values = [0.]
            for midrib in self.miniribs:
                phi = ballooning_angles[index] + math.asin((2 * midrib.yvalue - 1) * math.sin(ballooning_angles[index]))
                phi_values.append(phi)
            phi_values.append(2*ballooning_angles[index])

            left_point = self.rib1.profile_3d.curve.nodes[index]
            right_point = self.rib2.profile_3d.curve.nodes[index]

            phi_max = max(phi_values)


            if abs(xvalue) > 1.:
                if abs(xvalue) > 1. + 1e-5:
                    raise Exception(f"invalid xvalue: {xvalue}")
                xvalue = math.copysign(1., xvalue)

            ballooning_amount = self.ballooning_modified[xvalue]

            bow_length = (1.+ballooning_amount) * (right_point - left_point).length()  # L

            for child_no, child_cell in enumerate(child_cells):
                if ballooning_amount > 1e-8:
                    phi2= (phi_values[child_no+1] - phi_values[child_no]) / phi_max
                    length_bow_part = bow_length * phi2
                    lnew = (child_cell.prof1.curve.nodes[index] - child_cell.prof2.curve.nodes[index]).length()
                    
                    ballooning_new = (length_bow_part/lnew) - 1

                    if ballooning_new < 0:
                        logger.error(f"invalid ballooning for subcell: {self.name} / {child_no}")
                        ballooning_new = 0

                    child_cell.ballooning_phi.append(BallooningBase.arcsinc(1/(1+ballooning_new)))  # B/L NEW 1 / (bl * l / lnew)
                else:
                    child_cell.ballooning_phi.append(0.)
        return child_cells

    @property
    def ribs(self) -> list[Rib]:
        return [self.rib1, self.rib2]

    @property
    def _yvalues(self) -> list[float]:
        return [0.] + [mrib.yvalue for mrib in self.miniribs] + [1.]

    @property
    def x_values(self) -> list[float]:
        for i, (x1, x2) in enumerate(zip(self.prof1.x_values, self.prof2.x_values)):
            if (x2 - x1) > 1e-5:
                raise ValueError(f"Invalid x values at ({i}/{len(self.prof1.x_values)}): {x1, x2}")
            
        return self.prof1.x_values

    @property
    def prof1(self) -> Profile3D:
        return self.rib1.profile_3d

    @property
    def prof2(self) -> Profile3D:
        return self.rib2.profile_3d

    def point(self, y: float=0, i: int=0, k: float=0.) -> openglider.rs.vector.Vector3D:
        return self.midrib(y).get(i+k)

    @cached_function("self")
    def midrib(self, y: float, ballooning: bool=True, arc_argument: bool=True, close_trailing_edge: bool=False) -> Profile3D:
        kwargs = {
            "ballooning": ballooning,
            "arc_argument": arc_argument,
            "close_trailing_edge": close_trailing_edge
        }
        if len(self._child_cells) == 1:
            return self.basic_cell.midrib(y, **kwargs)
        if ballooning:
            i = 0
            while self._yvalues[i + 1] < y:
                i += 1
            cell = self._child_cells[i]
            y_new = (y - self._yvalues[i]) / (self._yvalues[i + 1] - self._yvalues[i])
            return cell.midrib(y_new, **kwargs)
        else:
            return self.basic_cell.midrib(y, ballooning=False)

    def get_midribs(self, numribs: int) -> list[Profile3D]:
        y_values = linspace(0, 1, numribs)
        return [self.midrib(y) for y in y_values]
    
    @cached_property('ballooning', 'rib1.profile_2d.x_values', 'rib2.profile_2d.x_values', 'panels')
    def ballooning_modified(self) -> BallooningBase:
        if not len(self.ballooning_modifiers):
            return self.ballooning
        
        ballooning = self.ballooning
        for modifier in self.ballooning_modifiers:
            ballooning = modifier.apply(ballooning, self)
        
        return ballooning

    @cached_property('ballooning_modified', 'rib1.profile_2d.x_values', 'rib2.profile_2d.x_values')
    def ballooning_phi(self) -> HashedList[float]:
        # get ballooning arc angles for each x value of the profiles

        rib1 = self.rib1
        rib2 = self.rib2
        ballooning_modified = self.ballooning_modified
        x_values = rib1.profile_2d.x_values

        balloon = [0.0] * len(x_values)
        for index, x in enumerate(x_values):
            balloon[index] = max(0.0, ballooning_modified[max(-1.0, min(1.0, x))])

        if self.ballooning_reference == "cell":
            rib1_nodes = rib1.profile_3d.curve.nodes
            rib2_nodes = rib2.profile_3d.curve.nodes
            width = self.width

            sinc = []
            for p1, p2, bal in zip(rib1_nodes, rib2_nodes, balloon):
                length = (p1 - p2).length()
                sinc.append(length / (length + width * bal))
        else:
            sinc = [1.0 / (1.0 + bal) for bal in balloon]
        return HashedList([BallooningBase.arcsinc(x) if x < 1. else 0. for x in sinc])
    
    @cached_property('ballooning', '_child_cells')
    def ballooning_tension_factors(self) -> list[float]:
        if len(self._child_cells) <= 1:
            return self.basic_cell.ballooning_tension_factors
        
        child_factors = [cell.ballooning_tension_factors for cell in self._child_cells]

        factors: list[float] = []

        prof1 = self.prof1.curve
        prof2 = self.prof2.curve

        for i in range(len(prof1.nodes)):
            tension = 0.
            diff = (prof1.nodes[i] - prof2.nodes[i]).normalized()

            for cell, cell_factors in zip(self._child_cells, child_factors):
                diff_child = (cell.prof1.curve.nodes[i] - cell.prof2.curve.nodes[i])
                cos_psi = abs(diff.dot(diff_child.normalized()))
                _tension = cell_factors[i]

                if cos_psi > 1e-5 and cos_psi < 1:
                    _tension = cell_factors[i]*cos_psi - math.sqrt(1-cos_psi**2)*diff_child.length()/2

                tension = max(tension, _tension)
            
            factors.append(tension)
        
        return factors


    @property
    def span(self) -> float:
        return ((self.rib1.pos - self.rib2.pos) * openglider.rs.vector.Vector3D([0, 1, 1])).length()

    @property
    def area(self) -> float:
        p1_1 = self.rib1.align(openglider.rs.vector.Vector2D([0, 0]))
        p1_2 = self.rib1.align(openglider.rs.vector.Vector2D([1, 0]))
        p2_1 = self.rib2.align(openglider.rs.vector.Vector2D([0, 0]))
        p2_2 = self.rib2.align(openglider.rs.vector.Vector2D([1, 0]))

        return 0.5 * ((p1_2 - p1_1).cross(p2_1 - p1_1).length() + (p2_2-p2_1).cross(p2_2-p1_2).length())

    @property
    def projected_area(self) -> float:
        """ return the z component of the crossproduct
            of the cell diagonals"""
        p1_1 = self.rib1.align(openglider.rs.vector.Vector2D([0, 0]))
        p1_2 = self.rib1.align(openglider.rs.vector.Vector2D([1, 0]))
        p2_1 = self.rib2.align(openglider.rs.vector.Vector2D([0, 0]))
        p2_2 = self.rib2.align(openglider.rs.vector.Vector2D([1, 0]))

        return -0.5 * (p2_1-p1_2).cross(p2_2-p1_1)[2]

    @property
    def centroid(self) -> openglider.rs.vector.Vector3D:
        p1_1 = self.rib1.align(openglider.rs.vector.Vector2D([0, 0]))
        p1_2 = self.rib1.align(openglider.rs.vector.Vector2D([1, 0]))
        p2_1 = self.rib2.align(openglider.rs.vector.Vector2D([0, 0]))
        p2_2 = self.rib2.align(openglider.rs.vector.Vector2D([1, 0]))

        centroid = (p1_1 + p1_2 + p2_1 + p2_2) / 4
        return centroid

    @property
    def aspect_ratio(self) -> float:
        return self.span ** 2 / self.area

    def mirror(self, mirror_ribs: bool=True) -> None:
        self.rib2, self.rib1 = self.rib1, self.rib2

        if mirror_ribs:
            for rib in self.ribs:
                rib.mirror()

        for diagonal in self.diagonals:
            diagonal.mirror()

        for strap in self.straps:
            strap.mirror()

        cuts: list[PanelCut] = []
        for panel in self.panels:
            if panel.cut_front not in cuts:
                cuts.append(panel.cut_front)
            if panel.cut_back not in cuts:
                cuts.append(panel.cut_back)
        
        for cut in cuts:
            cut.mirror()

    def mean_airfoil(self, num_midribs: int=8) -> Profile2D:
        mean_rib = self.midrib(0).flatten().normalized()

        for i in range(1, num_midribs):
            y = i/(num_midribs-1)
            mean_rib += self.midrib(y).flatten().normalized()
        return mean_rib * (1. / num_midribs)

    def get_mesh_grid(self, numribs: int=0, half_cell: bool=False) -> list[list[openglider.rs.vector.Vector3D]]:
        """
        Get Cell-grid
        :param numribs: number of miniribs to calculate
        :return: grid
        """
        numribs += 1

        grid: list[list[openglider.rs.vector.Vector3D]] = []
        rib_indices = range(numribs + 1)
        if half_cell:
            rib_indices = rib_indices[(numribs) // 2:]
        for rib_no in rib_indices:
            y = rib_no / max(numribs, 1)
            rib = self.midrib(y).curve.nodes
            grid.append(rib[:-1])
        return grid

    def get_mesh(self, numribs: int=0, half_cell: bool=False) -> Mesh:
        """
        Get Cell-mesh
        :param numribs: number of miniribs to calculate
        :return: mesh
        """

        grid = self.get_mesh_grid(numribs=numribs, half_cell=half_cell)

        nodes: list[openglider.rs.vector.Vector3D] = []
        quads: list[tuple[tuple[int, int, int, int], dict[str, Any]]] = []

        index_by_point_id: dict[int, int] = {}

        def point_index(point: openglider.rs.vector.Vector3D) -> int:
            point_id = id(point)
            if point_id in index_by_point_id:
                return index_by_point_id[point_id]
            index = len(nodes)
            index_by_point_id[point_id] = index
            nodes.append(point)
            return index

        for rib_left, rib_right in zip(grid[:-1], grid[1:]):
            numpoints = len(rib_left)
            for i in range(numpoints):
                i_next = (i+1)%numpoints
                quads.append((
                    (
                        point_index(rib_left[i]),
                        point_index(rib_right[i]),
                        point_index(rib_right[i_next]),
                        point_index(rib_left[i_next]),
                    ),
                    {},
                ))

        return Mesh.from_indexed(nodes, {"hull": quads})

    @cached_function("self")
    def get_flattened_cell(self, numribs: int=50, num_inner: int | None=None) -> FlattenedCell:
        if self.flatten_from_midribs:
            midribs = self.get_midribs(numribs)
            inner, ballooned = openglider.rs.flatten_midribs(
                [rib.curve for rib in midribs],
                num_inner=num_inner,
            )
        else:
            ballooning_modified = self.ballooning_modified
            x_values = self.rib1.profile_2d.x_values
            correction = []

            for x in x_values:
                x_normalized = max(0.0, ballooning_modified[max(-1.0, min(1.0, x))])
                correction.append(x_normalized)

            ballooned = openglider.rs.flatten_strip(
                left=self.rib1.get_profile_3d().curve,
                right=self.rib2.get_profile_3d().curve,
                correction=correction
            )

            y_values = linspace(0, 1, numribs)
            inner: list[openglider.rs.vector.PolyLine2D] = []

            # insert mid-points
            diff = ballooned[1].sub(ballooned[0])
            for y in y_values:
                inner.append(
                    ballooned[0].add(diff.scale(y))
                )

        return FlattenedCell(
            inner=inner,
            ballooned=ballooned
        )
    
    def calculate_3d_shaping(self, panels: list[Panel] | None=None, numribs: int=10) -> None:
        if panels is None:
            panels = self.panels

        flat = self.get_flattened_cell(numribs)

        cuts_3d: dict[int, list[float]] = {}

        def add_amount(cut: PanelCut, amount: list[float]) -> None:
            cut_key = cut.__hash__()

            for key in cuts_3d:
                if key == cut_key:
                    old = cuts_3d[key]

                    cuts_3d[key] = [(x1+x2)/2 for x1, x2 in zip(old, amount)]
                    return

            cuts_3d[cut_key] = amount

        def get_amount(cut: PanelCut) -> list[float]:
            cut_key = cut.__hash__()
            data = cuts_3d[cut_key]
            # TODO: Investigate
            return [max(0, x) for x in data]

        midribs = self.get_midribs(len(flat.inner))

        for panel in panels:
            amount_front, amount_back = panel.integrate_3d_shaping(self, flat.inner, midribs)

            add_amount(panel.cut_front, amount_front)
            add_amount(panel.cut_back, amount_back)

        cut_3d_types = [PANELCUT_TYPES.cut_3d]
        for panel in panels:
            if panel.cut_front.cut_type in cut_3d_types:
                panel.cut_front.cut_3d_amount = get_amount(panel.cut_front)
            else:
                panel.cut_front.cut_3d_amount = [0] * (numribs+2)
            
            if panel.cut_back.cut_type in cut_3d_types:
                panel.cut_back.cut_3d_amount = get_amount(panel.cut_back)
            else:
                panel.cut_back.cut_3d_amount = [0] * (numribs+2)
