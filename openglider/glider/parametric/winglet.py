"""
The data of a winglet: what makes it, stored with its glider (see openglider.glider.winglet,
which builds it, places it on the glider and draws its footprint).

A Winglet holds only its planform, its profile and ballooning curves, its profile modifiers,
rib holes and cloth, and where it sits. It has no arc and no angle of attack: it is flat.

Its airfoils and balloonings are entries of the glider's own lists (its Airfoils and
Balloonings sheets), edited with the glider's editors: its two curves run along its span into
these lists, as the glider's own curves do. The glider leaves out the entries at the end of its
lists whose name starts with "winglet" (see ParametricGlider.get_merge_profile).
"""
from __future__ import annotations

import copy

from typing import TYPE_CHECKING

import openglider.rs
from openglider.glider.parametric.arc import ArcCurve
from openglider.glider.parametric.shape import ParametricShape
from openglider.glider.parametric.table import GliderTables
from openglider.glider.parametric.table.material import CellClothTable, RibClothTable
from openglider.glider.parametric.table.rib.holes import HolesTable
from openglider.glider.parametric.table.rib.profile import ProfileModifierTable
from openglider.utils.dataclass import Field, dataclass
from openglider.utils.types import CurveType, SymmetricCurveType

if TYPE_CHECKING:
    from openglider.glider.glider import Glider
    from openglider.glider.parametric.config import ParametricGliderConfig
    from openglider.glider.parametric.glider import ParametricGlider
    from openglider.glider.winglet import WingletGeometry


# the airfoils and balloonings only a winglet uses are named so, at the end of the glider's lists
WINGLET_NAME = "winglet"


def is_winglet_entry(name: str | None) -> bool:
    return bool(name) and str(name).lower().startswith(WINGLET_NAME)


def remove_winglet_entries(glider: ParametricGlider) -> None:
    """take out the airfoils and balloonings only a winglet uses, at the end of the glider's lists"""
    for entries in (glider.profiles, glider.balloonings):
        while len(entries) > 1 and is_winglet_entry(entries[-1].name):
            entries.pop()


def _scale_points(curve: CurveType, x_factor: float, y_factor: float) -> None:
    curve.controlpoints = [[x * x_factor, y * y_factor] for x, y in curve.controlpoints.nodes]  # type: ignore[assignment]


SymmetricBSplineCurve = openglider.rs.spline.SymmetricBSplineCurve


def flat_curve(shape: ParametricShape) -> SymmetricCurveType:
    """a curve at 0 across the span of a shape"""
    half_span = shape.span / 2
    return SymmetricBSplineCurve([[half_span * x, 0.0] for x in (0.25, 0.5, 0.75, 1.0)])


def flat_arc(shape: ParametricShape) -> ArcCurve:
    """a straight arc across the span of a shape"""
    return ArcCurve(flat_curve(shape))


def winglet_config(config: ParametricGliderConfig) -> ParametricGliderConfig:
    """
    the config of a glider, for its winglet: no stabilo cell, its own airfoils. The tip rib is
    closed as the glider's (last_profile_height): flat, as at the tip of a wing
    """
    return config.model_copy(update={"has_stabicell": False, "use_mean_profile": False})


@dataclass
class Winglet:
    shape: ParametricShape
    # along the span of the winglet, into the airfoils and the balloonings of the glider
    # (as the glider's own curves)
    profile_merge_curve: CurveType
    ballooning_merge_curve: CurveType

    profile_modifiers: ProfileModifierTable = Field(default_factory=ProfileModifierTable)
    holes: HolesTable = Field(default_factory=HolesTable)
    material_ribs: RibClothTable = Field(default_factory=RibClothTable)
    material_cells: CellClothTable = Field(default_factory=CellClothTable)

    rib_position: float = 4.5
    chord_start: float = 0.25
    chord_end: float = 0.75
    height: float = 0.3
    # turn of the winglet on the panel about the middle of its root (deg): 0 in line with the
    # cell, negative its nose towards the centre of the glider, positive towards the tip
    angle: float = 0.0

    @property
    def arc(self) -> ArcCurve:
        """a winglet is flat"""
        return flat_arc(self.shape)

    @property
    def aoa(self) -> SymmetricCurveType:
        """and has no angle of attack: it is placed by its root rib"""
        return flat_curve(self.shape)

    def copy(self) -> Winglet:
        return copy.deepcopy(self)

    def get_tables(self) -> GliderTables:
        return GliderTables(
            profile_modifiers=self.profile_modifiers,
            holes=self.holes,
            material_ribs=self.material_ribs,
            material_cells=self.material_cells,
        )

    def get_tables_with_cuts(self) -> GliderTables:
        """its tables and a cut at the nose of every cell: an upper and a lower panel each, as the
        cloth of the panels (material_cells) takes them, upper first"""
        from openglider.glider.parametric.table.cell.cuts import CutTable
        from openglider.utils.table import Table

        table = Table()
        table[0, 0] = "DESIGNM"
        table[1, 0] = "x (1)"
        table[1, 1] = "x (2)"
        for cell in range(len(self.shape.rib_x_values) - 1):
            table[2 + cell, 0] = 0.0
            table[2 + cell, 1] = 0.0

        tables = self.get_tables()
        tables.cuts = CutTable(table)
        return tables

    def get_parametric(self, glider: ParametricGlider) -> ParametricGlider:
        """The winglet as a glider of its own, to build it with the glider pipeline"""
        from openglider.glider.parametric.glider import ParametricGlider

        config = winglet_config(glider.config)

        return ParametricGlider(
            shape=self.shape.copy(),
            arc=self.arc,
            aoa=self.aoa,
            profiles=[profile.copy() for profile in glider.profiles],
            profile_merge_curve=self.profile_merge_curve.copy(),
            balloonings=[ballooning.copy() for ballooning in glider.balloonings],
            ballooning_merge_curve=self.ballooning_merge_curve.copy(),
            config=config,
            allowances=glider.allowances,
            speed=glider.speed,
            glide=glider.glide,
            tables=self.get_tables_with_cuts(),
        )

    def get_geometry(self, glider: ParametricGlider, glider_3d: Glider | None = None) -> WingletGeometry:
        """
        The winglet built at the size it is sewn at: its root as long as its seam on the ballooned
        cloth of the glider, its half span its height. The patterns, the 3d view and the footprint
        all come from it
        """
        from openglider.glider.winglet import WingletGeometry, seam_length

        if glider_3d is None:
            glider_3d = glider.get_glider_3d()
        return WingletGeometry(self, self.scaled(seam_length(self, glider_3d), self.height).get_parametric(glider).get_glider_3d())

    def scaled(self, root_chord: float, half_span: float) -> Winglet:
        """the same winglet, its root chord and its half span set"""
        new = self.copy()
        shape = new.shape
        span_factor = 2 * half_span / shape.span
        chord_factor = root_chord / shape.chords[0]
        _scale_points(shape.front_curve, span_factor, chord_factor)
        _scale_points(shape.back_curve, span_factor, chord_factor)
        _scale_points(new.profile_merge_curve, span_factor, 1.)
        _scale_points(new.ballooning_merge_curve, span_factor, 1.)
        shape._clean()
        return new
