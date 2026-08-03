from __future__ import annotations

from enum import Enum
import logging
import math
from typing import TYPE_CHECKING, Any, ClassVar

import openglider.rs
import numpy as np
from openglider.airfoil.profile_3d import Profile3D
import openglider.mesh as mesh
from openglider.airfoil import get_x_value
from openglider.materials import Material, cloth
from openglider.utils.cache import cached_function, hash_list
from openglider.utils.dataclass import BaseModel, Field
from openglider.vector.drawing.part import PlotPart
from openglider.vector.unit import Length, Percentage
import openglider.glider.cell.panel.cuts as cuts

if TYPE_CHECKING:
    from openglider.glider.cell.cell import Cell, FlattenedCell


logger = logging.getLogger(__name__)

class PANELCUT_TYPES(Enum):
    folded = 1
    orthogonal = 2
    cut_3d = 3
    singleskin = 4
    parallel = 5
    round = 6


class PanelCut(BaseModel):
    cache_versioned: ClassVar[bool] = True
    x_left: Percentage
    x_right: Percentage
    cut_type: PANELCUT_TYPES
    seam_allowance: Length = Field(default_factory=lambda: Length(0))
    cut_3d_amount: list[float] = Field(default_factory=lambda: [0., 0.])
    cut_3d_sigma: float = 0.077
    x_center: Percentage | None = None

    def __json__(self) -> dict[str, Any]:
        return {
            "x_left": self.x_left,
            "x_right": self.x_right,
            "x_center": self.x_center,
            "cut_type": self.cut_type.name,
            "cut_3d_amount": self.cut_3d_amount,
            "seam_allowance": self.seam_allowance
        }

    @classmethod    
    def __from_json__(cls, **dct: Any) -> PanelCut:
        cut_type = getattr(PANELCUT_TYPES, dct["cut_type"])
        dct.update({
            "cut_type": cut_type
        })

        return cls(**dct)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PanelCut):
            return NotImplemented

        if self.x_left != other.x_left:
            return False
        
        if self.x_right != other.x_right:
            return False
        
        if self.cut_type != other.cut_type:
            return False
        
        if self.x_center != other.x_center:
            return False
        
        return True
    
    def mirror(self) -> None:
        self.x_left, self.x_right = self.x_right, self.x_left
    
    def get_x_values(self) -> list[Percentage]:
        values = [self.x_left, self.x_right]

        if self.x_center is not None:
            values.insert(1, self.x_center)
        
        return values
    
    def get_average_x(self) -> Percentage:
        values = self.get_x_values()
        
        return sum(values, start=Percentage(0))/len(values)
    
    def __hash__(self) -> int:
        return hash_list(self.x_left, self.x_right, self.cut_type)

    @cached_function("self")
    def get_ik_values(self, cell: Cell, x_values: list[float] | int, exact: bool=True) -> list[float]:
        if isinstance(x_values, int):
            x_values = [0] + [i/(x_values+1) for i in range(1, x_values+1)] + [1]

        x_values_left = cell.rib1.profile_2d.x_values
        x_values_right = cell.rib2.profile_2d.x_values

        ik_left = get_x_value(x_values_left, self.x_left)
        ik_right = get_x_value(x_values_right, self.x_right)

        points_2d = [
            openglider.rs.vector.Vector2D([0, self.x_left.si]),
            openglider.rs.vector.Vector2D([1, self.x_right.si])
        ]

        if self.x_center is not None:
            points_2d.insert(1, openglider.rs.vector.Vector2D([0.5, self.x_center.si]))
            bspline = openglider.rs.spline.BSplineCurve(points_2d).get_sequence(50)
            curve = openglider.rs.vector.Interpolation(bspline.nodes)
        else:
            curve = openglider.rs.vector.Interpolation(points_2d)
        
        ik_values: list[float] = []

        for x in x_values:
            if x == 0:
                ik_values.append(ik_left)
            elif x == 1:
                ik_values.append(ik_right)
            else:
                y = curve.get_value(x)

                _ik_left = get_x_value(x_values_left, y)
                _ik_right = get_x_value(x_values_right, y)
                ik_values.append(_ik_left + (_ik_right-_ik_left) * x)

        if not exact:
            return ik_values

        ik_values_new: list[float] = []
        flattened = cell.get_flattened_cell()  # noqa: F821
        inner = [flattened.at_position(Percentage(x)) for x in x_values]

        points_2d = [
            inner[0].get(ik_left),
            inner[-1].get(ik_right)
        ]

        if self.x_center is not None:
            p1 = inner[0].get(get_x_value(x_values_left, self.x_center.si))
            p2 = inner[-1].get(get_x_value(x_values_right, self.x_center.si))

            points_2d.insert(1, p1+(p2-p1)*0.5)
        
        if self.x_center is not None:
            curve_exact = openglider.rs.spline.BSplineCurve(points_2d).get_sequence(50)
        else:
            curve_exact = openglider.rs.vector.PolyLine2D(points_2d)

        for x, ik in zip(x_values, ik_values):
            line = flattened.at_position(Percentage(x))

            try:
                _ik, _ = line.cut(curve_exact, nearest_ik=ik)
                if abs(_ik-ik) < 20:
                    ik = _ik
            except RuntimeError:
                logger.error(f"no cut found for panel: {self} ({x}/{ik})")

            ik_values_new.append(ik)
        
        return ik_values_new


    @cached_function("self")
    def get_ik_interpolation(self, cell: Cell, numribs: int=5, exact: bool=True) -> openglider.rs.vector.Interpolation:
        ik_values = self.get_ik_values(cell, x_values=numribs, exact=exact)
        numpoints = len(ik_values)-1
        ik_interpolation = openglider.rs.vector.Interpolation(
            [[i/numpoints, x] for i, x in enumerate(ik_values)]
            )
        
        return ik_interpolation
    
    def get_curve_2d(self, cell: Cell, numribs: int=0, exact: bool=True) -> openglider.rs.vector.PolyLine2D:
        ik_values = self.get_ik_values(cell, x_values=numribs, exact=exact)

        ribs = cell.get_flattened_cell(num_inner=numribs+2).inner
        points_2d = [rib.get(ik) for rib, ik in zip(ribs, ik_values)]

        return openglider.rs.vector.PolyLine2D(points_2d)
    
    def get_curve_3d(self, cell: Cell, numribs: int=0, exact: bool=True) -> openglider.rs.vector.PolyLine3D:
        ik_values = self.get_ik_values(cell, numribs, exact)

        ribs = cell.get_midribs(numribs+2)
        points = [rib.get(ik) for rib, ik in zip(ribs, ik_values)]

        return openglider.rs.vector.PolyLine3D(points)

class FlattenedPanel(BaseModel):
    panel: Panel
    flattened_cell: FlattenedCell
    envelope: openglider.rs.vector.PolyLine2D
    cut_front: cuts.CutResult
    cut_back: cuts.CutResult
    x_distribution: list[float]

    def draw_straight_line(self, y: Percentage, start: Percentage, end: Percentage,) -> openglider.rs.vector.PolyLine2D | None:
        if start > max(self.panel.cut_back.x_left, self.panel.cut_back.x_right):
            return None
        if end < min(self.panel.cut_front.x_left, self.panel.cut_front.x_right):
            return None

        ik_min = self.cut_front.get_inner_index(y.si)
        ik_max = self.cut_back.get_inner_index(y.si)

        line = self.flattened_cell.at_position(y)

        ik_front = get_x_value(self.x_distribution, start)
        ik_back = get_x_value(self.x_distribution, end)

        ik_front = max(ik_front, ik_min)
        ik_back = min(ik_back, ik_max)

        if ik_front < ik_back:
            return line.get(ik_front, ik_back)
        
        return None

class Panel(BaseModel):
    """
    Glider cell-panel
    :param cut_front {'left': 0.06, 'right': 0.06, 'type': 'orthogonal'}
    """
    cache_versioned: ClassVar[bool] = True
    cut_front: PanelCut
    cut_back: PanelCut
    material: Material = cloth.get("porcher.skytex_32.white")
    name: str

    def __init__(self, cut_front: PanelCut, cut_back: PanelCut, material: Material | str | None=None, name: str="unnamed"):
        if isinstance(material, str):
            material = cloth.get(material)

        kwargs = {}
        if material is not None:
            kwargs["material"] = material
        
        # TODO: investigate type bug
        super().__init__(  # type: ignore
            cut_front=cut_front,
            cut_back=cut_back,
            name=name,
            **kwargs
        )

    def __json__(self) -> dict[str, Any]:
        return {'cut_front': self.cut_front,
                'cut_back': self.cut_back,
                "material": str(self.material),
                "name": self.name
                }

    @classmethod
    def dummy(cls) -> Panel:
        top = Percentage(-1)
        bottom = Percentage(1)
        return cls(
            PanelCut(
                x_left=top,
                x_right=top,
                cut_type=PANELCUT_TYPES.parallel,
                seam_allowance=Length("1cm")
                ),
            PanelCut(
                x_left=bottom,
                x_right=bottom,
                cut_type=PANELCUT_TYPES.parallel,
                seam_allowance=Length("1cm")
                )
        )
    
    def __hash__(self) -> int:
        return hash_list(self.cut_front.__hash__(), self.cut_back.__hash__())

    def mean_x(self) -> Percentage:
        """
        :return: center point of the panel as x-values
        """
        total = self.cut_front.x_left
        total += self.cut_front.x_right
        total += self.cut_back.x_left
        total += self.cut_back.x_right

        return total/4

    def __radd__(self, other: Panel) -> Panel | None:
        """needed for sum(panels)"""
        if not isinstance(other, Panel):
            return self
        
        return None

    def __add__(self, other: Panel) -> Panel | None:
        if self.cut_front == other.cut_back:
            return Panel(cut_front=other.cut_front, cut_back=self.cut_back, material=self.material)
        elif self.cut_back == other.cut_front:
            return Panel(cut_front=self.cut_front, cut_back=other.cut_back, material=self.material)
        else:
            return None

    def is_lower(self) -> bool:
        if (self.cut_front.x_left + self.cut_back.x_left + self.cut_front.x_right + self.cut_back.x_right) >=  1e-3:
            return True
        
        return False

    def get_3d(self, cell: Cell, numribs: int=0, midribs: list[Profile3D] | None=None) -> list[openglider.rs.vector.PolyLine3D]:
        """
        Get 3d-Panel
        :param glider: glider class
        :param numribs: number of miniribs to calculate
        :return: List of rib-pieces (Vectorlist)
        """
        xvalues = cell.rib1.profile_2d.x_values
        ribs: list[openglider.rs.vector.PolyLine3D] = []
        for i in range(numribs + 1):
            y = i / numribs

            if midribs is None:
                midrib = cell.midrib(y)
            else:
                midrib = midribs[i]

            x1 = self.cut_front.x_left + y * (self.cut_front.x_right -
                                               self.cut_front.x_left)
            front = get_x_value(xvalues, x1)

            x2 = self.cut_back.x_left + y * (self.cut_back.x_right -
                                              self.cut_back.x_left)
            back = get_x_value(xvalues, x2)
            ribs.append(midrib.get(front, back))
            # todo: return polygon-data
        return ribs

    def get_mesh(self, cell: Cell, numribs: int=0, exact: bool=False, tri: bool=False,
                 x_span_left: float | None = None, x_span_right: float | None = None,
                 chord_left: float | None = None, chord_right: float | None = None) -> mesh.Mesh:
        """
        Get Panel-mesh
        :param cell: the parent cell of the panel
        :param numribs: number of interpolation steps between ribs
        :param x_span_left: when provided (together with x_span_right and chord_left/right),
            store global (span_normalized, y_physical) UV coords instead of local (u, v).
            y_physical = chord_p * interpolated_chord  so it matches _get_panel_shape exactly.
        :return: mesh objects consisting of triangles and quadrangles
        """
        # TODO: doesn't work for numribs=0?
        
        xvalues = cell.rib1.profile_2d.x_values
        x_value_interpolation = openglider.rs.vector.Interpolation([[i, x] for i, x in enumerate(xvalues)])

        rib_iks: list[list[float]] = []
        nodes: list[openglider.rs.vector.Vector3D] = []
        node_attributes: list[dict[str, tuple[float, float]]] = []
        rib_node_indices: list[list[int]] = []

        ik_values = self.get_ik_values(cell, numribs, exact=exact)

        for rib_no in range(numribs + 2):
            y = rib_no / max(numribs+1, 1)
            span_x = x_span_left + y * (x_span_right - x_span_left) if x_span_left is not None else None
            chord_y = (chord_left + y * (chord_right - chord_left)
                       if chord_left is not None else None)

            front, back = ik_values[rib_no]

            midrib = cell.midrib(y)

            rib_iks.append(midrib.get_positions(front, back))

            ik_range = back - front
            for ik in rib_iks[-1]:
                if span_x is not None:
                    # Global glider coords: (span_normalized, y_physical)
                    # y_physical = chord_p * chord_y matches _get_panel_shape exactly.
                    chord_p = float(x_value_interpolation.get_value(ik))
                    y_phys = chord_p * chord_y if chord_y is not None else chord_p
                    node_attributes.append({"uv": (float(span_x), y_phys)})
                else:
                    if abs(ik_range) > 1e-9:
                        u = (ik - front) / ik_range
                    else:
                        u = 0.0
                    u = max(0.0, min(1.0, u))
                    node_attributes.append({"uv": (float(u), float(y))})

            i0 = len(nodes)
            rib_node_indices.append([i + i0 for i, _ in enumerate(rib_iks[-1])])

            nodes += list(midrib.get(front, back))

        polygons: list[tuple[tuple[int, ...], dict[str, Any]]] = []

        # helper functions
        def left_triangle(l_i: int, r_i: int) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
            return [((l_i+1, l_i, r_i), {})]

        def right_triangle(l_i: int, r_i: int) -> list[tuple[tuple[int, int, int], dict[str, Any]]]:
            return [((r_i+1, l_i, r_i), {})]

        def quad(l_i: int, r_i: int) -> list[tuple[tuple[int, ...], dict[str, Any]]]:
            if tri:
                return left_triangle(l_i, r_i) + right_triangle(l_i+1, r_i)
            else:
                return [((l_i+1, l_i, r_i, r_i+1), {})]

        for rib_no, _ in enumerate(rib_iks[:-1]):
            x = (2*rib_no+1) / (numribs+1) / 2
            indices_left = rib_node_indices[rib_no]
            indices_right = rib_node_indices[rib_no + 1]

            iks_left = rib_iks[rib_no]
            iks_right = rib_iks[rib_no + 1]
            l_i = r_i = 0            

            while l_i < len(indices_left)-1 or r_i < len(indices_right)-1:
                poly: list[tuple[tuple[int, ...], dict[str, Any]]] | None = None
                if l_i == len(indices_left) - 1:
                    poly = right_triangle(indices_left[l_i], indices_right[r_i])
                    r_i += 1

                elif r_i == len(indices_right) - 1:
                    poly = left_triangle(indices_left[l_i], indices_right[r_i])
                    l_i += 1

                elif abs(iks_left[l_i] - iks_right[r_i]) == 0:
                    poly = quad(indices_left[l_i], indices_right[r_i])
                    r_i += 1
                    l_i += 1

                elif iks_left[l_i] <= iks_right[r_i]:
                    poly = left_triangle(indices_left[l_i], indices_right[r_i])
                    l_i += 1

                elif iks_right[r_i] < iks_left[l_i]:
                    poly = right_triangle(indices_left[l_i], indices_right[r_i])
                    r_i += 1

                # TODO: improve logic for triangles
                iks = [iks_left[l_i], iks_right[r_i]]
                if l_i < len(iks_left) - 1:
                    iks.append(iks_left[l_i+1])
                if r_i < len(iks_right) - 1:
                    iks.append(iks_right[r_i+1])
                
                if poly is not None:
                    for p in poly:
                        p[1]["center"] = [x, x_value_interpolation.get_value(sum(iks)/len(iks))]

                    polygons += poly

        mesh_data = {
            f"panel_{self.material}#{self.material.color_code}": polygons,
        }

        return mesh.Mesh.from_indexed(nodes, mesh_data, name=self.name, node_attributes=node_attributes)

    def mirror(self) -> Panel:
        """
        mirrors the cuts of the panel
        """
        self.cut_front.mirror()
        self.cut_back.mirror()
        return self
    
    def snap(self, cell: Cell) -> None:
        """
        replaces panel x_valus with x_values stored in profile-2d-x-values
        """
        p_l = cell.rib1.profile_2d
        p_r = cell.rib2.profile_2d
        self.cut_back.x_left = Percentage(p_l.find_nearest_x_value(self.cut_back.x_left.si))
        self.cut_back.x_right = Percentage(p_r.find_nearest_x_value(self.cut_back.x_right.si))
        self.cut_front.x_left = Percentage(p_l.find_nearest_x_value(self.cut_front.x_left.si))
        self.cut_front.x_right = Percentage(p_r.find_nearest_x_value(self.cut_front.x_right.si))

    @cached_function("self")
    def get_ik_values(self, cell: Cell, numribs: int=0, exact: bool=True) -> list[tuple[float, float]]:
        """
        :param cell: the parent cell of the panel
        :param numribs: number of interpolation steps between ribs
        :return: [[front_ik_0, back_ik_0], ..[front_ik_n, back_ik_n]] with n is numribs + 1
        """
        ik_front = self.cut_front.get_ik_values(cell, x_values=numribs, exact=exact)
        ik_back = self.cut_back.get_ik_values(cell, x_values=numribs, exact=exact)

        return [(ik1, ik2) for ik1, ik2 in zip(ik_front, ik_back)]
        
    @cached_function("self")
    def get_ik_interpolation(self, cell: Cell, numribs: int=0, exact: bool=True) -> tuple[openglider.rs.vector.Interpolation, openglider.rs.vector.Interpolation]:
        i1 = self.cut_front.get_ik_interpolation(cell, numribs, exact)
        i2 = self.cut_back.get_ik_interpolation(cell, numribs, exact)

        return i1, i2

    def integrate_3d_shaping(self, cell: Cell, inner_2d: list[openglider.rs.vector.PolyLine2D], midribs: list[Profile3D] | None=None) -> tuple[list[float], list[float]]:
        """
        :param cell: the parent cell of the panel
        :param sigma: std-deviation parameter of gaussian distribution used to weight the length differences.
        :param inner_2d: list of 2D polylines (flat representation of the cell)s
        :param midribs: precomputed midribs, None by default
        :return: front, back (lists of lengths) with length equal to number of midribs
        """
        numribs = len(inner_2d) - 2
        if midribs is None or len(midribs) != len(inner_2d):
            ribs = cell.get_midribs(numribs+2)
        else:
            ribs = midribs

        positions = self.get_ik_values(cell, numribs, exact=True)

        front: list[float] = []
        back: list[float] = []


        for rib_no in range(numribs + 2):
            x1, x2 = positions[rib_no]
            rib_2d = inner_2d[rib_no].get(x1,x2)
            rib_3d = ribs[rib_no].get(x1, x2)

            lengthes_2d = rib_2d.get_segment_lengthes()
            lengthes_3d = rib_3d.get_segment_lengthes()

            amount_front = 0.
            # influence factor: e^-(x^2/(2*sigma^2))
            # -> sigma = einflussfaktor [m]
            # integral = sqrt(pi/2)*sigma * [ erf(x / (sqrt(2)*sigma) ) ]

            def integrate(lengths_2d: list[float], lengths_3d: list[float], sigma: float) -> float:
                amount = 0.
                distance = 0.

                for l2d, l3d in zip(lengths_2d, lengths_3d):
                    if l3d > 0:
                        factor = (l3d - l2d) / l3d
                        x = math.erf( (distance + l3d) / (sigma*math.sqrt(2))) - math.erf(distance / (sigma*math.sqrt(2)))

                        amount += factor * x
                    distance += l3d
            
                ff = math.sqrt(math.pi/2)*sigma

                return amount * ff
            
            cut_3d_type = PANELCUT_TYPES.cut_3d
            amount_back = amount_front = 0.

            if self.cut_back.cut_type == cut_3d_type:
                amount_back = integrate(lengthes_2d[::-1], lengthes_3d[::-1], self.cut_back.cut_3d_sigma)

            if self.cut_front.cut_type == cut_3d_type:
                amount_front = integrate(lengthes_2d, lengthes_3d, self.cut_front.cut_3d_sigma)

            total = 0.
            for l2d, l3d in zip(lengthes_2d, lengthes_3d):
                total += l3d - l2d

            cut_3d_type = PANELCUT_TYPES.cut_3d

            if abs(amount_front + amount_back) > abs(total):
                normalization = abs(total / (amount_front + amount_back))
                amount_front *= normalization
                amount_back *= normalization

            if rib_no == 0 or rib_no == numribs+1:
                amount_front = 0.
                amount_back = 0.
                
            front.append(amount_front)
            back.append(amount_back)

        return front, back
    
    @cached_function("cut_front", "cut_back")
    def get_flattened(self, cell: Cell, midribs: int, cut_types: dict[PANELCUT_TYPES, type[cuts.Cut]] | None = None) -> FlattenedPanel:
        plotpart = PlotPart(material_code=str(self.material), name=self.name)

        if cut_types is None:
            _cut_types: dict[PANELCUT_TYPES, type[cuts.Cut]] = {
                PANELCUT_TYPES.folded: cuts.SimpleCut,
                PANELCUT_TYPES.parallel: cuts.SimpleCut,
                PANELCUT_TYPES.orthogonal: cuts.SimpleCut,
                PANELCUT_TYPES.singleskin: cuts.SimpleCut,
                PANELCUT_TYPES.cut_3d: cuts.Cut3D,
                PANELCUT_TYPES.round: cuts.Cut3D
            }
        else:
            _cut_types = cut_types

        flattened = cell.get_flattened_cell(num_inner=midribs)

        ik_front = self.cut_front.get_ik_values(cell, x_values=midribs, exact=True)
        ik_back = self.cut_back.get_ik_values(cell, x_values=midribs, exact=True)

        allowance_front = -self.cut_front.seam_allowance
        allowance_back = self.cut_back.seam_allowance

        # cuts -> cut-line, index left, index right
        cut_front = _cut_types[self.cut_front.cut_type](amount=allowance_front)
        cut_back = _cut_types[self.cut_back.cut_type](amount=allowance_back)

        inner_front = [(line, ik) for line, ik in zip(flattened.inner, ik_front)]
        inner_back = [(line, ik) for line, ik in zip(flattened.inner, ik_back)]

        shape_3d_amount_front = [-x for x in self.cut_front.cut_3d_amount]
        shape_3d_amount_back = self.cut_back.cut_3d_amount

        # zero-out 3d-shaping if there is none
        if self.cut_front.cut_type != PANELCUT_TYPES.cut_3d:
            dist = np.linspace(shape_3d_amount_front[0], shape_3d_amount_front[-1], len(shape_3d_amount_front))
            shape_3d_amount_front = list(dist)

        if self.cut_back.cut_type != PANELCUT_TYPES.cut_3d:
            dist = np.linspace(shape_3d_amount_back[0], shape_3d_amount_back[-1], len(shape_3d_amount_back))
            shape_3d_amount_back = list(dist)

        left = inner_front[0][0].get(inner_front[0][1], inner_back[0][1])
        right = inner_front[-1][0].get(inner_front[-1][1], inner_back[-1][1])

        outer_left = left.offset(-cell.rib1.seam_allowance.si)
        outer_right = right.offset(cell.rib2.seam_allowance.si)

        cut_front_result = cut_front.apply(inner_front, outer_left, outer_right, shape_3d_amount_front)
        cut_back_result = cut_back.apply(inner_back, outer_left, outer_right, shape_3d_amount_back)

        panel_left: openglider.rs.vector.PolyLine2D | None = None
        if cut_front_result.index_left < cut_back_result.index_left:
            panel_left = outer_left.get(cut_front_result.index_left, cut_back_result.index_left).fix_errors()
        panel_back = cut_back_result.outline.copy()

        panel_right: openglider.rs.vector.PolyLine2D | None = None
        if cut_back_result.index_right > cut_front_result.index_right:
            panel_right = outer_right.get(cut_back_result.index_right, cut_front_result.index_right).fix_errors()
        panel_front = cut_front_result.outline.copy()

        panel_back = panel_back.get(len(panel_back)-1, 0)
        if panel_right:
            envelope_nodes = panel_right.reverse().nodes + panel_back.nodes
        else:
            envelope_nodes = panel_back.nodes[:]

        if panel_left:
            envelope_nodes += panel_left.reverse().nodes
        envelope_nodes += panel_front.nodes
        envelope_nodes.append(envelope_nodes[0])

        envelope = openglider.rs.vector.PolyLine2D(envelope_nodes)

        plotpart.layers["envelope"].append(envelope)

        return FlattenedPanel(
            panel=self,
            flattened_cell=flattened,
            envelope=envelope,
            cut_front=cut_front_result,
            cut_back=cut_back_result,
            x_distribution=cell.x_values
        )
