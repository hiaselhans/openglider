from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, TypeAlias
from collections.abc import Iterator
import openglider.rs

from openglider.glider.ballooning.base import BallooningBase

if TYPE_CHECKING:
    from openglider.glider.ballooning.old import Ballooning


logger = logging.getLogger(__name__)


class BallooningNew(BallooningBase):
    def __init__(self, interpolation: openglider.rs.vector.Interpolation, name: str="ballooning_new") -> None:
        self.interpolation = interpolation
        self.name = name

    def __json__(self) -> dict[str, Any]:
        return {
            "interpolation": self.interpolation.tolist(),
            "name": self.name
        }
    
    @classmethod
    def __from_json__(cls, **kwargs: Any) -> BallooningNew:
        _interpolation = openglider.rs.vector.Interpolation(kwargs["interpolation"])

        return cls(_interpolation, kwargs["name"])

    def __iter__(self) -> Iterator[openglider.rs.vector.Vector2D]:
        return self.interpolation.__iter__()

    def __getitem__(self, xval: float) -> float:
        """Get Ballooning Value (%) for a certain XValue"""
        if -1 <= xval <= 1:
            return max(0, self.interpolation.get_value(xval))
        else:
            raise ValueError(f"Value {xval} not between -1 and 1")
    
    def __add__(self, other: BallooningBase) -> BallooningNew:
        if not isinstance(other, BallooningNew):
            raise NotImplementedError()
        new_interpolation = openglider.rs.vector.Interpolation(self.interpolation + other.interpolation)

        return BallooningNew(new_interpolation)
    
    def __mul__(self, factor: float) -> BallooningNew:
        interpolation = self.interpolation.copy()
        interpolation = interpolation.scale(openglider.rs.vector.Vector2D([1, factor]))
        return BallooningNew(interpolation)

    def close_trailing_edge(self, start_x: float) -> None:
        if self[-1] > 1e-10 or self[1] > 1e-10:
            nodes = []
            for n in self.interpolation.nodes:
                x = abs(n[0])
                y = n[1]
                if x > start_x:
                    y = n[1]
                    t_e_c = start_x
                    y = y * (1 - (x-t_e_c)/(1-t_e_c))
                
                nodes.append([n[0], y])
            
            self.interpolation = openglider.rs.vector.Interpolation(nodes)

    @property
    def amount_maximal(self) -> float:
        return max([p[1] for p in self.interpolation.nodes])

    def copy(self) -> BallooningNew:
        return BallooningNew(self.interpolation.copy(), name=self.name)


VecType: TypeAlias = openglider.rs.vector.Vector2D | tuple[float, float]

class BallooningBezierNeu(BallooningNew):
    spline_curve: openglider.rs.spline.BSplineCurve

    def __init__(self, spline: list[openglider.rs.vector.Vector2D] | list[tuple[float, float]], name: str="ballooning_new") -> None:
        super().__init__(None, None)  # type: ignore
        self.spline_curve = openglider.rs.spline.BSplineCurve(spline)
        self.name = name
        self.apply_splines()

    def __json__(self) -> dict[str, Any]:
        return {
            "spline": self.spline_curve.controlpoints,
            "name": self.name
            }
    
    def copy(self) -> BallooningBezierNeu:
        return BallooningBezierNeu(self.spline_curve.controlpoints.nodes.copy(), name=self.name)

    @classmethod
    def __from_json__(cls, **kwargs: Any) -> BallooningNew:
        return cls(**kwargs)

    def __getitem__(self, xval: float) -> float:
        """Get Ballooning Value (%) for a certain XValue"""
        if -1 <= xval <= 1:
            return max(0, self.interpolation.get_value(xval))
        else:
            raise ValueError(f"Value {xval} not between -1 and 1")

    @classmethod
    def from_classic(cls, ballooning: Ballooning, numpoints: int=12) -> BallooningBezierNeu:
        upper = ballooning.upper.scale([-1, 1])
        lower = ballooning.lower

        data = upper.reverse().nodes + lower.nodes

        data[0][0] = -1
        data[-1][0] = 1

        #data = [(-p[0], p[1]) for p in upper[::-1]] + list(lower)

        spline = openglider.rs.spline.BSplineCurve.fit(openglider.rs.vector.PolyLine2D(data), numpoints)  # type: ignore
        controlpoints: list[openglider.rs.vector.Vector2D] = []

        for x, y in spline.controlpoints:
            x = max(-1, min(x, 1))
            controlpoints.append(openglider.rs.vector.Vector2D([x,y]))

        #return data
        return cls(controlpoints)

    def get_points(self, n: int=300) -> list[openglider.rs.vector.Vector2D]:
        return self.spline_curve.get_sequence(n).nodes

    def apply_splines(self) -> None:
        self.interpolation = openglider.rs.vector.Interpolation(self.get_points(), extrapolate=True)

    def __mul__(self, factor: float) -> BallooningBezierNeu:
        return BallooningBezierNeu(self.controlpoints.scale(openglider.rs.vector.Vector2D([1, factor])).nodes)

    def __imul__(self, factor: float) -> BallooningBezierNeu:  # TODO: Check consistency
        """Multiplication of BezierBallooning"""
        self.scale(factor)
        self.apply_splines()
        return self
    
    def close_trailing_edge(self, start_x: float) -> None:
        cp = self.controlpoints.nodes[:]
        cp[0][1] = 0
        cp[-1][1] = 0
        self.controlpoints = openglider.rs.vector.PolyLine2D(cp)
        
        return super().close_trailing_edge(start_x)

    @property
    def controlpoints(self) -> openglider.rs.vector.PolyLine2D:
        return self.spline_curve.controlpoints

    @controlpoints.setter
    def controlpoints(self, controlpoints: openglider.rs.vector.PolyLine2D) -> None:
        self.spline_curve.controlpoints = controlpoints
        self.apply_splines()

    def scale(self, factor: float) -> None:
        self.spline_curve.controlpoints = self.spline_curve.controlpoints.scale(openglider.rs.vector.Vector2D([1, factor]))
        self.apply_splines()

    def _repr_svg_(self) -> str:
        import svgwrite
        import svgwrite.container

        height = self.amount_maximal

        drawing = svgwrite.Drawing(size=[800, 800*height])

        drawing.viewbox(-1, -height/2, 2, height)

        g = svgwrite.container.Group()
        g.scale(1, -1)
        upper = drawing.polyline(self.spline_curve.get_sequence(100).nodes, style="stroke:black; vector-effect: non-scaling-stroke; fill: none;")
        g.add(upper)
        drawing.add(g)

        return drawing.tostring()

