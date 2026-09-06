from __future__ import annotations
from typing import Any, TYPE_CHECKING, ClassVar, Self
import numpy as np
import logging

import openglider.rs
from openglider.airfoil import Profile2D

from openglider.airfoil import Profile3D
from openglider.glider.rib.attachment_point import AttachmentPoint
from openglider.glider.rib.crossports import RibHoleBase
from openglider.glider.rib.rigidfoils import RigidFoilBase
from openglider.materials.material import Material
from openglider.utils.cache import cached_function, cached_property
from openglider.mesh import Mesh, triangulate
from openglider.glider.rib.sharknose import Sharknose
from openglider.utils.dataclass import BaseModel, Field
from openglider.vector.unit import Angle, Length, Percentage


if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

class RibBase(BaseModel):
    """
    Openglider Rib Class: contains a airfoil, needs a startpoint, angle (arcwide), angle of attack,
        glide-wide rotation and glider ratio.
        optional: name, absolute aoa (bool), startposition
    """
    cache_versioned: ClassVar[bool] = False
    material: Material | None = None
    profile_2d: Profile2D
    pos: openglider.rs.vector.Vector3D

    name: str = "unnamed rib"

    @property
    def nose(self) -> openglider.rs.vector.Vector3D:
        raise NotImplementedError()

    def align_all(self, data: openglider.rs.vector.PolyLine2D, scale: bool=True) -> openglider.rs.vector.PolyLine3D:
        """align 2d coordinates to the 3d pos of the rib"""
        if not isinstance(data, openglider.rs.vector.PolyLine2D):
            data = openglider.rs.vector.PolyLine2D(data)

        if scale:
            return self.transformation.apply_polyline(data)
        else:
            return self.rotation_matrix.apply_polyline(data).move(self.nose)

    def align(self, point: openglider.rs.vector.Vector2D, scale: bool=True) -> openglider.rs.vector.Vector3D:
        if not isinstance(point, openglider.rs.vector.Vector2D):
            point = openglider.rs.vector.Vector2D(point)

        if scale:
            return self.transformation.apply(point)
        else:
            return self.rotation_matrix.apply(point) + self.nose

    def align_x(self, x_value: float) -> openglider.rs.vector.Vector3D:
        ik = self.profile_2d(x_value)
        return self.profile_3d[ik]
    
    def get_hull(self, normalize_x_values: bool = False) -> Profile2D:
        return self.profile_2d
    
    @cached_function('profile_2d', 'transformation')
    def get_profile_3d(self, x_values: list[float]=None) -> Profile3D:
        hull = self.get_hull(normalize_x_values=x_values is None)

        if x_values is not None:
            hull = hull.set_x_values(x_values)
        else:
            x_values = self.profile_2d.x_values
        
        return Profile3D(curve=self.align_all(hull.curve), x_values=x_values)

    @cached_property('profile_3d')
    def normvectors(self) -> list[openglider.rs.vector.Vector3D]:
        return [self.rotation_matrix.apply(p) for p in self.profile_2d.normvectors.nodes]
    
    @cached_property('profile_2d', 'transformation')
    def profile_3d(self) -> Profile3D:
        return self.get_profile_3d()
    
    @property
    def rotation_matrix(self) -> openglider.rs.vector.Transformation:
        raise NotImplementedError()
    
    @property
    def transformation(self) -> openglider.rs.vector.Transformation:
        raise NotImplementedError()
    
    def point(self, x_value: float | Percentage) -> openglider.rs.vector.Vector3D:
        return self.align(self.profile_2d.profilepoint(float(x_value)))
    

    def copy(self, *args: Any, **kwargs: Any) -> Self:
        new = super().copy(*args, **kwargs)
        try:
            new.name += "_copy"
        except TypeError:
            new.name = str(new.name) + "_copy"
        return new
    
    def get_projection(self, point: openglider.rs.vector.Vector3D) -> float:
        p1 = self.align(openglider.rs.vector.Vector2D([0,0]))
        p2 = self.align(openglider.rs.vector.Vector2D([1,0]))

        d1 = point - p1
        d2 = p2 - p1
        return d1.dot(d2) / d2.dot(d2)


class Rib(RibBase):
    chord: float = 2.
    startpos: float = 0.
    
    glide: float = 10.
    aoa_absolute: float = 0.
    arcang: float = 0.
    zrot: Angle | None = None
    xrot: Angle | None = None
    offset: list[Length | Percentage] | None = None

    seam_allowance: Length
    trailing_edge_extra: Length | None

    holes: list[RibHoleBase] = Field(default_factory=list)
    rigidfoils: list[RigidFoilBase] = Field(default_factory=list)
    attachment_points: list[AttachmentPoint] = Field(default_factory=list)
    sharknose: Sharknose | None = None

    hole_naming_scheme: ClassVar[str] = "{rib.name}h{}"
    rigid_naming_scheme: ClassVar[str] = "{rib.name}r{}"

    rotation_position: Percentage | None = None

    @property
    def nose(self) -> openglider.rs.vector.Vector3D:
        if self.rotation_position is not None:
            return self.pos + self.rotation_matrix.apply(openglider.rs.vector.Vector3D([-self.rotation_position.si * self.chord, 0, 0]))
        else:
            return self.pos

    def convert_to_percentage(self, value: Percentage | Length) -> Percentage:
        if isinstance(value, Percentage):
            return value
        
        return Percentage(value.si/self.chord)
    
    def convert_to_chordlength(self, value: Percentage | Length) -> Length:
        if isinstance(value, Length):
            return value
        
        return Length(value.si*self.chord)

    @property
    def aoa_relative(self) -> float:
        return self.aoa_absolute + self._aoa_diff(self.arcang, self.glide)
    
    @aoa_relative.setter
    def aoa_relative(self, aoa: float) -> None:
        self.set_aoa_relative(aoa)

    def set_aoa_relative(self, aoa: float) -> None:
        self.aoa_absolute = aoa - self._aoa_diff(self.arcang, self.glide)

    @cached_property('arcang', 'glide', 'zrot', 'xrot', 'aoa_absolute')
    def rotation_matrix(self) -> openglider.rs.vector.Transformation:  # type: ignore
        return rib_rotation(self.aoa_absolute, self.arcang, self.zrot, self.xrot)

    @cached_property('arcang', 'glide', 'zrot', 'xrot', 'aoa_absolute', 'chord', 'pos', 'offset', 'rotation_position')
    def transformation(self) -> openglider.rs.vector.Transformation:  # type: ignore
        if self.offset is None:
            offset = openglider.rs.vector.Vector3D([0, 0, 0])
        else:
            xoffset = self.convert_to_chordlength(self.offset[0]).si
            yoffset = self.convert_to_chordlength(self.offset[1]).si
            zoffset = self.convert_to_chordlength(self.offset[2]).si

            offset = openglider.rs.vector.Vector3D([xoffset, yoffset, zoffset])

        if self.rotation_position is not None:
            offset += openglider.rs.vector.Vector3D([-self.rotation_position.si * self.chord, 0, 0])
            #offset = openglider.rs.vector.Vector3D([0, 0.1, 0])

        return rib_transformation(self.aoa_absolute, self.arcang, self.zrot, self.xrot, self.chord, self.pos, offset)
    
    def rename_parts(self) -> None:
        for hole_no, hole in enumerate(self.holes):
            hole.name = self.hole_naming_scheme.format(hole_no, rib=self)

        for rigid_no, rigid in enumerate(self.rigidfoils):
            rigid.name = self.rigid_naming_scheme.format(rigid_no, rib=self)

    @staticmethod
    def _aoa_diff(arc_angle: float, glide: float) -> float:
        ##Formula for aoa rel/abs: ArcTan[Cos[alpha]/gleitzahl]-aoa[rad];
        return np.arctan(np.cos(arc_angle) / glide)

    def mirror(self) -> None:
        self.arcang *= -1.
        if self.xrot is not None:
            self.xrot *= -1.
        if self.zrot is not None:
            self.zrot = - self.zrot
        self.pos = self.pos * openglider.rs.vector.Vector3D([1, -1, 1])

    def is_closed(self) -> bool:
        return self.profile_2d.thickness < 0.01

    def get_hull(self, normalize_x_values: bool = False) -> Profile2D:
        """returns the outer contour of the normalized mesh in form
           of a Polyline"""
        result = self.profile_2d

        if self.sharknose is not None:
            result = self.sharknose.get_modified_airfoil(self)
            if normalize_x_values:
                result = result.set_x_values(self.profile_2d.x_values)
        
        return result
    
    def get_weight(self) -> float:
        if self.material is None:
            raise ValueError(f"Rib {self.name} has no material assigned")

        outline = self.get_hull().curve * self.chord
        crossports = [hole.get_flattened(self, layer_name="cuts") for hole in self.holes]

        area = outline.get_area() - sum([
            sum([line.get_area() for line in crossport.layers["cuts"].polylines]) for crossport in crossports
        ])

        return area * self.material.weight

    @property
    def normalized_normale(self) -> openglider.rs.vector.Vector3D:
        return self.rotation_matrix.apply(openglider.rs.vector.Vector3D([0., 0., 1.]))

    def get_mesh(self, hole_num: int=10, filled: bool=False, max_area: float=None) -> Mesh:
        if self.is_closed():
            # stabi
            # TODO: return line
            return Mesh.from_indexed([], {})

        outline = self.get_hull().curve
        hole_curves: list[openglider.rs.vector.PolyLine2D] = []
        if len(self.holes) > 0 and hole_num > 3:
            for hole in self.holes:
                curves = hole.get_curves(self, num=hole_num, scale=False)
                for curve in curves:
                    hole_curves.append(openglider.rs.vector.PolyLine2D(list(curve)[:-1]))

        if filled:
            tri = triangulate.Triangulation(outline, hole_curves)
            if max_area is not None:
                tri.max_area = max_area

            tri.name = self.name
            mesh = tri.triangulate()

            points = self.align_all(openglider.rs.vector.PolyLine2D(mesh.points))

            rib_mesh = Mesh.from_indexed(points.nodes, polygons={f"ribs#{self.material.color_code}": [(tri, {}) for tri in mesh.elements]})

            for hole in self.holes:
                if hole_mesh := hole.get_mesh(self):
                    rib_mesh += hole_mesh

            return rib_mesh

        else:
            vertices = [(p[0], p[1]) for p in outline.nodes[:-1]]
            boundary = [list(range(len(vertices))) + [0]]
            for curve in hole_curves:
                start_index = len(vertices)
                hole_vertices = [(p[0], p[1]) for p in curve.nodes]
                hole_indices = list(range(len(hole_vertices))) + [0]
                vertices += hole_vertices
                boundary.append([start_index + i for i in hole_indices])

            segments = []
            for lst in boundary:
                segments += triangulate.Triangulation.get_segments(lst)
            return Mesh.from_indexed(
                self.align_all(openglider.rs.vector.PolyLine2D(vertices)).nodes,
                {'rib': [(segment, {}) for segment in segments]},
                {}
                )

    @cached_function("self")
    def get_offset_outline(self, margin: Percentage | Length) -> Profile2D:
        if margin == 0.:
            return self.profile_2d
        else:
            if isinstance(margin, Percentage):
                margin = margin/self.chord
            
            envelope = self.profile_2d.curve.offset(-margin.si, simple=False).nodes
            
            return Profile2D(envelope)
        
    def get_rigidfoils(self) -> list[RigidFoilBase]:
        if self.sharknose is not None:
            result: list[RigidFoilBase] = []

            for rigidfoil in self.rigidfoils:
                rigidfoils_this = self.sharknose.update_rigidfoil(self, rigidfoil)
                if rigidfoils_this is not None:
                    result += rigidfoils_this
                else:
                    result.append(rigidfoil)
            for rigid_no, rigid in enumerate(result):
                rigid.name = self.rigid_naming_scheme.format(rigid_no, rib=self)
            
            return result

        return self.rigidfoils


def rib_rotation(aoa: float, arc: float, zrot: Angle | None, xrot: Angle | None) -> openglider.rs.vector.Transformation:
    # align upright -> profile is in x/z layer
    xrot_float = 0.
    if xrot is not None:
        xrot_float = xrot.si
    rot0 = openglider.rs.vector.Transformation.rotation(np.pi / 2 - xrot_float, [1, 0, 0])  # type: ignore

    # rotate aoa -> y (rot0.apply([0,0,1]))
    rot1 = openglider.rs.vector.Transformation.rotation(aoa, [0, 1, 0])  # type: ignore

    # rotate arc
    rot2 = openglider.rs.vector.Transformation.rotation(-arc, [1,0,0])  # type: ignore

    # Compose in the order the transforms are meant to be applied to vectors.
    result = rot0 * rot1 * rot2

    if zrot is not None:
        axis = (rot2 * rot1).apply(openglider.rs.vector.Vector3D([0,0,1]))
        rot3 = openglider.rs.vector.Transformation.rotation(zrot.si, axis)  # type: ignore
        return result * rot3
    
    return result


def rib_transformation(aoa: float, arc: float, zrot: Angle | None, xrot: Angle | None, scale: float, pos: openglider.rs.vector.Vector3D, offset: openglider.rs.vector.Vector3D) -> openglider.rs.vector.Transformation:
    scale_transform = openglider.rs.vector.Transformation.scale(scale)  # type: ignore
    #scale = Scale(scale)
    #move = Translation(pos)
    rot = rib_rotation(aoa, arc, zrot, xrot)  # type: ignore
    move = openglider.rs.vector.Transformation.translation(pos + rot.apply(offset))  # type: ignore
    return scale_transform * rot * move 
