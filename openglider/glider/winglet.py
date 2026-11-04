"""
Winglets: a small sail of its own, sewn by its root rib flat onto the upper
surface of the glider, and set on both sides.

The Winglet (openglider.glider.parametric.winglet) holds only what makes it: its
planform, its profile and ballooning curves into the glider's own lists, its
profile modifiers, rib holes and cloth. This module builds it for its glider
(WingletGeometry): where it sits, its footprint, its 3d mesh, its shape in place
for the patterns.

It is placed by these settings:

    rib_position   span position in ribs, counted from the tip rib
                   (4.445: inside the cell between the ribs 4 and 5 from the tip)
    chord_start    chord position the root of the winglet starts at (its nose)
    chord_end      chord position it ends at (its trailing edge)
    height         height of the winglet, its half span (m)
    angle          its turn on the panel about the middle of its root (deg): negative its
                   nose towards the centre of the glider, positive towards the tip

The root airfoil is laid on the upper surface between the two chord positions:
its chord along the chord of the glider, its thickness across the span. That
outline is the footprint the winglet is sewn on. The winglet is built at the size
it is sewn at: its root as long as the seam on the ballooned cloth.
"""
from __future__ import annotations

import dataclasses
import logging
import math
import os
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import openglider.airfoil
import openglider.mesh
import openglider.rs
from openglider.airfoil import get_x_value
from openglider.glider.parametric.winglet import WINGLET_NAME, Winglet, remove_winglet_entries
from openglider.utils.table import Table
from openglider.vector.unit import Percentage

if TYPE_CHECKING:
    from openglider.airfoil.profile_3d import Profile3D
    from openglider.glider.cell.cell import Cell, FlattenedCell
    from openglider.glider.glider import Glider
    from openglider.glider.parametric.glider import ParametricGlider
    from openglider.glider.project import GliderProject
    from openglider.mesh import Mesh

logger = logging.getLogger(__name__)

Vector2D = openglider.rs.vector.Vector2D
Vector3D = openglider.rs.vector.Vector3D
PolyLine2D = openglider.rs.vector.PolyLine2D
ORIGIN = Vector2D([0, 0])


@dataclasses.dataclass
class WingletGeometry:
    """A winglet built for its glider: where it sits, its footprint, its mesh"""
    winglet: Winglet
    glider_3d: Glider

    @classmethod
    def from_project(cls, project: GliderProject) -> WingletGeometry | None:
        """The winglet of a glider, None if it has none"""
        if project.glider.winglet is None:
            return None
        return project.glider.winglet.get_geometry(project.glider, project.get_glider_3d())

    @property
    def rib_position(self) -> float:
        return self.winglet.rib_position

    @property
    def chord_start(self) -> float:
        return self.winglet.chord_start

    @property
    def chord_end(self) -> float:
        return self.winglet.chord_end

    @property
    def height(self) -> float:
        return self.winglet.height

    @property
    def angle(self) -> float:
        return self.winglet.angle

    def get_cell(self, glider: Glider) -> tuple[int, float]:
        """The cell the winglet is on and its span position inside the cell (0: rib1, 1: rib2)"""
        return winglet_cell(self.winglet, glider)

    def get_root_airfoil(self) -> PolyLine2D:
        """The airfoil of the root rib of the winglet, chord 1 from the nose (0) to the trailing edge (1)"""
        return self.glider_3d.ribs[0].profile_2d.curve

    def get_footprint(
        self,
        flattened_cell: FlattenedCell,
        x_distribution: list[float],
        span_position: float,
    ) -> PolyLine2D:
        """
        The outline the root of the winglet covers on the flattened cell: the root airfoil from
        chord_start to chord_end along the chord line at span_position. The upper surface runs
        over the negative chord positions, the nose of the winglet is the forward end.
        """
        line = flattened_cell.at_position(Percentage(span_position))
        ik_nose = get_x_value(x_distribution, -self.chord_start)
        ik_tail = get_x_value(x_distribution, -self.chord_end)
        chord_line = line.get(min(ik_nose, ik_tail), max(ik_nose, ik_tail))
        if ik_nose > ik_tail:
            chord_line = chord_line.reverse()

        length = chord_line.get_length()
        step = length / 1000
        rotation = openglider.rs.vector.Rotation2D(math.pi / 2)

        nodes = []
        for x, y in self.get_root_airfoil().nodes:
            distance = min(max(x, 0.), 1.) * length
            ik = chord_line.walk(0, distance)
            ik_before = chord_line.walk(0, max(distance - step, 0.))
            ik_after = chord_line.walk(0, min(distance + step, length))
            tangent = (chord_line.get(ik_after) - chord_line.get(ik_before)).normalized()
            nodes.append(chord_line.get(ik) + rotation.apply(tangent) * (y * length))

        # turned by the angle about the middle of the root, as the winglet: towards the tip is
        # where the cell runs on (the next span position)
        middle = chord_line.get(chord_line.walk(0, length / 2))
        along = (chord_line.get(len(chord_line) - 1) - chord_line.get(0)).normalized()
        ahead = flattened_cell.at_position(Percentage(min(span_position + 0.01, 1.)))
        behind = flattened_cell.at_position(Percentage(max(span_position - 0.01, 0.)))
        ik_middle = get_x_value(x_distribution, -(self.chord_start + self.chord_end) / 2)
        towards_tip = ahead.get(ik_middle) - behind.get(ik_middle)
        across = rotation.apply(along)
        if across.dot(towards_tip) < 0:
            across = across * -1.

        return PolyLine2D(_turn(nodes, middle, along, across, self.angle)).close()

    def _get_surface_frame(self, cell: Cell, span_position: float) -> tuple[Vector3D, Vector3D, Vector3D, Vector3D, float]:
        """
        Where the root of the winglet sits on the upper surface: the point of its nose, the
        chord direction (nose to tail), the outward normal and the spanwise direction across,
        and the distance from nose to tail
        """
        x_values = cell.rib1.profile_2d.x_values
        ik_nose = get_x_value(x_values, -self.chord_start)
        ik_tail = get_x_value(x_values, -self.chord_end)
        ik_lower = get_x_value(x_values, self.chord_start)

        profile = cell.midrib(span_position)
        nose = profile[ik_nose]
        tail = profile[ik_tail]
        chord = (tail - nose).normalized()

        step = 0.01
        span = (cell.midrib(min(span_position + step, 1.))[ik_nose] - cell.midrib(max(span_position - step, 0.))[ik_nose]).normalized()
        normal = chord.cross(span).normalized()
        # outwards: away from the lower surface below the nose
        if normal.dot(nose - profile[ik_lower]) < 0:
            normal = normal * -1.
        across = normal.cross(chord).normalized()

        return nose, chord, normal, across, (tail - nose).length()

    def get_placement(self, glider: Glider) -> Callable[[Vector3D], Vector3D]:
        """
        Where a point of the winglet (as built, glider_3d) goes on the right half of the glider.
        Its root lies on the ballooned cloth of the panel: along the seam, from chord_start to
        chord_end, and across the cell, turned by the angle about the middle of the root. Every
        point stands on the cloth below it, its height on top, square to the panel
        """
        cell_index, span_position = self.get_cell(glider)
        cell = glider.cells[cell_index]
        _, chord, normal, across, _ = self._get_surface_frame(cell, span_position)
        side = 1. if across.dot(cell.rib2.align(ORIGIN) - cell.rib1.align(ORIGIN)) > 0 else -1.
        turn = math.radians(self.angle)
        cos, sin = math.cos(turn), math.sin(turn)

        # the frame of the root rib: chord, thickness, and the span outwards
        winglet = self.glider_3d
        root = winglet.ribs[0]
        root_nose = root.align(ORIGIN)
        root_chord = root.align(Vector2D([1, 0])) - root_nose
        root_length = root_chord.length()
        local_x = root_chord.normalized()
        local_z = root.align(Vector2D([0, 1])) - root_nose
        local_z = (local_z - local_x * local_z.dot(local_x)).normalized()
        local_y = local_z.cross(local_x).normalized()
        if local_y.dot(winglet.ribs[-1].align(ORIGIN) - root_nose) < 0:
            local_y = local_y * -1.

        # built at the size it is sewn at (Winglet.get_geometry): only the height is set here
        span_extent = max((p - root_nose).dot(local_y) for rib in winglet.ribs for p in rib.get_profile_3d().curve.nodes)
        span_scale = self.height / span_extent
        surface = _Surface(glider, cell_index, span_position, self.chord_start, self.chord_end)

        # the root is sewn on the ballooned cloth, the ribs above it stay as they are: the cloth
        # of the first cell goes from one to the other, it is stretched where the root follows
        # the ballooning. From the second rib up, the winglet is straight, square to the panel
        outwards = across * side
        middle = surface.get(0.5, 0.)
        first_rib = (winglet.ribs[1].align(ORIGIN) - root_nose).dot(local_y) * span_scale if len(winglet.ribs) > 1 else 0.

        def place(point: Vector3D) -> Vector3D:
            v = point - root_nose
            # on the seam from its middle (m), and across the cell (m)
            along = v.dot(local_x) - root_length / 2
            off = side * v.dot(local_z)
            along, off = along * cos + off * sin, off * cos - along * sin
            height = v.dot(local_y) * span_scale

            on_cloth = surface.get(along / root_length + 0.5, off)
            straight = middle + chord * along + outwards * off
            sewn = max(0., 1. - height / first_rib) if first_rib > 0 else 1.
            return straight + (on_cloth - straight) * sewn + normal * height

        return place

    def get_placed_glider(self, glider: Glider) -> Glider:
        """
        The winglet as a glider, in place on the cloth: its cells give their sections (midrib)
        where the placement puts them. Its panels are flattened from that shape, the one of the
        3d view, stretched where the root follows the ballooning
        """
        placed = self.glider_3d.copy()
        place = self.get_placement(glider)

        for cell in placed.cells:
            def midrib(y: float, *args: Any, _midrib: Callable[..., Profile3D] = cell.midrib, **kwargs: Any) -> Profile3D:
                profile = _midrib(y, *args, **kwargs)
                return type(profile)(
                    curve=openglider.rs.vector.PolyLine3D([place(p) for p in profile.curve.nodes]),
                    x_values=profile.x_values,
                    name=profile.name,
                )
            # on the instance, the cell model takes no field of that name
            object.__setattr__(cell, "midrib", midrib)

        return placed

    def get_mesh(self, glider: Glider, numribs: int = 3, panels: bool = True, ribs: bool = True) -> Mesh:
        """The winglet in place on the right half (see get_placement): its panels and ribs"""
        winglet = self.glider_3d
        mesh = openglider.mesh.Mesh()
        if panels:
            for cell in winglet.cells:
                for panel in cell.panels:
                    mesh += panel.get_mesh(cell, numribs=numribs)
        if ribs:
            for rib in winglet.ribs:
                try:
                    mesh += rib.get_mesh(filled=True)
                except (KeyboardInterrupt, SystemExit):
                    raise
                except BaseException as e:
                    # the rust triangulation panics on holes that touch: leave the rib out,
                    # as the glider's own ribs are in the 3d view
                    logger.error(f"could not mesh rib {rib.name} of the winglet, check its holes: {e}")
        if not mesh.get_indexed()[0]:
            return mesh

        place = self.get_placement(glider)
        vertices, polygons, boundaries = mesh.get_indexed()
        placed = [place(v) for v in vertices]

        # get_indexed leaves out the colour of each object: back in its name, as from_indexed reads it
        colours = {obj.name: obj.color for obj in mesh.objects}
        coloured: dict[str, Sequence[tuple[Any, Any]]] = {
            f"{name}#{''.join(f'{c:02x}' for c in colours[name])}" if name in colours else name: polys
            for name, polys in polygons.items()
        }

        return openglider.mesh.Mesh.from_indexed(placed, coloured, boundaries, name="winglet")


class _Surface:
    """
    The ballooned upper surface around the winglet: by the part of the way from chord_start to
    chord_end and the distance across the span from the middle of the root (m), over the cell
    of the winglet and the ones next to it
    """
    steps = 40

    def __init__(self, glider: Glider, cell_index: int, span_position: float, chord_start: float, chord_end: float):
        cell = glider.cells[cell_index]
        self.x_values = cell.rib1.profile_2d.x_values
        self.chord_start = chord_start
        self.chord_end = chord_end

        # span positions over the home cell (0 to 1) and the ones next to it, from -1 to 2
        self.spans = [-1 + 3 * i / self.steps for i in range(self.steps + 1)]
        self.lines = []
        for span in self.spans:
            index = min(max(cell_index + math.floor(span), 0), len(glider.cells) - 1)
            local = min(max(span - (index - cell_index), 0.), 1.)
            self.lines.append(glider.cells[index].midrib(local).curve)

        ik_middle = get_x_value(self.x_values, -(chord_start + chord_end) / 2)
        self.width = (cell.midrib(1.)[ik_middle] - cell.midrib(0.)[ik_middle]).length()
        self.span_position = span_position

    def get(self, along: float, across: float) -> Vector3D:
        x = self.chord_start + (self.chord_end - self.chord_start) * along
        ik = get_x_value(self.x_values, -min(max(x, 0.), 1.))
        span = min(max(self.span_position + across / self.width, self.spans[0]), self.spans[-1])

        position = (span - self.spans[0]) / (self.spans[1] - self.spans[0])
        i = min(int(position), self.steps - 1)
        t = position - i
        return self.lines[i].get(ik) * (1 - t) + self.lines[i + 1].get(ik) * t


def winglet_cell(winglet: Winglet, glider: Glider) -> tuple[int, float]:
    """The cell a winglet is on and its span position inside the cell (0: rib1, 1: rib2)"""
    rib_index = len(glider.ribs) - 1 - winglet.rib_position
    if not 0 <= rib_index <= len(glider.ribs) - 1:
        raise ValueError(f"winglet rib position {winglet.rib_position} is outside the glider ({len(glider.ribs)} ribs)")

    cell_index = min(math.floor(rib_index), len(glider.cells) - 1)
    return cell_index, rib_index - cell_index


def seam_length(winglet: Winglet, glider: Glider) -> float:
    """how long the seam of the root of a winglet is: along the ballooned cloth, chord_start to chord_end"""
    cell_index, span_position = winglet_cell(winglet, glider)
    cell = glider.cells[cell_index]
    x_values = cell.rib1.profile_2d.x_values
    start, end = sorted((get_x_value(x_values, -winglet.chord_start), get_x_value(x_values, -winglet.chord_end)))
    return cell.midrib(span_position).curve.get(start, end).get_length()


def _turn(
    points: Sequence[Vector2D], middle: Vector2D, along: Vector2D, towards_tip: Vector2D, angle: float
) -> list[Vector2D]:
    """points turned about middle by angle (deg), negative taking along towards -towards_tip"""
    turn = math.radians(angle)
    turned_along = along * math.cos(turn) - towards_tip * math.sin(turn)
    turned_across = towards_tip * math.cos(turn) + along * math.sin(turn)
    return [
        middle + turned_along * (p - middle).dot(along) + turned_across * (p - middle).dot(towards_tip)
        for p in points
    ]


# the default winglet: 0.50m across, 0.96m of chord at the root, on CLARK-Y.dat (symmetric, 18%)
DEFAULT_AIRFOIL = os.path.join(os.path.dirname(openglider.airfoil.__file__), "CLARK-Y.dat")
DEFAULT_FRONT = [[0.041304, 0.0], [0.123914, -0.092934], [0.206529, -0.254956], [0.247839, -0.368344]]
DEFAULT_BACK = [[0.041304, -0.961746], [0.123914, -0.904771], [0.206529, -0.84982], [0.247839, -0.814893]]
DEFAULT_RIB_DISTRIBUTION = [[0.0, 0.0], [0.5, 0.5], [1.0, 1.0]]
DEFAULT_CELLS = 8
DEFAULT_BALLOONING: list[tuple[float, float]] = [
    (-1.0, 0.017419), (-0.971018, 0.068938), (-0.558334, 0.067249), (-0.137697, 0.063402),
    (-0.066306, 0.021961), (-0.016858, -0.00018), (0.100426, -8.3e-05), (0.19006, 0.058565),
    (0.461139, 0.057777), (0.943449, 0.054523), (1.0, 0.017419),
]
# where it sits: rib_position, chord_start, chord_end, height, angle
DEFAULT_PLACEMENT = (7.5, 0.3, 0.8, 0.248, 0.0)
# hard finish ribs with holes as the ribs of the demowing that carry no lines, blue panels
DEFAULT_RIB_CLOTH = "porcher.skytex_40_hf"
DEFAULT_PANEL_CLOTH = "porcher.skytex_38.royal_blue"
DEFAULT_HOLE_HEADERS = ["start", "end", "height", "num_holes", "border_width", "margin"]


def _holes(num_holes: int) -> list[Any]:
    return [0.15, 0.75, 0.85, num_holes, "2cm", 0.03]


def _rib_table(keyword: str, headers: list[str], rows: dict[int, list[Any]]) -> Table:
    """a table of rib (or cell) elements: the keyword, its headers, a row per rib from row 2"""
    table = Table()
    table[0, 0] = keyword
    for column, header in enumerate(headers):
        table[1, column] = header
    for rib, values in rows.items():
        for column, value in enumerate(values):
            table[2 + rib, column] = value
    return table


def default_winglet(glider: ParametricGlider) -> Winglet:
    """
    The default winglet of a glider: its rib holes and cloth, its panel cloth filled in. Its airfoil
    and ballooning go to the end of the glider's lists (named "winglet ..."), after the airfoils
    and balloonings only a winglet it had used are taken out
    """
    from openglider.airfoil import Profile2D
    from openglider.glider.ballooning.new import BallooningBezierNeu
    from openglider.glider.parametric.shape import ParametricShape
    from openglider.glider.parametric.table.material import CellClothTable, RibClothTable
    from openglider.glider.parametric.table.rib.holes import HolesTable
    from openglider.glider.parametric.winglet import winglet_config

    remove_winglet_entries(glider)

    airfoil = Profile2D.import_from_dat(DEFAULT_AIRFOIL)
    airfoil.name = f"{WINGLET_NAME} 1"
    glider.profiles.append(airfoil)
    glider.balloonings.append(BallooningBezierNeu(DEFAULT_BALLOONING, name=WINGLET_NAME))

    spline = openglider.rs.spline
    shape = ParametricShape(
        spline.SymmetricBSplineCurve(DEFAULT_FRONT),
        spline.SymmetricBSplineCurve(DEFAULT_BACK),
        spline.BSplineCurve(DEFAULT_RIB_DISTRIBUTION),
        DEFAULT_CELLS,
        config=winglet_config(glider.config),
    )
    ribs = len(shape.rib_x_values)
    rib_position, chord_start, chord_end, height, angle = DEFAULT_PLACEMENT

    def along_span(value: float) -> openglider.rs.spline.SymmetricBSplineCurve:
        return spline.SymmetricBSplineCurve([[x, value] for x, _ in DEFAULT_FRONT])

    # the upper and the lower panel of every cell
    panel_cloth = _rib_table("MATERIAL", ["Name"], {cell: [DEFAULT_PANEL_CLOTH] for cell in range(ribs - 1)})
    panel_cloth.append_right(_rib_table("MATERIAL", ["Name"], {cell: [DEFAULT_PANEL_CLOTH] for cell in range(ribs - 1)}))
    # all but the flat tip, fewer holes on the smaller rib before it
    holes = {rib: _holes(4 if rib < ribs - 2 else 3) for rib in range(ribs - 1)}

    return Winglet(
        shape=shape,
        profile_merge_curve=along_span(len(glider.profiles) - 1),
        ballooning_merge_curve=along_span(len(glider.balloonings) - 1),
        holes=HolesTable(_rib_table("HOLESQMULTI6", DEFAULT_HOLE_HEADERS, holes)),
        material_ribs=RibClothTable(_rib_table("MATERIAL", ["Name"], {rib: [DEFAULT_RIB_CLOTH] for rib in range(ribs)})),
        material_cells=CellClothTable(panel_cloth),
        rib_position=rib_position,
        chord_start=chord_start,
        chord_end=chord_end,
        height=height,
        angle=angle,
    )


def add_default_winglet(glider: ParametricGlider) -> Winglet:
    """Give a glider the default winglet (see default_winglet)"""
    winglet = default_winglet(glider)
    glider.winglet = winglet
    return winglet
