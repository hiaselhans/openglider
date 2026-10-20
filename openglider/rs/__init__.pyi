from . import drawing as drawing
from . import mesh as mesh
from . import plane as plane
from . import spline as spline
from . import svg_mod as svg_mod
from . import vector as vector
from . import voronoi as voronoi
from . import wgpu as wgpu
from .vector import PolyLine2D, PolyLine3D, Vector3D
from collections.abc import Sequence
def basic_cell_midrib(prof1: PolyLine3D, prof2: PolyLine3D, x_values_left: Sequence[float], x_values_right: Sequence[float], normvectors: PolyLine3D, ballooning_phi: Sequence[float], ballooning_radius: Sequence[float |None], y_value: float, ballooning: bool = True, arc_argument: bool = True, close_trailing_edge: bool = False) -> tuple[PolyLine3D, list[float]]: ...
def find_duplicates(points: Sequence[Vector3D], max_distance: float) -> list[tuple[int, int]]: ...
def flatten_midribs(midribs: Sequence[PolyLine3D], num_inner: int |None = None) -> tuple[list[PolyLine2D], tuple[PolyLine2D, PolyLine2D]]: ...

def flatten_strip(left: PolyLine3D, right: PolyLine3D, correction: Sequence[float] |None = None) -> tuple[PolyLine2D, PolyLine2D]:
    """
    Flatten two 3D polylines of equal length (`left` / `right`) into 2D.
    
    The segments `left[i-1] -> left[i]` and `right[i-1] -> right[i]` keep their 3D
    length, the angle between the chord (`right - left`) and the chord midpoint
    path is taken from 3D. The chord length `|left[i] - right[i]|` is scaled by
    `1 + correction[i]`.
    """

def triangle_area(a: float, b: float, c: float) -> float: ...
def version() -> str: ...
