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

import numpy as np
import numpy.typing as npt
import scipy.optimize

import openglider.rs
from openglider.airfoil.profile_2d import Profile2D as Airfoil

FloatArray = npt.NDArray[np.float64]

_EPS = 1e-9
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
    trailing_edge_angle: float = 0.2
    "angle between the surface and the chord at the trailing edge"
    trailing_edge_factor: float = 0.
    "perpendicular offset of rear2 as percentage of |y_max| (0: no additional offset)"

    @classmethod
    def parameter_names(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    def to_list(self) -> list[float]:
        return [float(getattr(self, name)) for name in self.parameter_names()]

    @classmethod
    def from_list(cls, values: Sequence[float]) -> SurfaceParameters:
        return cls(**{name: float(value) for name, value in zip(cls.parameter_names(), values)})

    def control_points(self) -> tuple[FloatArray, FloatArray]:
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

        # rear: interpolated between the point behind the maximum and the trailing edge
        rear_radius = min(self.top_radius, 1 - x_max)
        x_start = x_max + rear_radius
        length = 1 - x_start
        x1 = x_start + length / 3
        y1 = y_max * 2 / 3 + self.rear_factor * profile_height

        rear1 = np.array([x1, y1])
        trailing_edge = np.array([1., 0.])
        rear_segment = trailing_edge - rear1
        rear2 = rear1 + rotate(rear_segment * 0.5, self.trailing_edge_angle)
        rear_segment_length = max(np.linalg.norm(rear_segment), _EPS)
        rear_normal = rotate(rear_segment / rear_segment_length, math.pi / 2)
        rear2 = rear2 + rear_normal * self.trailing_edge_factor * profile_height

        rear = np.array([
            [x_max, y_max],
            [x_start, y_max],
            [x1, y1],
            rear2,
            [1, 0]
        ], dtype=float)

        return front, rear

    def polyline(self, num: int=_NUM_SAMPLES) -> FloatArray:
        """densely sampled surface from the nose to the trailing edge (y positive)"""
        basis = _sample_basis(num)
        front, rear = self.control_points()

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


@dataclass
class ParsecAirfoil:
    upper: SurfaceParameters = field(default_factory=lambda: SurfaceParameters())
    lower: SurfaceParameters = field(default_factory=lambda: SurfaceParameters(
        x_max=0.35, y_max=0.03, nose_radius=0.02, top_radius=0.12, trailing_edge_angle=0.1
    ))

    def get_parameters(self) -> dict[str, float]:
        """flat parameter dict (upper_x_max, ...)"""
        return {
            f"{side}_{name}": value
            for side, params in (("upper", self.upper), ("lower", self.lower))
            for name, value in zip(SurfaceParameters.parameter_names(), params.to_list())
        }

    def get_curves(self) -> dict[str, openglider.rs.spline.CubicBSplineCurve]:
        """the four b-spline curves (the lower ones are mirrored)"""
        result = {}
        for side, params, sign in (("upper", self.upper, 1), ("lower", self.lower, -1)):
            front, rear = params.control_points()
            result[f"{side}_front"] = openglider.rs.spline.CubicBSplineCurve(
                [[x, sign * y] for x, y in front]
            )
            result[f"{side}_rear"] = openglider.rs.spline.CubicBSplineCurve(
                [[x, sign * y] for x, y in rear]
            )

        return result

    def upper_at(self, x: Sequence[float] | FloatArray) -> FloatArray:
        return _y_at(self.upper.polyline(), np.abs(np.asarray(x, dtype=float)))

    def lower_at(self, x: Sequence[float] | FloatArray) -> FloatArray:
        return -_y_at(self.lower.polyline(), np.abs(np.asarray(x, dtype=float)))

    def get_airfoil(self, numpoints: int=100, name: str="parsec") -> Airfoil:
        """airfoil from the trailing edge via the upper surface and the nose to the trailing edge"""
        num = max(2, numpoints // 2)

        upper = _resample(self.upper.polyline(), num)
        lower = _resample(self.lower.polyline(), num) * np.array([1, -1])

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

        result = cls(
            upper=cls._fit_surface(x, upper, effort),
            lower=cls._fit_surface(x, -lower, effort)
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
    def _fit_surface(cls, x: FloatArray, y: FloatArray, effort: int) -> SurfaceParameters:
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
        lower = [0.05, -0.05, 0.001, -1., 0.005, -1., -1.4, -1.]
        upper = [0.8, 0.4, 0.3, 1., 0.5, 1., 1.4, 1.]

        def residual(p: FloatArray) -> FloatArray:
            return _y_at(SurfaceParameters.from_list(p).polyline(300), x) - y  # type: ignore[no-any-return]

        return SurfaceParameters.from_list(cls._optimize(residual, guess, lower, upper, effort))
