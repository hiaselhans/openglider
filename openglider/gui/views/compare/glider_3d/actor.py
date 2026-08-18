import logging
from pathlib import Path

from openglider.glider.texture.texture import SVGTexture
import openglider.mesh
import openglider.rs
from openglider.glider.glider import Glider
from openglider.glider.project import GliderProject
from openglider.glider.texture.uv_map import UVMapMode
from openglider.gui.views.compare.glider_3d.config import GliderViewConfig, get_riser_indices
from openglider.gui.views_3d.widgets import View3D


logger = logging.getLogger(__name__)


class GliderActors:
    project: GliderProject
    glider_3d: Glider | None
    config: GliderViewConfig | None
    actors: dict

    def __init__(self, project: GliderProject):
        self.project = project
        self.glider_3d = self.project.get_glider_3d()
        self.actors = {}
        self.config = None
        self._panel_texture_key: str | None = None
        self._cached_project_svg_texture: SVGTexture | None = None
        self._cached_project_svg_hash: int | None = None

    def _get_project_texture_svg(self) -> str | None:
        texture = self.project.glider.texture
        if texture.has_texture():
            return texture.svg
        return None

    def _get_effective_texture(self) -> tuple[SVGTexture | None, UVMapMode]:
        project_texture_svg = self._get_project_texture_svg()
        if not project_texture_svg:
            return None, self.project.glider.texture.style

        project_svg_hash = hash(project_texture_svg)
        if self._cached_project_svg_hash != project_svg_hash:
            try:
                self._cached_project_svg_texture = SVGTexture(project_texture_svg)
            except Exception:
                logger.exception("failed to load inline project texture")
                self._cached_project_svg_texture = None
            self._cached_project_svg_hash = project_svg_hash

        return self._cached_project_svg_texture, self.project.glider.texture.style

    def _get_texture_scene_key(self, config: GliderViewConfig) -> str:
        project_texture_svg = self._get_project_texture_svg()
        project_texture_hash = hash(project_texture_svg) if project_texture_svg is not None else 0
        uv_mode = self.project.glider.texture.style
        return f"{uv_mode}|{config.texture_precision:.3f}|{project_texture_hash}"

    def get_panels(self, numribs: int) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        panel_mesh = openglider.mesh.Mesh()

        for i, cell in enumerate(self.glider_3d.cells):
            for panel in cell.panels:
                mesh_temp = panel.get_mesh(cell, numribs=numribs)
                panel_mesh += mesh_temp

                if not (i == 0 and self.glider_3d.has_center_cell):
                    panel_mesh += mesh_temp.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(panel_mesh, draw_edges=False)

    def get_panels_textured(self, numribs: int, config: GliderViewConfig) -> openglider.rs.wgpu.MeshActor:
        texture, uv_mode = self._get_effective_texture()
        if texture is None:
            return self.get_panels(numribs)

        uv_map = self.glider_3d.texture.uv_map

        try:
            return uv_map.get_textured_panels_actor(
                texture=texture,
                numribs=numribs,
                precision=config.texture_precision,
                cache_texture=True,
            )
        except Exception:
            logger.exception("failed to build textured panel mesh")
            return self.get_panels(numribs)

    def get_ribs(self, hole_numpoints: int) -> openglider.rs.wgpu.MeshActor:
        ribs_mesh = openglider.mesh.Mesh()

        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        for i, rib in enumerate(self.glider_3d.ribs):
            try:
                mesh_temp = rib.get_mesh(hole_num=hole_numpoints, filled=True)
            except BaseException as e:
                logger.error(f"Error generating mesh for rib {rib.name}: {e}")
                continue

            ribs_mesh += mesh_temp

            if i > self.glider_3d.has_center_cell:
                ribs_mesh += mesh_temp.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(ribs_mesh, draw_edges=True, boundary_only=True)

    def get_lines(
        self,
        numpoints: int = 3,
        riser: str | int = "all",
    ) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        lowest_lines = self.glider_3d.lineset.lowest_lines
        regular, brake = get_riser_indices(
            [line.lower_node.name for line in lowest_lines],
            self.project.glider.config.brake_name,
        )
        if riser == "all":
            riser_index = None
        elif riser == "brake":
            riser_index = brake if brake is not None else len(lowest_lines)
        elif isinstance(riser, int) and 0 <= riser < len(regular):
            riser_index = regular[riser]
        else:
            riser_index = len(lowest_lines)

        mesh_lineset = self.glider_3d.lineset.get_mesh(
            numpoints=numpoints,
            riser_index=riser_index,
        )
        mesh = mesh_lineset + mesh_lineset.copy().mirror("y")
        return openglider.rs.wgpu.MeshActor(mesh)

    def get_diagonals(self, hole_numpoints: int, numribs: int) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        mesh = openglider.mesh.Mesh()
        for cell_no, cell in enumerate(self.glider_3d.cells):
            for diagonal in cell.diagonals:
                cell_mesh = diagonal.get_mesh(cell, numribs, False, hole_numpoints)

                mesh += cell_mesh
                if cell_no > 0 or not self.glider_3d.has_center_cell:
                    mesh += cell_mesh.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(mesh, draw_edges=True, boundary_only=True)

    def get_straps(self, numribs: int) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        mesh = openglider.mesh.Mesh()
        for cell_no, cell in enumerate(self.glider_3d.cells):
            for diagonal in cell.straps:
                cell_mesh = diagonal.get_mesh(cell, numribs)

                mesh += cell_mesh
                if cell_no > 0 or not self.glider_3d.has_center_cell:
                    mesh += cell_mesh.copy().mirror("y")

            for rigidfoil in cell.rigidfoils:
                cell_mesh = rigidfoil.get_mesh(cell, numribs)

                mesh += cell_mesh
                if cell_no > 0 or not self.glider_3d.has_center_cell:
                    mesh += cell_mesh.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(mesh, draw_edges=True, boundary_only=True)

    def get_miniribs(self) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        mesh = openglider.mesh.Mesh()
        for cell_no, cell in enumerate(self.glider_3d.cells):
            for minirib in cell.miniribs:
                minirib_mesh = minirib.get_mesh(cell)

                mesh += minirib_mesh
                if cell_no > 0 or not self.glider_3d.has_center_cell:
                    mesh += minirib_mesh.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(mesh, draw_edges=False)

    def add(self, view_3d: View3D, config: GliderViewConfig) -> None:
        texture_key = self._get_texture_scene_key(config)

        if self.glider_3d is None or config.needs_recalc(self.config):
            self.glider_3d = self.project.get_glider_3d().copy()

            if self.glider_3d is None:
                return

            self.glider_3d.profile_numpoints = config.profile_numpoints
            for rib in self.glider_3d.ribs:
                rib.get_hull()

            self.actors = {
                "panels": self.get_panels_textured(config.numribs, config),
                "ribs": self.get_ribs(config.hole_numpoints),
                "lines": self.get_lines(
                    config.line_numpoints,
                    config.line_riser,
                ),
                "diagonals": self.get_diagonals(config.hole_numpoints, config.numribs),
                "straps": self.get_straps(config.numribs),
                "miniribs": self.get_miniribs(),
            }
            self._panel_texture_key = texture_key
        else:
            if self.config is not None and (
                config.line_numpoints != self.config.line_numpoints
                or config.line_riser != self.config.line_riser
            ):
                self.actors["lines"] = self.get_lines(
                    config.line_numpoints,
                    config.line_riser,
                )
            if self._panel_texture_key != texture_key:
                self.actors["panels"] = self.get_panels_textured(config.numribs, config)
                self._panel_texture_key = texture_key

        for name in config.get_active_keys():
            view_3d.show_actor(self.actors[name])

        self.config = config.copy()

    def remove(self, view_3d: View3D) -> None:
        if self.config is None:
            return

        for name in self.config.get_active_keys():
            view_3d.remove_actor(self.actors[name])

    def update(self, view_3d: View3D, config: GliderViewConfig) -> None:
        self.remove(view_3d)
        self.add(view_3d, config)

