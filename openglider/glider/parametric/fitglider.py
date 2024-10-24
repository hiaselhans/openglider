from __future__ import annotations

from typing import TYPE_CHECKING
import euklid
import numpy as np
from openglider.glider.parametric.arc import ArcCurve
from openglider.glider.parametric.shape import ParametricShape

if TYPE_CHECKING:
    from openglider.glider.glider import Glider
    from openglider.glider.parametric.glider import ParametricGlider

def fit_glider_3d(cls: type[ParametricGlider], glider: Glider, numpoints: int=3) -> ParametricGlider:
    """
    Create a parametric model from glider
    """
    shape = glider.shape_simple
    front, back = shape.front, shape.back
    arc = euklid.vector.PolyLine2D([list(rib.pos)[1:] for rib in glider.ribs])
    aoa = euklid.vector.PolyLine2D([[front.get(i)[0], rib.aoa_relative] for i, rib in enumerate(glider.ribs)])
    zrot = euklid.vector.PolyLine2D([[front.get(i)[0], rib.zrot] for i, rib in enumerate(glider.ribs)])

    def symmetric_fit(polyline: euklid.vector.PolyLine2D, numpoints: int=numpoints) -> euklid.spline.SymmetricBSplineCurve:
        return euklid.spline.SymmetricBSplineCurve.fit(polyline, numpoints)  # type: ignore

    front_bezier = symmetric_fit(front)
    back_bezier = symmetric_fit(back)
    arc_bezier = symmetric_fit(arc)
    aoa_bezier = symmetric_fit(aoa)
    zrot_bezier = symmetric_fit(zrot)

    cell_num = len(glider.cells) * 2 - glider.has_center_cell

    front.get(0)[0] = 0  # for midribs
    start = (2 - glider.has_center_cell) / cell_num
    const_arr = [0.] + np.linspace(start, 1, len(front) - 1).tolist()

    rib_pos = [p[0] for p in front]

    rib_pos_int = euklid.vector.Interpolation(list(zip([0] + rib_pos[1:], const_arr)))
    rib_distribution = euklid.vector.PolyLine2D([[i, rib_pos_int.get_value(i)] for i in np.linspace(0, rib_pos[-1], 30)])
    rib_distribution_curve = euklid.spline.BSplineCurve.fit(rib_distribution, numpoints+3)  # type: ignore

    profiles = [rib.profile_2d for rib in glider.ribs]
    profile_dist = euklid.spline.BSplineCurve.fit(euklid.vector.PolyLine2D([[i, i] for i, rib in enumerate(front)]),  # type: ignore
                                   numpoints)  # type: ignore

    balloonings = [cell.ballooning_modified for cell in glider.cells]
    ballooning_dist = euklid.spline.BSplineCurve.fit(euklid.vector.PolyLine2D([[i, i] for i, rib in enumerate(front.nodes[1:])]),  # type: ignore
                                   numpoints)  # type: ignore

    # TODO: lineset, dist-curce->xvalues
    raise NotImplementedError()
    parametric_shape = ParametricShape(front_bezier, back_bezier, rib_distribution_curve, cell_num)
    parametric_arc = ArcCurve(arc_bezier)


    return cls(shape=parametric_shape,
               arc=parametric_arc,
               aoa=aoa_bezier,
               zrot=zrot_bezier,
               profiles=profiles,
               profile_merge_curve=profile_dist,
               balloonings=balloonings,
               ballooning_merge_curve=ballooning_dist,
               glide=glider.glide,
               speed=10)
