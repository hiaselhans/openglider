from __future__ import annotations

import copy
import logging
import math
from typing import TYPE_CHECKING
from collections.abc import Callable

import euklid
from openglider.glider.parametric.config import ParametricGliderConfig, SewingAllowanceConfig
from openglider.glider.parametric.table.base.parser import Parser
import openglider.materials
import pyfoil
from openglider.glider.ballooning.base import BallooningBase
from openglider.glider.ballooning.new import BallooningBezierNeu
from openglider.glider.cell import Cell
from openglider.glider.cell.panel import Panel, PanelCut, PANELCUT_TYPES
from openglider.glider.glider import Glider
from openglider.glider.parametric.arc import ArcCurve
from openglider.glider.parametric.export_ods import export_ods_2d
from openglider.glider.parametric.fitglider import fit_glider_3d
from openglider.glider.parametric.import_ods import import_ods_2d
from openglider.glider.parametric.shape import ParametricShape
from openglider.glider.parametric.table import GliderTables
from openglider.glider.rib import Rib, SingleSkinRib
from openglider.utils import ZipCmp
from openglider.utils.cache import cached_property
from openglider.utils.dataclass import dataclass, Field
from openglider.utils.distribution import Distribution
from openglider.utils.table import Table
from openglider.utils.types import CurveType, SymmetricCurveType
from openglider.vector.unit import Percentage

if TYPE_CHECKING:
    from openglider.glider.curve import GliderCurveType

logger = logging.getLogger(__name__)


@dataclass
class ParametricGlider:
    """
    A parametric (2D) Glider object used for gui input
    """
    shape: ParametricShape
    arc: ArcCurve
    aoa: SymmetricCurveType
    profiles: list[pyfoil.Airfoil]
    profile_merge_curve: CurveType
    balloonings: list[BallooningBase]
    ballooning_merge_curve: CurveType
    config: ParametricGliderConfig
    allowances: SewingAllowanceConfig
    speed: float
    glide: float
    tables: GliderTables = Field(default_factory=lambda: GliderTables())
    zrot: SymmetricCurveType = Field(default_factory=lambda: euklid.spline.SymmetricBSplineCurve([[0,0],[1,0]]))

    num_interpolate: int=30
    num_profile: int | None=None

    @classmethod
    def import_ods(cls, path: str) -> ParametricGlider:
        return import_ods_2d(cls, path)

    export_ods = export_ods_2d

    def copy(self) -> ParametricGlider:
        return copy.deepcopy(self)

    def get_geomentry_table(self) -> Table:
        table = Table()
        table.insert_row(["", "Ribs", "Chord", "X", "Y", "%", "Arc", "Arc_diff", "AOA", "Z-rotation", "Y-rotation", "profile-merge", "ballooning-merge"])
        shape = self.shape.get_half_shape()
        for rib_no in range(self.shape.half_rib_num):
            table[1+rib_no, 1] = rib_no+1

        for rib_no, chord in enumerate(shape.chords):
            table[1+rib_no, 2] = chord

        for rib_no, p in enumerate(self.shape.baseline):
            table[1+rib_no, 3] = p[0]
            table[1+rib_no, 4] = p[1]
            table[1+rib_no, 5] = self.shape.baseline_pos

        last_angle = 0.
        for cell_no, angle in enumerate(self.get_arc_angles()):
            angle = angle * 180 / math.pi
            table[1+cell_no, 6] = angle
            table[1+cell_no, 7] = angle - last_angle
            last_angle = angle

        for rib_no, aoa in enumerate(self.get_aoa()):
            table[1+rib_no, 8] = aoa * 180 / math.pi
            table[1+rib_no, 9] = 0
            table[1+rib_no, 10] = 0

        return table

    def get_arc_angles(self) -> list[float]:
        """
        Get rib rotations
        """
        return self.arc.get_rib_angles(self.shape.rib_x_values)

    def merge_ballooning(self, factor: float, multiplier: float) -> BallooningBase:
        factor = max(0, min(len(self.balloonings)-1, factor))
        k = factor % 1
        i = int(factor // 1)
        first = self.balloonings[i]
        if k > 0:
            second = self.balloonings[i + 1]
            result = first * (1 - k) + second * k
        else:
            result = first
        
        return result * multiplier

    def get_merge_profile(self, factor: float) -> pyfoil.Airfoil:
        factor = max(0, min(len(self.profiles)-1, factor))
        k = factor % 1
        i = int(factor // 1)
        first = self.profiles[i]

        if k > 0:
            second = self.profiles[i + 1]
            airfoil = first * (1 - k) + second * k
        else:
            airfoil = first.copy()
        return airfoil

    def get_curves(self) -> dict[str, GliderCurveType]:
        return self.tables.curves.get_curves(self.shape.get_half_shape())

    def get_panels(self, glider_3d: Glider | None=None) -> list[list[Panel]]:
        """
        Create Panels Objects and apply on gliders cells if provided, otherwise create a list of panels
        :param glider_3d: (optional)
        :return: list of "cells"
        """
        resolvers = self.resolvers

        cells: list[list[Panel]]

        if glider_3d is None:
            cells = [[] for _ in range(self.shape.half_cell_num)]
        else:
            cells = [cell.panels for cell in glider_3d.cells]

        for cell_no, panel_lst in enumerate(cells):
            panel_lst.clear()

            cuts: list[PanelCut] = self.tables.cuts.get(cell_no, allowance=self.allowances.design, resolvers=resolvers)

            for cut in cuts:
                if cut.cut_type == PANELCUT_TYPES.folded:
                    cut.seam_allowance = self.allowances.entry

            all_values = [c.x_left for c in cuts] + [c.x_right for c in cuts]

            if -1 not in all_values:
                cuts.append(PanelCut(
                    x_left=Percentage(-1),
                    x_right=Percentage(-1),
                    cut_type=PANELCUT_TYPES.parallel,
                    seam_allowance=self.allowances.trailing_edge
                ))
            
            if 1 not in all_values:
                cuts.append(PanelCut(
                    x_left=Percentage(1),
                    x_right=Percentage(1),
                    cut_type=PANELCUT_TYPES.parallel,
                    seam_allowance=self.allowances.trailing_edge
                ))

            cuts.sort(key=lambda cut: cut.get_average_x())

            i = 0
            materials = self.tables.material_cells.get(cell_no)

            for cut1, cut2 in ZipCmp(cuts):
                
                if cut1.x_right > cut2.x_right or cut1.x_left > cut2.x_left:
                    error_str = "Invalid cut: C{} {:.02f}/{:.02f}/{} + {:.02f}/{:.02f}/{}".format(
                        cell_no+1,
                        cut1.x_left, cut1.x_right, cut1.cut_type,
                        cut2.x_left, cut2.x_right, cut2.cut_type
                    )
                    raise ValueError(error_str)

                if cut1.cut_type == cut2.cut_type:
                    if cut1.cut_type in (PANELCUT_TYPES.folded, PANELCUT_TYPES.singleskin):
                        continue

                try:
                    material = materials[i]
                except (KeyError, IndexError):
                    #logger.warning(f"No material for panel {cell_no}/{i+1}")
                    material = openglider.materials.Material(name="unknown")
                
                i += 1

                if material is not None:
                    panel = Panel(cut1, cut2,
                                name=f"c{cell_no+1}p{len(panel_lst)+1}",
                                material=material)
                    panel_lst.append(panel)


        return cells

    def apply_diagonals(self, glider: Glider) -> None:
        resolvers = self.resolvers

        for cell_no, cell in enumerate(glider.cells):
            cell.diagonals = self.tables.diagonals.get(row_no=cell_no, resolvers=resolvers)

            cell.diagonals.sort(key=lambda strap: strap.get_average_x())

            for strap_no, strap in enumerate(cell.diagonals):
                strap.name = "c{}{}{}".format(cell_no+1, "d", strap_no)

            cell.straps = self.tables.straps.get(row_no=cell_no, resolvers=resolvers)
            cell.straps.sort(key=lambda strap: strap.get_average_x())

            for strap_no, strap in enumerate(cell.diagonals):
                strap.name = "c{}{}{}".format(cell_no+1, "s", strap_no)

    @classmethod
    def fit_glider_3d(cls, glider: Glider, numpoints: int=3) -> ParametricGlider:
        return fit_glider_3d(cls, glider, numpoints)

    def get_aoa(self, interpolation_num: int | None=None) -> list[float]:
        aoa_interpolation = euklid.vector.Interpolation(self.aoa.get_sequence(interpolation_num or self.num_interpolate).nodes)

        return [aoa_interpolation.get_value(abs(x)) for x in self.shape.rib_x_values]

    def apply_aoa(self, glider: Glider) -> None:
        aoa_values = self.get_aoa()

        for rib, aoa in zip(glider.ribs, aoa_values):
            rib.set_aoa_relative(aoa)

    def get_profile_merge_values(self) -> list[float]:
        profile_merge_curve = euklid.vector.Interpolation(self.profile_merge_curve.get_sequence(self.num_interpolate).nodes)
        return [profile_merge_curve.get_value(abs(x)) for x in self.shape.rib_x_values]

    def get_ballooning_merge(self) -> list[tuple[float, float]]:
        ballooning_merge_curve = euklid.vector.Interpolation(self.ballooning_merge_curve.get_sequence(self.num_interpolate).nodes)
        factors = [ballooning_merge_curve.get_value(abs(x)) for x in self.shape.cell_x_values]

        table = self.tables.ballooning_modifiers

        if table is not None:
            all_factors = table.get_merge_factors(factors)
        else:
            all_factors = [(factor, 1) for factor in factors]

        return [(max(0, x), y) for x,y in all_factors]

    def apply_shape_and_arc(self, glider: Glider) -> None:
        x_values = [abs(x) for x in self.shape.rib_x_values]
        shape_ribs = self.shape.ribs

        arc_pos = list(self.arc.get_arc_positions(x_values))
        rib_angles = self.arc.get_rib_angles(x_values)

        offset_x = shape_ribs[0][0][1]

        for rib_no, x in enumerate(x_values):
            front, back = shape_ribs[rib_no]
            arc = arc_pos[rib_no]
            startpoint = euklid.vector.Vector3D([-front[1] + offset_x, arc[0], arc[1]])
            rib = glider.ribs[rib_no]

            rib.pos = startpoint
            rib.chord = abs(front[1]-back[1])
            rib.arcang = rib_angles[rib_no]

    @cached_property('tables.curves', 'shape')
    def resolvers(self) -> list[Parser]:
        parsers = []
        curves=self.get_curves()

        def resolver_factory(rib_no: int) -> Callable[[str], float]:
            def resolve(name: str) -> float:
                if name not in curves:
                    raise ValueError(
                        f"could not resolve name '{name}' "+
                        f"(available curves: {list(curves.keys())})"
                    )
                return curves[name].get(rib_no)

            return resolve


        for rib_no, chord in enumerate(self.shape.chords):
            parsers.append(Parser(
                variable_resolver=resolver_factory(rib_no)
            ))
        
        return parsers
    
    def get_profiles(self, num_profile: int | None=None) -> list[pyfoil.Airfoil]:
        num_profile = num_profile or self.num_profile

        if num_profile is not None:
            airfoil_distribution = list(Distribution.from_cos_distribution(num_profile))
        else:
            airfoil_distribution = self.profiles[0].x_values

        balloonings = None
        if self.config.use_mean_profile:
            balloonings = self.apply_ballooning()

        x_values = self.shape.rib_x_values
        cell_widths = [x2-x1 for x2, x1 in zip(x_values[:-1], x_values[1:])]
        rib_chords = self.shape.chords

        if self.shape.has_center_cell:
            x_values = x_values[1:]
            rib_chords = rib_chords[1:]

        profile_merge_curve = euklid.vector.Interpolation(self.profile_merge_curve.get_sequence(self.num_interpolate).nodes)
        
        result: list[pyfoil.Airfoil] = []

        for rib_no, x_value in enumerate(x_values):
            merge_factor, scale_factor = self.tables.profile_modifiers.get_factors(rib_no)

            if merge_factor is not None:
                factor = merge_factor
            else:
                factor = profile_merge_curve.get_value(abs(x_value))

            profile = self.get_merge_profile(factor)


            if scale_factor is not None:
                profile = profile.set_thickness(profile.thickness * scale_factor)
            
            if self.config.use_mean_profile:
                assert balloonings is not None  # satisfy type-checker

                if rib_no == 0 and not self.shape.has_center_cell:
                    # center rib => use only the ballooning from the outside
                    arc_height = [balloonings[0].get_mean_height(x) * cell_widths[0] for x in profile.x_values]
                else:
                    left_cell_index = rib_no
                    if self.shape.has_center_cell:
                        left_cell_index -= 1
                    
                    arc_height = [
                        (
                            balloonings[left_cell_index].get_mean_height(x) * cell_widths[left_cell_index] + 
                            balloonings[left_cell_index+1].get_mean_height(x) * cell_widths[left_cell_index+1]
                        )/2
                        for x in profile.x_values
                    ]
                
                profile = BallooningBase.apply_height_to_airfoil(profile, [x/rib_chords[rib_no] for x in arc_height])

            profile.name = f"Profile{rib_no+1}"

            if flap := self.tables.profile_modifiers.get_flap(rib_no):
                logger.debug(f"add flap: {flap}")
                profile = profile.add_flap(**flap)

            result.append(profile.set_x_values(airfoil_distribution))

        if self.shape.has_center_cell:
            mirrored_profile = result[0].copy()
            result.insert(0, mirrored_profile)


        return result

    def get_glider_3d(self, glider: Glider=None, num: int=50, num_profile: int | None=None) -> Glider:
        """returns a new glider from parametric values"""
        logger.debug("get glider 3d")
        glider = glider or Glider()
        ribs = []

        logger.debug("apply curves")
        self.rescale_curves()
        curves = self.get_curves()
        resolvers = self.resolvers

        x_values = self.shape.rib_x_values
        shape_ribs = self.shape.ribs

        aoa_values = self.get_aoa()
        zrot_int = euklid.vector.Interpolation(self.zrot.get_sequence(num).nodes)

        arc_pos = self.arc.get_arc_positions(x_values).tolist()
        rib_angles = self.arc.get_rib_angles(x_values)
        profiles = self.get_profiles(num_profile=num_profile)

        offset_x = shape_ribs[0][0][1]

        logger.info("create ribs")

        for rib_no, x_value in enumerate(x_values):
            front, back = shape_ribs[rib_no]
            arc = arc_pos[rib_no]
            profile = profiles[rib_no]

            startpoint = euklid.vector.Vector3D([-front[1] + offset_x, arc[0], arc[1]])

            try:
                material = self.tables.material_ribs.get(rib_no)[0]
            except (KeyError, IndexError):
                logger.warning(f"no material set for rib: {rib_no+1}")
                material = openglider.materials.Material.default()

            chord = abs(front[1]-back[1])

            sharknose = self.tables.profile_modifiers.get_sharknose(rib_no, resolvers=resolvers)

            this_rib_holes = self.tables.holes.get(rib_no, resolvers=resolvers)
            this_rigid_foils = self.tables.rigidfoils_rib.get(rib_no, resolvers=resolvers)

            data = {
                "trailing_edge_extra": self.allowances.trailing_edge,
            }
            data.update(self.tables.rib_modifiers.get_rib_args(rib_no, resolvers=resolvers))

            rib = Rib(
                profile_2d=profile,
                pos=startpoint,
                chord=chord,
                arcang=rib_angles[rib_no],
                xrot=self.tables.rib_modifiers.get_xrot(rib_no),
                offset=self.tables.rib_modifiers.get_offset(rib_no, resolvers=resolvers),
                glide=self.glide,
                aoa_absolute=aoa_values[rib_no],
                zrot=zrot_int.get_value(abs(x_value)),
                holes=this_rib_holes,
                rigidfoils=this_rigid_foils,
                name=f"rib{rib_no}",
                material=material,
                sharknose=sharknose,
                attachment_points=[],
                seam_allowance=self.allowances.general,
                **data  # type: ignore
            )
            rib.set_aoa_relative(aoa_values[rib_no])

            singleskin_data = self.tables.rib_modifiers.get_singleskin_ribs(rib_no, resolvers=resolvers)
            if singleskin_data:
                rib = SingleSkinRib.from_rib(rib, *singleskin_data)
            
            attachment_points = self.tables.attachment_points_rib.get(rib_no, rib=rib, resolvers=resolvers)
            for p in rib.attachment_points:
                p.get_position(rib)
            rib.attachment_points = attachment_points

            ribs.append(rib)

        logger.info("create cells")

        ballooning_factors = self.get_ballooning_merge()
        glider.cells = []
        for cell_no, (rib1, rib2) in enumerate(zip(ribs[:-1], ribs[1:])):

            ballooning_factor = ballooning_factors[cell_no]
            ballooning = self.merge_ballooning(*ballooning_factor)
            
            cell = Cell(
                rib1=rib1,
                rib2=rib2,
                ballooning=ballooning,
                name=f"c{cell_no+1}",
                attachment_points=[],
                ballooning_modifiers=self.tables.ballooning_modifiers.get_modifiers(cell_no, resolvers=resolvers)
                )

            attachment_points = self.tables.attachment_points_cell.get(cell_no, curves=curves, cell=cell)
            cell.attachment_points = attachment_points

            cell.rigidfoils = self.tables.rigidfoils_cell.get(cell_no)
            
            for p_cell in cell.attachment_points:
                p_cell.get_position(cell)
            
            glider.cells.append(cell)


        logger.info("create cell elements")
        # CELL-ELEMENTS
        self.get_panels(glider)
        self.apply_diagonals(glider)

        for cell_no, cell in enumerate(glider.cells):
            cell.miniribs = self.tables.miniribs.get(row_no=cell_no, resolvers=resolvers)

        # RIB-ELEMENTS
        #self.apply_holes(glider)
                # add stabi rib
        if self.config.has_stabicell:
            cell = glider.cells[-1]
            ballooning = BallooningBezierNeu([(-1,0.015), (-0.7, 0.04), (-0.2, 0.04), (0, 0.02), (0.2, 0.04), (0.7, 0.04), (1,0.015)])
            cell.ballooning = ballooning

            glider.ribs[-2].profile_2d *= self.config.stabi_cell_thickness
        
        #glider.ribs[-1].profile_2d *= 0.
        glider.rename_parts()


        logger.info("create lineset")
        self.tables.lines.lower_attachment_points = self.config.get_lower_attachment_points()
        glider.lineset = self.tables.lines.get_lineset(glider, self.v_inf)
        glider.lineset.recalc(glider=glider)
        glider.lineset.rename_lines()

        return glider

    def apply_ballooning(self, glider3d: Glider | None=None) -> list[BallooningBase]:
        for ballooning in self.balloonings:
            ballooning.apply_splines()

        ballooning_factors = self.get_ballooning_merge()
        balloonings = []

        for cell_no in range(len(ballooning_factors)):
            ballooning_factor = ballooning_factors[cell_no]
            ballooning = self.merge_ballooning(*ballooning_factor)
            if glider3d is not None:
                cell = glider3d.cells[cell_no]
                cell.ballooning = ballooning
            
            balloonings.append(ballooning)

        return balloonings

    @property
    def v_inf(self) -> euklid.vector.Vector3D:
        angle = math.atan(1/self.glide)

        return euklid.vector.Vector3D([math.cos(angle), 0, math.sin(angle)]) * self.speed

    def set_area(self, area: float) -> None:
        factor = math.sqrt(area/self.shape.area)
        self.shape.scale(factor)
        self.tables.lines.scale(factor, scale_lower_floor=False)
        self.config.pilot_position[0] = self.config.pilot_position[0] * factor
        self.config.pilot_position[2] = self.config.pilot_position[2] * factor
        self.rescale_curves()

    def set_aspect_ratio(self, aspect_ratio: float, remain_area: bool=True) -> float:
        ar0 = self.shape.aspect_ratio
        area0 = self.shape.area


        self.shape.scale(y=ar0 / aspect_ratio)

        if remain_area:
            self.set_area(area0)

        return self.shape.aspect_ratio

    def rescale_curves(self) -> None:
        span = self.shape.span

        def rescale(curve: CurveType) -> None:
            span_orig = curve.controlpoints.nodes[-1][0]
            factor = span/span_orig
            curve.controlpoints = curve.controlpoints.scale(euklid.vector.Vector2D([factor, 1.]))

        rescale(self.ballooning_merge_curve)
        rescale(self.profile_merge_curve)
        rescale(self.aoa)
        rescale(self.zrot)
        self.arc.rescale(self.shape.rib_x_values)
