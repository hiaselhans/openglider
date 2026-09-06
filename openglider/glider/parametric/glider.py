from __future__ import annotations

import copy
import logging
import math
import random
from typing import TYPE_CHECKING, Self
from collections.abc import Callable

from openglider.airfoil.profile_2d import Profile2D
from openglider.glider.shape import Shape
import openglider.rs
from openglider.glider.parametric.config import ParametricGliderConfig, SewingAllowanceConfig
from openglider.glider.parametric.table.base.parser import Parser
from openglider.glider.parametric.table.cell.ballooning import BallooningData
from openglider.glider.ballooning.base import BallooningBase
from openglider.glider.ballooning.new import BallooningBezierNeu
from openglider.glider.cell import Cell
from openglider.glider.cell.panel import Panel, PanelCut, PANELCUT_TYPES
from openglider.glider.glider import Glider
from openglider.glider.texture.texture_table import TextureTable
from openglider.glider.parametric.arc import ArcCurve
from openglider.glider.parametric.export_ods import export_ods_2d
from openglider.glider.parametric.import_ods import import_markdown_2d, import_ods_2d
from openglider.glider.parametric.shape import ParametricShape, LeparaglidingShape
from openglider.glider.parametric.table import GliderTables
from openglider.glider.rib import Rib, SingleSkinRib
from openglider.utils import ZipCmp
from openglider.utils.cache import cached_property
from openglider.utils.dataclass import dataclass, Field
from openglider.utils.distribution import Distribution
from openglider.utils.types import CurveType, SymmetricCurveType
from openglider.vector.unit import Percentage, Quantity

if TYPE_CHECKING:
    from openglider.glider.curve import GliderCurveType

logger = logging.getLogger(__name__)


@dataclass
class ParametricGlider:
    """
    A parametric (2D) Glider object used for gui input
    """
    shape: Shape | ParametricShape | LeparaglidingShape
    arc: ArcCurve
    aoa: SymmetricCurveType
    profiles: list[Profile2D]
    profile_merge_curve: CurveType
    balloonings: list[BallooningBase]
    ballooning_merge_curve: CurveType
    config: ParametricGliderConfig
    allowances: SewingAllowanceConfig
    speed: float
    glide: float
    tables: GliderTables = Field(default_factory=lambda: GliderTables())

    num_interpolate: int=30
    num_profile: int | None=None
    texture: TextureTable = Field(default_factory=TextureTable)

    @classmethod
    def import_ods(cls, path: str) -> ParametricGlider:
        return import_ods_2d(cls, path)

    @classmethod
    def import_markdown(cls, path: str) -> ParametricGlider:
        return import_markdown_2d(cls, path)

    export_ods = export_ods_2d

    def copy(self) -> ParametricGlider:
        return copy.deepcopy(self)

    def randomize(self) -> ParametricGlider:
        new = self.copy()

        def get_factor(spread: float) -> float:
            return 1 + 2 * spread * (-0.5 + random.random())

        # change profiles
        for i, foil in enumerate(self.profiles):
            foil.set_camber(foil.camber * get_factor(0.1))
            foil.set_thickness(foil.thickness * get_factor(0.1))

        def randomize_nodes(
                curve: openglider.rs.vector.PolyLine2D, 
                factor: float,
                change_first: tuple[bool, bool]=(False, True),
                change_last: tuple[bool, bool]=(False, True)) -> openglider.rs.vector.PolyLine2D:
            assert len(curve) > 0
            new_curve = curve.nodes[:]

            if change_first[0]:
                new_curve[0][0] *= get_factor(factor) # change x[0] for 2%
            if change_first[1]:
                new_curve[0][1] *= get_factor(factor) # change x[0] for 2%

            for p in new_curve[1:-1]:
                p[0] *= get_factor(factor)
                p[1] *= get_factor(factor)

            if change_last[0]:
                new_curve[-1][0] *= get_factor(factor) # change x[0] for 2%
            if change_last[1]:
                new_curve[-1][1] *= get_factor(factor) # change x[0] for 2%

            return openglider.rs.vector.PolyLine2D(new_curve)
            

        # change arc
        new.arc.curve.controlpoints = randomize_nodes(new.arc.curve.controlpoints, 0.02)

        # change shape
        if isinstance(new.shape, ParametricShape):
            new.shape.front_curve.controlpoints = randomize_nodes(new.shape.front_curve.controlpoints, 0.02)
            new.shape.back_curve.controlpoints = randomize_nodes(new.shape.back_curve.controlpoints, 0.02)
            new.shape.rib_dist_controlpoints = randomize_nodes(new.shape.rib_dist_controlpoints, 0.02, (True, True), (True, True)).nodes

        new.aoa.controlpoints = randomize_nodes(new.aoa.controlpoints, 0.1, (False, True), (False, True))

        return new

    def get_shape(self) -> Shape:
        if isinstance(self.shape, Shape):
            return self.shape
        return self.shape.get_half_shape()

    def get_arc_angles(self) -> list[float]:
        """
        Get rib rotations
        """
        return self.arc.get_rib_angles(self.shape.rib_x_values)

    def merge_ballooning(self, factor: float, multiplier: float | None) -> BallooningBase:
        factor = max(0, min(len(self.balloonings)-1, factor))
        k = factor % 1
        i = int(factor // 1)
        first = self.balloonings[i]
        if k > 0:
            second = self.balloonings[i + 1]
            result = first * (1 - k) + second * k
        else:
            result = first.copy()
        
        if multiplier is not None:
            result *= multiplier

        return result

    def get_merge_profile(self, factor: float) -> Profile2D:
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
        return self.tables.curves.get_curves(self.get_shape())

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

            materials = self.tables.material_cells.get(cell_no, None, color_groups=self.config.color_groups)

            for cut1, cut2 in ZipCmp(cuts):
                
                if cut1.x_right > cut2.x_right or cut1.x_left > cut2.x_left:
                    error_str = "Invalid cuts for panel: C{} {:.02f}/{:.02f}/{} + {:.02f}/{:.02f}/{}".format(
                        cell_no+1,
                        cut1.x_left, cut1.x_right, cut1.cut_type,
                        cut2.x_left, cut2.x_right, cut2.cut_type
                    )
                    raise ValueError(error_str)

                if cut1.cut_type == cut2.cut_type:
                    if cut1.cut_type in (PANELCUT_TYPES.folded, PANELCUT_TYPES.singleskin):
                        continue

                try:
                    material, color_group = materials[i]
                except (KeyError, IndexError):
                    #logger.warning(f"No material for panel {cell_no}/{i+1}")
                    material = openglider.materials.Material(name="unknown")
                    color_group = None
                
                i += 1

                if material is not None:
                    panel = Panel(cut1, cut2,
                                name=f"c{cell_no+1}p{len(panel_lst)+1}",
                                material=material,
                                color_group=color_group)
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
            cell.straps.sort(key=lambda strap: (strap.is_lower, strap.get_average_x()))

            for strap_no, strap in enumerate(cell.diagonals):
                strap.name = "c{}{}{}".format(cell_no+1, "s", strap_no)

    def get_aoa(self, interpolation_num: int | None=None) -> list[float]:
        aoa_interpolation = openglider.rs.vector.Interpolation(self.aoa.get_sequence(interpolation_num or self.num_interpolate).nodes)

        return [aoa_interpolation.get_value(abs(x)) for x in self.shape.rib_x_values]

    def apply_aoa(self, glider: Glider) -> None:
        aoa_values = self.get_aoa()

        for rib, aoa in zip(glider.ribs, aoa_values):
            if self.config.aoa_absolute:
                rib.aoa_absolute = aoa
            else:
                rib.set_aoa_relative(aoa)

    def get_profile_merge_values(self) -> list[float]:
        profile_merge_curve = openglider.rs.vector.Interpolation(self.profile_merge_curve.get_sequence(self.num_interpolate).nodes)
        return [profile_merge_curve.get_value(abs(x)) for x in self.shape.rib_x_values]

    def get_ballooning_data(self) -> list[BallooningData]:
        ballooning_merge_curve = openglider.rs.vector.Interpolation(self.ballooning_merge_curve.get_sequence(self.num_interpolate).nodes)
        merge_factors = [ballooning_merge_curve.get_value(abs(x)) for x in self.shape.cell_x_values]

        result = []

        for rib_no, merge_factor in enumerate(merge_factors):
            modifier = self.tables.ballooning_modifiers.get_ballooning_data(rib_no, self.resolvers)
            if modifier.merge_factor is None:
                modifier.merge_factor = merge_factor
            result.append(modifier)
        
        return result

    def get_rib_positions(self) -> list[openglider.rs.vector.Vector3D]:
        rib_positions = self.shape.get_baseline(self.config.baseline_pct or Percentage(0.)).nodes
        shape_ribs = self.shape.ribs
        x_values = self.shape.rib_x_values
        arc_pos = self.arc.get_arc_positions(x_values).nodes

        offset_x = shape_ribs[0][0][1]

        result: list[openglider.rs.vector.Vector3D] = []

        for rib_no, x in enumerate(x_values):
            arc = arc_pos[rib_no]
            shape_pos = rib_positions[rib_no]
            startpoint = openglider.rs.vector.Vector3D([-shape_pos[1] + offset_x, arc[0], arc[1]])
            result.append(startpoint)

        return result

    def apply_shape_and_arc(self, glider: Glider) -> None:
        rib_positions = self.get_rib_positions()
        ribs = self.shape.ribs
        x_values = [abs(x) for x in self.shape.rib_x_values]

        rib_angles = self.arc.get_rib_angles(x_values)

        for rib_no, pos in enumerate(rib_positions):
            rib = glider.ribs[rib_no]

            rib.pos = pos
            rib.chord = abs(ribs[rib_no][0][1]-ribs[rib_no][1][1])
            rib.arcang = rib_angles[rib_no]

    @cached_property('tables.curves', 'shape')
    def resolvers(self) -> list[Parser]:
        parsers = []
        curves=self.get_curves()

        def resolver_factory(rib_no: int) -> Callable[[str], float | Quantity]:
            def resolve(name: str) -> float | Quantity:
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
    
    def get_profiles(self, num_profile: int | None=None) -> list[Profile2D]:
        resolvers = self.resolvers
        num_profile = num_profile or self.num_profile

        if num_profile is not None:
            airfoil_distribution = list(Distribution.from_cos_distribution(num_profile))
        else:
            airfoil_distribution = self.profiles[0].x_values            

        x_values = self.shape.rib_x_values
        cell_widths = [x2-x1 for x2, x1 in zip(x_values[:-1], x_values[1:])]
        rib_chords = self.shape.chords

        if self.shape.has_center_cell:
            x_values = x_values[1:]
            rib_chords = rib_chords[1:]

        profile_merge_curve = openglider.rs.vector.Interpolation(self.profile_merge_curve.get_sequence(self.num_interpolate).nodes)
        
        result: list[Profile2D] = []

        for rib_no, x_value in enumerate(x_values):
            merge_factor, scale_factor = self.tables.profile_modifiers.get_factors(rib_no, resolvers=resolvers)

            if merge_factor is not None:
                factor = merge_factor
            else:
                factor = profile_merge_curve.get_value(abs(x_value))

            profile = self.get_merge_profile(factor)


            if scale_factor is not None:
                profile = profile.set_thickness(profile.thickness * scale_factor)
            
            if self.config.use_mean_profile:
                balloonings = self.apply_ballooning()

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

        if glider is None:
            glider = Glider()
        
        ribs = []

        logger.debug("apply curves")
        self.rescale_curves()
        resolvers = self.resolvers

        x_values = self.shape.rib_x_values
        shape_ribs = self.shape.ribs

        aoa_values = self.get_aoa()

        rib_angles = self.arc.get_rib_angles(x_values)
        profiles = self.get_profiles(num_profile=num_profile)

        rib_positions = self.get_rib_positions()

        logger.info("create ribs")

        for rib_no, x_value in enumerate(x_values):
            front, back = shape_ribs[rib_no]

            try:
                material = self.tables.material_ribs.get(rib_no, None, color_groups={})[0][0]
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

            rotation = self.tables.rib_modifiers.get_rotation(rib_no, resolvers=resolvers)

            rib = Rib(
                profile_2d=profiles[rib_no],
                pos=rib_positions[rib_no],
                rotation_position=self.config.baseline_pct,
                chord=chord,
                arcang=rib_angles[rib_no],
                xrot=rotation.x,
                offset=self.tables.rib_modifiers.get_offset(rib_no, resolvers=resolvers),
                glide=self.glide,
                aoa_absolute=aoa_values[rib_no],
                zrot=rotation.z,
                holes=this_rib_holes,
                rigidfoils=this_rigid_foils,
                name=f"rib{rib_no}",
                material=material,
                sharknose=sharknose,
                attachment_points=[],
                seam_allowance=self.allowances.general,
                **data  # type: ignore
            )
            if not self.config.aoa_absolute:
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

        ballooning_data = self.get_ballooning_data()
        glider.cells = []
        for cell_no, (rib1, rib2) in enumerate(zip(ribs[:-1], ribs[1:])):

            ballooning_factor = ballooning_data[cell_no]
            assert ballooning_factor.merge_factor is not None
            ballooning = self.merge_ballooning(ballooning_factor.merge_factor, ballooning_factor.ballooning_factor)
            
            cell = Cell(
                rib1=rib1,
                rib2=rib2,
                ballooning=ballooning,
                ballooning_reference=ballooning_factor.ballooning_reference,
                name=f"c{cell_no+1}",
                attachment_points=[],
                ballooning_modifiers=self.tables.ballooning_modifiers.get_modifiers(cell_no, resolvers=resolvers)
                )

            attachment_points = self.tables.attachment_points_cell.get(cell_no, resolvers=resolvers, cell=cell)
            cell.attachment_points = attachment_points

            cell.rigidfoils = self.tables.rigidfoils_cell.get(cell_no, resolvers=resolvers)
            
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
        
        glider.ribs[-1].profile_2d *= self.config.last_profile_height
        glider.rename_parts()


        logger.info("create lineset")
        self.tables.lines.lower_attachment_points = self.config.get_lower_attachment_points()
        glider.lineset = self.tables.lines.get_lineset(glider, self.v_inf)
        glider.lineset.calculate_sag = self.config.use_sag
        glider.lineset.recalc(glider=glider)
        glider.lineset.rename_lines()

        logger.info("apply texture")
        if self.texture.has_texture():
            glider.texture = self.texture.get_texture(self.get_shape(), glider)

        return glider

    def apply_ballooning(self, glider3d: Glider | None=None) -> list[BallooningBase]:
        for ballooning in self.balloonings:
            ballooning.apply_splines()

        ballooning_factors = self.get_ballooning_data()
        balloonings = []

        for cell_no, ballooning_factor in enumerate(ballooning_factors):
            assert ballooning_factor.merge_factor is not None
            ballooning = self.merge_ballooning(ballooning_factor.merge_factor, ballooning_factor.ballooning_factor)
            if glider3d is not None:
                cell = glider3d.cells[cell_no]
                cell.ballooning = ballooning
                cell.ballooning_reference = ballooning_factor.ballooning_reference
            
            balloonings.append(ballooning)

        return balloonings

    @property
    def v_inf(self) -> openglider.rs.vector.Vector3D:
        angle = math.atan(1/self.glide)

        return openglider.rs.vector.Vector3D([math.cos(angle), 0, math.sin(angle)]) * self.speed

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
        span = self.shape.span / 2

        def rescale(curve: CurveType) -> None:
            span_orig = curve.controlpoints.nodes[-1][0]
            factor = span/span_orig
            curve.controlpoints = curve.controlpoints.scale(openglider.rs.vector.Vector2D([factor, 1.]))

        rescale(self.ballooning_merge_curve)
        rescale(self.profile_merge_curve)
        rescale(self.aoa)
        self.arc.rescale(self.shape.rib_x_values)
