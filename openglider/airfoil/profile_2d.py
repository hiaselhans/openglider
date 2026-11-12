from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Iterable, List, Self, Sequence
import os
import re
import math
import logging

import openglider.rs
from openglider.utils.cache import cached_property
import openglider.xfoil as xfoil

if TYPE_CHECKING:
    from openglider.airfoil.generators.parsec import ParsecAirfoil
import pandas

from openglider.airfoil.generators import JoukowskyAirfoil, VanDeVoorenAirfoil, TrefftzKuttaAirfoil, compute_naca
from openglider.vector.unit import Percentage


logger = logging.getLogger(__name__)

solver = xfoil.Solver()

class Profile2D:
    noseindex: int
    name: str
    _curve: openglider.rs.vector.PolyLine2D
    
    ncrit = 4
    xtr_top = 0.5
    xtr_bottom = 0.5
    reynolds: float | None = None
    mach: float = 0.

    parsec_data: ParsecAirfoil | None = None

    def __init__(self, data: Sequence[openglider.rs.vector.Vector2D | tuple[float, float]] | openglider.rs.vector.PolyLine2D, name: str="unnamed") -> None:
        self.name = name
        if isinstance(data, openglider.rs.vector.PolyLine2D):
            self._curve = data
        else:
            self._curve = openglider.rs.vector.PolyLine2D(data)

        self._setup()

    def __hash__(self) -> int:
        return hash((self.curve.__hash__(), self.name))

    @property
    def curve(self) -> openglider.rs.vector.PolyLine2D:
        return self._curve

    @curve.setter
    def curve(self, value: openglider.rs.vector.PolyLine2D) -> None:
        self._curve = value
        self._setup()

    def _setup(self) -> None:
        i = 0
        data = self.curve.nodes
        while data[i + 1][0] < data[i][0] and i < len(data) - 2:
            i += 1
        self.noseindex = i

        # Create a mapping x -> ik value
        self._interpolation_x_values = openglider.rs.vector.Interpolation(
            [[-p[0], i] for i, p in enumerate(self.curve.nodes[:self.noseindex])] +
            [[ p[0], i+self.noseindex] for i, p in enumerate(self.curve.nodes[self.noseindex:])],
            extrapolate=True,
            validate=False
        )

    def _load_xfoil(self) -> None:
        solver.ncrit = self.ncrit
        solver.xtr_top = self.xtr_top
        solver.xtr_bottom = self.xtr_bottom
        if self.reynolds is not None and hasattr(solver, "reynolds"):
            solver.reynolds = self.reynolds
        if hasattr(solver, "mach"):
            solver.mach = self.mach

        if len(self.curve) > 300:
            raise Exception(f"too many numpoints for profile {self.name}: {len(self.curve)}")
        
        solver.load(self.curve.tolist())

    
    def xfoil_aoa(self, aoa: float, degree: bool=True, load: bool=True) -> xfoil.Result:
        # TODO: reynolds
        if degree:
            aoa = aoa * math.pi / 180

        if load:
            self._load_xfoil()

        return solver.run_aoa(aoa)
    
    def xfoil_polar(self, aoa_start: float, aoa_end: float, steps: int=10, degree: bool=True) -> pandas.DataFrame:
        self._load_xfoil()
        delta = (aoa_end-aoa_start)/(steps-1)
        data = []
        for i in range(steps):
            aoa = aoa_start + delta*i

            try:
                result = self.xfoil_aoa(aoa, degree=degree, load=False)
            except RuntimeError:
                continue

            if result.converged:
                data.append([
                    result.aoa,
                    result.cl,
                    result.cd,
                    result.cdp,
                    result.cm
                ])
        
        return pandas.DataFrame(data, columns=["aoa", "cl", "cd", "cdp", "cm"])


    def __mul__(self, value: float) -> Self:
        fakt = openglider.rs.vector.Vector2D([1, float(value)])

        return type(self)(self.curve * fakt)

    def __call__(self, xval: Percentage | float) -> float:
        return self.get_ik(xval)

    def get_ik(self, x: Percentage | float) -> float:
        xval = float(x)
        return self._interpolation_x_values.get_value(xval)
    
    def get(self, x: Percentage | float) -> openglider.rs.vector.Vector2D:
        ik = self.get_ik(x)
        return self.curve.get(ik)

    def align(self, p: Sequence[float] | openglider.rs.vector.Vector2D) -> openglider.rs.vector.Vector2D:
        """Align a point (x, y) on the airfoil. x: (0,1), y: (-1,1)"""
        x, y = p

        upper = self.get(-x)
        lower = self.get(x)

        return lower + (upper-lower) * ((y + 1)/2)

    def profilepoint(self, xval: Percentage | float, h: float=-1.) -> openglider.rs.vector.Vector2D:
        """
        Get airfoil Point for x-value (<0:upper side)
        optional: height (-1:lower,1:upper)
        """
        if h == -1:
            return self.get(xval)
        else:
            return self.align([float(xval), h])

    def normalized(self, close: bool=True) -> Self:
        """
        Normalize the airfoil.
        This routine does:
            *Put the nose back to (0,0)
            *De-rotate airfoil
            *Reset its length to 1
        """
        nose = self.curve.nodes[self.noseindex]

        new_curve: openglider.rs.vector.PolyLine2D = self.curve.move(nose * -1)

        diff = (new_curve.nodes[0] + new_curve.nodes[-1]) * 0.5

        # normalize length
        new_curve = new_curve.scale(1/diff.length())

        # de-rotate
        rotation = openglider.rs.vector.Rotation2D(-diff.angle())
        new_nodes = [rotation.apply(p) for p in new_curve.nodes]

        new_nodes[0][0] = 1.
        new_nodes[-1][0] = 1.

        if close:
            new_nodes[0][1] = 0
            new_nodes[-1][1] = 0
        
        return type(self)(new_nodes, self.name)
    
    @property
    def normvectors(self) -> openglider.rs.vector.PolyLine2D:
        return self.curve.normvectors()

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        cpy = self.copy()
        memo[id(self)] = cpy
        return cpy

    def __copy__(self) -> Self:
        return self.copy()

    def copy(self) -> Self:
        return type(self)(self.curve.nodes, self.name)

    def __add__(self, other: Self, conservative: bool=False) -> Self:
        """
        Mix 2 Profiles
        """
        new = []
        for i, point in enumerate(self.curve.nodes):
            x = point[0]
            if i < self.noseindex:
                x = -x

            y2 = other.get(x)[1]
            new.append(point + openglider.rs.vector.Vector2D([0.0, y2]))
        
        return type(self)(new)

    def __json__(self) -> dict[str, Any]:
        return {
            "data": [list(p) for p in self.curve.nodes],
            "name": self.name
        }

    _re_number = r"[+-]?(?:(?:\d+\.?\d*)|(?:\.\d+))(?:[eE][+-]?\d+)?|\d+"
    _re_coord_line = re.compile(rf"\s*({_re_number})\s+({_re_number})\s*")

    @classmethod
    def import_from_dat(cls, path: str | os.PathLike[str]) -> Self:
        """
        Import an airfoil from a '.dat' file
        """
        name = os.path.split(path)[-1]
        with open(path, "r") as p_file:
            return cls._import_dat(p_file, name=name)
    
    @classmethod
    def _import_dat(cls, p_file: Iterable[str], name: str="unnamed") -> Self:
        profile: list[tuple[float, float]] = []
        for i, line in enumerate(p_file):
            if line.endswith(","):
                line = line[:-1]

            match = cls._re_coord_line.match(line)

            if match:
                profile.append((float(match.group(1)), float(match.group(2))))
            elif i == 0:
                name = line.strip()
            elif len(line) == 0:
                continue
            else:
                logger.error(f"error in dat airfoil: {name} {i}:({line.strip()})")

        return cls(profile, name)


    def export_dat(self, pfad: str | os.PathLike[str]) -> str | os.PathLike[str]:
        """
        Export airfoil to .dat Format
        """
        with open(pfad, "w") as out:
            if self.name:
                out.write(str(self.name).strip())
            for p in self.curve.nodes:
                out.write("\n{: 10.8f}\t{: 10.8f}".format(*p))
        return pfad

    @cached_property("curve")
    def x_values(self) -> List[float]:
        """Get XValues of airfoil. upper side neg, lower positive"""
        i = self.noseindex

        x_values = [-vector[0] for vector in self.curve.nodes[:i]]
        x_values += [vector[0] for vector in self.curve.nodes[i:]]
        return x_values

    def set_x_values(self, xval: Sequence[Percentage | float]) -> Self:
        """Set X-Values of airfoil to defined points."""
        new_nodes = [
            self.get(x) for x in xval
        ]

        return type(self)(new_nodes)

    @property
    def numpoints(self) -> int:
        return len(self.curve.nodes)

    def resample(self, numpoints: int) -> Self:
        numpoints -= numpoints % 2  # brauchts?

        xtemp = lambda x: ((x > 0.5) - (x < 0.5)) * (1 - math.sin(math.pi * x))

        x_values = ([xtemp(i/numpoints) for i in range(numpoints+1)])

        return self.set_x_values(x_values)

    @property
    def thickness(self) -> float:
        """return the maximum sickness (Sic!) of an airfoil"""
        xvals = sorted(set(map(abs, self.x_values)))

        return max([
            abs(self.get(-x)[1] - self.get(x)[1]) for x in xvals
        ])

    def set_thickness(self, newthick: float) -> Self:
        factor = float(newthick / self.thickness)

        name = self.name
        if name is not None:
            name += "_" + str(newthick) + "%"

        return type(self)(self.curve * [1, factor], name)

    @property
    def camber_line(self) -> openglider.rs.vector.Interpolation:
        xvals = sorted(set(map(abs, self.x_values)))
        return openglider.rs.vector.Interpolation([self.profilepoint(i, 0.) for i in xvals])

    #@cached_property('self')
    @property
    def camber(self) -> float:
        """return the maximum camber of the airfoil"""
        return max([p[1] for p in self.camber_line])

    def set_camber(self, newcamber: float) -> Self:
        """Set maximal camber to the new value"""
        old_camber = self.camber
        factor = newcamber / old_camber - 1
        old_camber_line = self.camber_line

        data = [
            p + openglider.rs.vector.Vector2D([0.0, old_camber_line.get_value(p[0]) * factor])
            for p in self.curve.nodes
        ]

        return type(self)(data)

    def insert_point(self, pos: Percentage | float, tolerance: float=1e-5) -> Self:
        pos_float = float(pos)
        nearest_x_value = self.find_nearest_x_value(pos_float)
        new_nodes = self.curve.nodes[:]

        if abs(nearest_x_value - pos_float) > tolerance:
            point = self.get(pos_float)
            ik = self.get_ik(pos_float)

            new_nodes.insert(int(ik + 1), point)

        return type(self)(new_nodes)

    def remove_points(self, start: Percentage | float, end: Percentage | float, tolerance: float=0.) -> Self:
        new_data = []

        ik_start = self.get_ik(start)
        ik_end = self.get_ik(end)

        i_start = int(ik_start - ik_start%1)
        if (self.curve.get(ik_start)-self.curve.get(i_start)).length() > tolerance:
            i_start += 1
        
        i_end = int(ik_end - ik_end%1)
        if (self.curve.get(ik_end)-self.curve.get(i_end+1)).length() <= tolerance:
            i_end += 1

        new_data = self.curve.nodes[:i_start+1] + self.curve.nodes[i_end:]
        
        return type(self)(new_data)

    def move_nearest_point(self, pos: Percentage | float) -> Self:
        pos_float = float(pos)
        ik = self(pos_float)
        diff = ik % 1.
        if diff < 0.5:
            i = int(ik)
        else:
            i = int(ik)+1

        new_nodes = self.curve.nodes[:i-1]
        new_nodes.append(self.profilepoint(pos_float))
        new_nodes += self.curve.nodes[i:]

        return type(self)(new_nodes)

    def find_nearest_x_value(self, x: Percentage | float) -> float:
        ik = self.get_ik(x)

        diff = ik % 1.
        if diff < 0.5:
            i = int(ik)
        else:
            i = int(ik)+1
        
        result = self.curve.get(i)[0]

        if x < 0:
            result = -result
        return result

    def apply_function(self, fn: Callable[[openglider.rs.vector.Vector2D, bool], openglider.rs.vector.Vector2D]) -> Self:
        return type(self)([fn(p, i < self.noseindex) for i, p in enumerate(self.curve.nodes)])

    @classmethod
    def fetch(cls, name: str='atr72sm', base_url: str='http://m-selig.ae.illinois.edu/ads/coord/{name}.dat') -> Self:
        import urllib.request
        
        with urllib.request.urlopen(base_url.format(name=name)) as data_file:
            dat_str = data_file.read().decode('utf8')
            return cls._import_dat(dat_str.split("\n"))

    def add_flap(self, begin: float, amount: float) -> Self:
        
        def f(x: float, a: float, b: float) -> float:
            c1, c2, c3 = -a**2*b/(a**2 - 2*a + 1), 2*a*b/(a**2 - 2*a + 1), -b/(a**2 - 2*a + 1)
            if x < a:
                return 0.
            if x > 1:
                return -b
            return c1 + c2 * x + c3 * x**2
        
        new_nodes = []

        for p in self.curve.nodes:
            dy = f(abs(p[0]), begin, amount)
            new_nodes.append(openglider.rs.vector.Vector2D([p[0], p[1]+dy]))
        
        return type(self)(new_nodes, self.name+"_flap")

    @classmethod
    def compute_naca(cls, naca: int=1234, numpoints: int=100) -> Self:
        nodes = compute_naca(naca, numpoints)
        return cls(nodes, name=f"NACA_{naca:04d}").normalized()

    @classmethod
    def compute_trefftz(cls, m: complex=-0.1+0.1j, tau: float=0.05, numpoints: int=100) -> Self:
        airfoil = TrefftzKuttaAirfoil(midpoint=m, tau=tau)

        # find the smallest xvalue to reset the nose
        profile = cls(airfoil.coordinates(numpoints), f"TrefftzKuttaAirfoil_m={m}_tau={tau}")
        return profile.normalized()

    @classmethod
    def compute_joukowsky(cls, m: complex=-0.1+0.1j, numpoints: int=100) -> Self:
        airfoil = JoukowskyAirfoil(m)

        profile = cls(airfoil.coordinates(numpoints), f"joukowsky_{m}")
        return profile.normalized().resample(numpoints)

    @classmethod
    def compute_vandevooren(cls, tau: float=0.05, epsilon: float=0.05, numpoints: int=100) -> Self:
        airfoil = VanDeVoorenAirfoil(tau=tau, epsilon=epsilon)

        profile = cls(airfoil.coordinates(numpoints), f"VanDeVooren_tau={tau}_epsilon={epsilon}")        
        return profile.normalized()
    
    def _repr_svg_(self) -> str:
        result = '<svg baseProfile="full" height="100%" version="1.1" viewBox="-0.1,-0.25,1.2,0.5" width="100%" xmlns="http://www.w3.org/2000/svg">\n'

        result += '<g transform="scale(1,-1)">'
        result += '<polyline stroke="black" stroke-width="0.001" fill="none" points="'

        for p in self.curve.nodes:
            result += f"{p[0]},{p[1]} "
        
        result = result[:-1] + '"></polyline>'

        result += '<polyline stroke="red" stroke-width="0.001" fill="none" points="'

        for p in self.camber_line.nodes:
            result += f"{p[0]},{p[1]} "
        
        result = result[:-1] + '"></polyline>'

        result += '</g></svg>'

        return result
