"""
Parametric airfoil that is built of b-spline curves

The upper and the lower surface are built the same way, each of them from two
cubic b-spline curves (front and rear), which meet at the point of maximum height
(x_max, y_max) with a horizontal tangent. The lower surface is defined in a mirrored
frame, so a positive y_max means below the chord.

Each surface consists of two curves: the front curve covers x = 0 ... x_max,
the rear curve x = x_max ... 1 (x is monotonic along both of them).

Front curve (with a = (x_max - top_radius, y_max), the point in front of the maximum):

    (0, 0)
    (0, nose_radius)
    midpoint((0, nose_radius), a) + normal((0, nose_radius) -> a) * front_percentage * y_max
    a
    (x_max, y_max)

Rear curve (with b = (x_max + top_radius, y_max), the point behind the maximum):

    (x_max, y_max)
    b
    rear1: x at 1/3 between b and the trailing edge,
            y is interpolated between b and the trailing edge and offset by `rear_factor * y_max`
        rear2: built from the midpoint between rear1 and the trailing edge,
            vector (rear1 -> trailing edge) is rotated by trailing_edge_angle,
            then offset perpendicular by trailing_edge_factor * y_max
    (1, 0)  (closed trailing edge)

All angles are in radians, factors and percentages are given as fractions (1 = 100%).
"""
from __future__ import annotations

import functools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, fields
from enum import Enum

import numpy as np
import numpy.typing as npt
import scipy.optimize

import openglider.rs
from openglider.airfoil.profile_2d import Profile2D as Airfoil

FloatArray = npt.NDArray[np.float64]

_EPS = 1e-9
_REAR2_X = 0.8
_DEGREE = 3
_NUM_CONTROLPOINTS = 5
_NUM_SAMPLES = 500


@functools.lru_cache(maxsize=None)
def _bspline_basis(num_controlpoints: int, degree: int, t_values: tuple[float, ...]) -> FloatArray:
    """
    Basis functions of a clamped, uniform b-spline (same knots as openglider.rs.spline.*BSplineCurve)
    result[i, j]: value of basis function j at t_values[i]
    """
    inner = num_controlpoints - degree + 1
    knots = np.array([0.] * degree + [i / (inner - 1) for i in range(inner)] + [1.] * degree)
    t = np.array(t_values)

    # degree 0
    basis = np.zeros((len(t), len(knots) - 1))
    for i in range(len(knots) - 1):
        if knots[i] < knots[i + 1]:
            basis[:, i] = (t >= knots[i]) & (t < knots[i + 1])
    last_span = max(i for i in range(len(knots) - 1) if knots[i] < knots[i + 1])
    basis[t >= 1., last_span] = 1.

    # Cox-de Boor
    for d in range(1, degree + 1):
        new = np.zeros((len(t), len(knots) - 1 - d))
        for i in range(len(knots) - 1 - d):
            denominator_1 = knots[i + d] - knots[i]
            if denominator_1 > 0:
                new[:, i] += (t - knots[i]) / denominator_1 * basis[:, i]
            denominator_2 = knots[i + d + 1] - knots[i + 1]
            if denominator_2 > 0:
                new[:, i] += (knots[i + d + 1] - t) / denominator_2 * basis[:, i + 1]
        basis = new

    return basis[:, :num_controlpoints]


def _sample_basis(num: int=_NUM_SAMPLES) -> FloatArray:
    # a bit denser at the beginning of the curve (the nose)
    t = np.linspace(0, 1, num) ** 1.5
    return _bspline_basis(_NUM_CONTROLPOINTS, _DEGREE, tuple(float(v) for v in t))


@dataclass
class SurfaceParameters:
    """Parameters of one surface (upper or lower)"""
    x_max: float = 0.3
    "x position of the maximum height"
    y_max: float = 0.07
    "maximum height"
    nose_radius: float = 0.03
    "height of the second control point (above the nose)"
    front_percentage: float = 0.
    "offset of the third control point as percentage of |y_max|"
    top_radius: float = 0.1
    "distance of the control points next to the maximum"
    rear_factor: float = 0.
    "offset of rear1 as percentage of |y_max|"

    @classmethod
    def parameter_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def to_list(self) -> list[float]:
        return [float(getattr(self, name)) for name in self.parameter_names()]

    @classmethod
    def from_list(cls, values: Sequence[float]) -> SurfaceParameters:
        return cls(**{name: float(value) for name, value in zip(cls.parameter_names(), values)})

    def control_points(self, trailing_edge_angle: float=0., trailing_edge_factor: float=0.) -> tuple[FloatArray, FloatArray]:
        """control points of the front and the rear curve (y positive)"""
        x_max = self.x_max
        y_max = self.y_max
        profile_height = abs(y_max)

        # front
        front_radius = min(self.top_radius, x_max)
        front_top = np.array([x_max - front_radius, y_max])

        def rotate(point: FloatArray, angle: float) -> FloatArray:
            cos, sin = math.cos(angle), math.sin(angle)
            return np.array([point[0] * cos - point[1] * sin, point[0] * sin + point[1] * cos])

        nose_top = np.array([0., self.nose_radius])
        segment = front_top - nose_top
        midpoint = nose_top + segment * 0.5
        segment_length = max(np.linalg.norm(segment), _EPS)
        normal = rotate(segment / segment_length, math.pi / 2)
        p2 = midpoint + normal * self.front_percentage * profile_height
        # the front curve covers exactly x = 0 ... x_max (x is monotonic along the curve)
        p2[0] = min(max(p2[0], 0.), front_top[0])

        front = np.array([
            [0, 0],
            [0, self.nose_radius],
            p2,
            front_top,
            [x_max, y_max]
        ], dtype=float)

        # rear: construct rear2 first, then rear1 between back and rear2
        rear_radius = min(self.top_radius, 1 - x_max)
        x_start = x_max + rear_radius
        rear_back = np.array([x_start, y_max])

        rear2_x = min(max(_REAR2_X, x_start + _EPS), 1. - _EPS)
        rear2_y = math.tan(trailing_edge_angle) * (1. - rear2_x)
        rear2 = np.array([rear2_x, rear2_y + trailing_edge_factor * profile_height])

        rear_segment = rear2 - rear_back
        rear_segment_length = max(np.linalg.norm(rear_segment), _EPS)
        rear_normal = rotate(rear_segment / rear_segment_length, math.pi / 2)
        rear1 = rear_back + 0.5 * rear_segment + rear_normal * self.rear_factor * profile_height

        rear = np.array([
            [x_max, y_max],
            [x_start, y_max],
            rear1,
            rear2,
            [1, 0]
        ], dtype=float)

        return front, rear

    def polyline(self, num: int=_NUM_SAMPLES, trailing_edge_angle: float=0., trailing_edge_factor: float=0.) -> FloatArray:
        """densely sampled surface from the nose to the trailing edge (y positive)"""
        basis = _sample_basis(num)
        front, rear = self.control_points(trailing_edge_angle, trailing_edge_factor)

        return np.vstack([basis @ front, (basis @ rear)[1:]])  # type: ignore[no-any-return]


def _y_at(polyline: FloatArray, x: FloatArray) -> FloatArray:
    xs = np.maximum.accumulate(polyline[:, 0])
    return np.interp(x, xs, polyline[:, 1])  # type: ignore[no-any-return]


def _resample(polyline: FloatArray, num: int) -> FloatArray:
    """
    resample a polyline with a mix of equal arc length and equal turning angle
    (so the nose is resolved properly). returns num+1 points
    """
    diff = np.diff(polyline, axis=0)
    length = np.hypot(diff[:, 0], diff[:, 1])
    keep = length > 1e-12
    diff = diff[keep]
    length = length[keep]
    starts = polyline[:-1][keep]

    heading = np.unwrap(np.arctan2(diff[:, 1], diff[:, 0]))
    turn_vertex = np.concatenate([[0.], np.abs(np.diff(heading)), [0.]])
    turn_segment = (turn_vertex[:-1] + turn_vertex[1:]) / 2

    weight = length / max(length.sum(), _EPS) + turn_segment / max(turn_segment.sum(), _EPS)
    cumulative = np.concatenate([[0.], np.cumsum(weight)])
    targets = np.linspace(0, cumulative[-1], num + 1)

    points = np.vstack([starts, polyline[-1:]])
    return np.stack([np.interp(targets, cumulative, points[:, i]) for i in range(2)], axis=1)  # type: ignore[no-any-return]


@dataclass
class ParsecFit:
    airfoil: ParsecAirfoil
    rms_error: float
    max_error: float


class SurfaceSide(Enum):
    UPPER = "upper"
    LOWER = "lower"


@dataclass
class ParsecAirfoil:
    upper: SurfaceParameters = field(default_factory=lambda: SurfaceParameters())
    lower: SurfaceParameters = field(default_factory=lambda: SurfaceParameters(
        x_max=0.35, y_max=0.03, nose_radius=0.02, top_radius=0.12
    ))
    trailing_edge_angle: float = 0.2
    trailing_edge_factor: float = 0.
    numpoints: int = 180

    def get_parameters(self) -> dict[str, float]:
        """flat parameter dict (upper_x_max, ...)"""
        values = {
            f"{side}_{name}": value
            for side, params in ((SurfaceSide.UPPER.value, self.upper), (SurfaceSide.LOWER.value, self.lower))
            for name, value in zip(SurfaceParameters.parameter_names(), params.to_list())
        }
        values["trailing_edge_angle"] = self.trailing_edge_angle
        values["trailing_edge_factor"] = self.trailing_edge_factor

        return values

    def _surface_parameters(self, side: SurfaceSide) -> SurfaceParameters:
        return self.upper if side is SurfaceSide.UPPER else self.lower

    def _surface_trailing_angle(self, side: SurfaceSide) -> float:
        return self.trailing_edge_angle if side is SurfaceSide.UPPER else -self.trailing_edge_angle

    def _surface_control_points(self, side: SurfaceSide) -> tuple[FloatArray, FloatArray]:
        params = self._surface_parameters(side)
        angle = self._surface_trailing_angle(side)
        return params.control_points(angle, self.trailing_edge_factor)

    def _surface_polyline(self, side: SurfaceSide, num: int=_NUM_SAMPLES) -> FloatArray:
        params = self._surface_parameters(side)
        angle = self._surface_trailing_angle(side)
        return params.polyline(num, angle, self.trailing_edge_factor)

    def get_curves(self) -> dict[str, openglider.rs.spline.CubicBSplineCurve]:
        """the four b-spline curves (the lower ones are mirrored)"""
        result = {}
        for side, sign in ((SurfaceSide.UPPER, 1), (SurfaceSide.LOWER, -1)):
            front, rear = self._surface_control_points(side)
            result[f"{side.value}_front"] = openglider.rs.spline.CubicBSplineCurve(
                [[x, sign * y] for x, y in front]
            )
            result[f"{side.value}_rear"] = openglider.rs.spline.CubicBSplineCurve(
                [[x, sign * y] for x, y in rear]
            )

        return result

    def upper_at(self, x: Sequence[float] | FloatArray) -> FloatArray:
        return _y_at(self._surface_polyline(SurfaceSide.UPPER), np.abs(np.asarray(x, dtype=float)))

    def lower_at(self, x: Sequence[float] | FloatArray) -> FloatArray:
        return -_y_at(self._surface_polyline(SurfaceSide.LOWER), np.abs(np.asarray(x, dtype=float)))

    def get_airfoil(self, numpoints: int=None, name: str="parsec") -> Airfoil:
        """airfoil from the trailing edge via the upper surface and the nose to the trailing edge"""
        if numpoints is None:
            numpoints = self.numpoints
        num = max(2, numpoints // 2)

        upper = _resample(self._surface_polyline(SurfaceSide.UPPER), num)
        lower = _resample(self._surface_polyline(SurfaceSide.LOWER), num) * np.array([1, -1])

        points = np.vstack([upper[::-1], lower[1:]])

        return Airfoil([(float(x), float(y)) for x, y in points], name)

    @classmethod
    def fit(cls, airfoil: Airfoil, num_samples: int=200, effort: int=3) -> ParsecFit:
        """
        Fit the parameters to an existing airfoil.
        The surfaces are fitted independently (global search + least squares).

        num_samples: number of points the airfoil is sampled at (dense at the nose)
        effort: 0 (local fit only) ... 10 (thorough). Number of iterations of the global search
        """
        profile = airfoil.normalized(close=True)

        s = np.linspace(0, 1, max(num_samples, 20))
        x = ((1 - np.cos(np.pi * s)) / 2) ** 1.5

        upper = np.array([profile.get(-float(xi))[1] for xi in x])
        lower = np.array([profile.get(float(xi))[1] for xi in x])

        upper_surface, upper_angle, upper_factor = cls._fit_surface(x, upper, effort)
        lower_surface, lower_angle, lower_factor = cls._fit_surface(x, -lower, effort)

        initial_shared = np.array([
            0.5 * (upper_angle - lower_angle),
            0.5 * (upper_factor + lower_factor)
        ])

        def shared_residual(p: FloatArray) -> FloatArray:
            angle = float(p[0])
            factor = float(p[1])
            upper_pred = _y_at(upper_surface.polyline(300, angle, factor), x)
            lower_pred = -_y_at(lower_surface.polyline(300, -angle, factor), x)
            return np.concatenate([upper_pred - upper, lower_pred - lower])  # type: ignore[no-any-return]

        shared_result = scipy.optimize.least_squares(
            shared_residual,
            np.clip(initial_shared, np.array([-1.4, -1.0]), np.array([1.4, 1.0])),
            bounds=(np.array([-1.4, -1.0]), np.array([1.4, 1.0])),
            x_scale=np.array([2.8, 2.0]),
            diff_step=1e-5,
            max_nfev=300
        )

        trailing_angle = float(shared_result.x[0])
        trailing_factor = float(shared_result.x[1])

        result = cls(
            upper=upper_surface,
            lower=lower_surface,
            trailing_edge_angle=trailing_angle,
            trailing_edge_factor=trailing_factor,
            numpoints=airfoil.numpoints
        )

        errors = np.concatenate([result.upper_at(x) - upper, result.lower_at(x) - lower])

        return ParsecFit(
            airfoil=result,
            rms_error=float(np.sqrt(np.mean(errors**2))),
            max_error=float(np.max(np.abs(errors)))
        )

    @staticmethod
    def _optimize(
            function: Callable[[FloatArray], FloatArray], guess: FloatArray,
            lower: list[float], upper: list[float], effort: int) -> FloatArray:
        """differential evolution (global) followed by a least squares polish"""
        lower_array = np.array(lower)
        upper_array = np.array(upper)
        guess = np.clip(guess, lower_array + 1e-9, upper_array - 1e-9)

        def cost(p: FloatArray) -> float:
            residual = function(p)
            return float(np.dot(residual, residual))

        candidates = [guess]
        if effort > 0:
            global_result = scipy.optimize.differential_evolution(
                cost,
                list(zip(lower, upper)),
                x0=guess,
                maxiter=40 * effort,
                popsize=8,
                tol=1e-10,
                mutation=(0.4, 1.0),
                seed=0,
                polish=False
            )
            candidates.append(global_result.x)

        best: scipy.optimize.OptimizeResult | None = None
        for start in candidates:
            result = scipy.optimize.least_squares(
                function,
                np.clip(start, lower_array + 1e-9, upper_array - 1e-9),
                bounds=(lower_array, upper_array),
                x_scale=upper_array - lower_array,
                diff_step=1e-5,
                max_nfev=300
            )
            if best is None or result.cost < best.cost:
                best = result

        assert best is not None
        return best.x  # type: ignore[no-any-return]

    @classmethod
    def _fit_surface(cls, x: FloatArray, y: FloatArray, effort: int) -> tuple[SurfaceParameters, float, float]:
        """fit one surface (y positive) to the data"""
        i_max = int(np.argmax(y))
        x_max = min(max(float(x[i_max]), 0.1), 0.7)
        y_max = max(float(y[i_max]), 1e-3)

        angle = math.atan(max(float(np.interp(0.9, x, y)) / 0.1, 0.02))

        guess = np.array([
            x_max, y_max, 0.5 * y_max,
            0., 0.1,
            0., angle, 0.
        ])
        lower = [0.05, 0.001, 0.001, -1., 0.005, -1., -1.4, -1.]
        upper = [0.8, 0.4, 0.3, 1., 0.5, 1., 1.4, 1.]

        def residual(p: FloatArray) -> FloatArray:
            surface = SurfaceParameters.from_list(p[:-2])
            return _y_at(surface.polyline(300, float(p[-2]), float(p[-1])), x) - y  # type: ignore[no-any-return]

        fitted = cls._optimize(residual, guess, lower, upper, effort)
        surface = SurfaceParameters.from_list(fitted[:-2])
        return surface, float(fitted[-2]), float(fitted[-1])
