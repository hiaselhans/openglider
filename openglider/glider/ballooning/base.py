from __future__ import annotations

from abc import ABC
import math
from collections.abc import Iterator

import numpy as np
import euklid

import openglider
from pyfoil import Airfoil

class ArcSinc:
    def __init__(self) -> None:
        self.start = 0.
        self.end = math.pi
        self.interpolate(openglider.config['asinc_interpolation_points'])

    def __call__(self, val: float) -> float:
        return self.arsinc.get_value(val)

    def interpolate(self, numpoints: int) -> None:
        data = []

        for i in range(numpoints + 1):
            phi = self.end + (i * 1. / numpoints) * (self.start - self.end)  # reverse for interpolation (increasing x_values)
            data.append([np.sinc(phi / np.pi), phi])

        self.arsinc = euklid.vector.Interpolation(data)

    @property
    def numpoints(self) -> int:
        return len(self.arsinc.nodes)

    @numpoints.setter
    def numpoints(self, numpoints: int) -> None:
        self.interpolate(numpoints)


class BallooningBase(ABC):
    arcsinc = ArcSinc()
    name: str

    def draw(self) -> euklid.vector.PolyLine2D:
        points = []
        last_point = None

        upper = euklid.vector.Vector2D([-1, 1])
        lower = euklid.vector.Vector2D([1, -1])

        for p in self:
            if p[0] < 0:
                points.append(p * upper)
            else:
                if last_point and last_point[0] < 0:
                    amount_at_zero = self[0]
                    points.append(euklid.vector.Vector2D([0, amount_at_zero]))
                    points.append(euklid.vector.Vector2D([0, -amount_at_zero]))
                
                points.append(p * lower)
            
            last_point = p
        
        return euklid.vector.PolyLine2D(points)

    def __iter__(self) -> Iterator[euklid.vector.Vector2D]:
        raise NotImplementedError(f"no iter method defined on {self.__class__}")

    def __call__(self, xval: float) -> float:
        return self.get_phi(xval)

    def __getitem__(self, xval: float) -> float:
        raise NotImplementedError()
    
    def __add__(self, other: BallooningBase) -> BallooningBase:
        raise NotImplementedError()
    
    def __mul__(self, factor: float) -> BallooningBase:
        raise NotImplementedError()

    def get_phi(self, xval: float) -> float:
        """Get Ballooning Arc (phi) for a certain XValue"""
        return self.phi(self[xval])

    def get_tension_factor(self, xval: float) -> float:
        """Get the tension due to ballooning"""
        value =  2. * np.tan(self.get_phi(xval))
        if value == 0:
            return value
        else:
            return 1. / value
        
    def get_mean_height(self, x: float) -> float:
        """
        Get the mean height (multiply by cell width!)"""
        ballooning_amount = self[x]
        phi = self.phi(ballooning_amount)
        if phi < 1e-6:
            return 0.
        
        r_by_width = (1+ballooning_amount/2) / phi / 2

        return r_by_width * (math.sin(phi) / phi - math.cos(phi))
    
    def get_max_height(self, x: float) -> float:
        ballooning_amount = self[x]
        phi = self.phi(ballooning_amount)
        if phi < 1e-6:
            return 0.
        r_by_width = (1+ballooning_amount/2) / phi

        return r_by_width * (1 - math.cos(phi))
    
    @classmethod
    def apply_height_to_airfoil(cls, airfoil: Airfoil, amounts: list[float]) -> Airfoil:
        normals = airfoil.normvectors

        assert len(normals.nodes) == len(airfoil.curve.nodes) == len(amounts)

        new_points = [
            p + n * amount for p, amount, n in zip(airfoil.curve.nodes, amounts, normals)
        ]

        return Airfoil(new_points).normalized()

    @classmethod
    def phi(cls, baloon: float) -> float:
        """
        Return the angle of the piece of cake.
        b/l=R*phi/(R*Sin(phi)) -> Phi=arsinc(l/b)
        """
        if baloon < 0:
            return 0
        return cls.arcsinc(1/(baloon+1))
    
    def close_trailing_edge(self, x: float) -> None:
        raise NotImplementedError()
    
    def apply_splines(self) -> None:
        pass


