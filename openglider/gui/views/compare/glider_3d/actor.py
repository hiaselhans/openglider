import logging
from pathlib import Path

import openglider.mesh
import openglider.rs
from openglider.glider.glider import Glider
from openglider.glider.project import GliderProject
from openglider.glider.uv_map import SVGTexture, UVMap, UVMapMode
from openglider.gui.views_3d.widgets import View3D
from openglider.mesh import Mesh
from openglider.gui.views.compare.glider_3d.config import GliderViewConfig


logger = logging.getLogger(__name__)



class GliderActors:
    project: GliderProject
    glider_3d: Glider | None
    config: GliderViewConfig | None
    actors: dict

    def __init__(self, project: GliderProject):
        self.project = project
        self.glider_3d = None
        self.actors = {}
        self.config = None
        self.texture_svg_path: str | None = None
        self.texture_uv_mode: UVMapMode = "stacked"
        self.texture_precision: float = 0.35
        self.texture_overlay: bool = False
        self._panel_texture_key: str | None = None
        self._cached_svg_texture: SVGTexture | None = None
        self._cached_svg_texture_path: str | None = None
        self._cached_uv_map: UVMap | None = None

    def set_panel_texture(
        self,
        texture_svg_path: str | None,
        uv_mode: UVMapMode = "stacked",
        precision: float | None = None,
        overlay: bool = False,
    ) -> None:
        self.texture_svg_path = texture_svg_path
        self.texture_uv_mode = uv_mode
        if precision is not None:
            self.texture_precision = precision
        self.texture_overlay = overlay

    def invalidate_texture_cache(self) -> None:
        self._cached_svg_texture = None
        self._cached_svg_texture_path = None
        self._panel_texture_key = None
        
    def get_panels(self, numribs: int):
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

    def get_panels_textured(self, numribs: int):
        if self._cached_uv_map is None:
            self._cached_uv_map = UVMap(self.project.glider)
        uv_map = self._cached_uv_map

        if self.texture_svg_path is None:
            return self.get_panels(numribs)

        texture_path = Path(self.texture_svg_path)
        if not texture_path.exists():
            logger.warning("texture svg does not exist: %s", texture_path)
            return self.get_panels(numribs)

        # Cache SVGTexture so the SVG is only parsed and rendered once per path change.
        if self._cached_svg_texture_path != self.texture_svg_path:
            try:
                self._cached_svg_texture = SVGTexture(texture_path)
            except Exception:
                logger.exception("failed to load SVG texture: %s", texture_path)
                return self.get_panels(numribs)
            self._cached_svg_texture_path = self.texture_svg_path

        try:
            return uv_map.get_textured_panels_actor(
                texture=self._cached_svg_texture,
                numribs=numribs,
                mode=self.texture_uv_mode,
                precision=self.texture_precision,
                cache_texture=False,
                draw_edges=self.texture_overlay,
                boundary_only=self.texture_overlay,
            )
        except Exception:
            logger.exception("failed to build textured panel mesh")
            return self.get_panels(numribs)
    
    def get_ribs(self, hole_numpoints: int):
        ribs_mesh = openglider.mesh.Mesh()

        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        for i, rib in enumerate(self.glider_3d.ribs):
            try:
                mesh_temp = rib.get_mesh(hole_num=hole_numpoints, filled=True)
            except BaseException as e:
                logger.error(f"Error generating mesh for rib {rib.name}: {e}")
                continue  # Skip this rib and continue with the next one
                #raise e

            ribs_mesh += mesh_temp

            # center cell -> dont mirror 0 and 1, no center cell -> dont mirror 0
            if i > self.glider_3d.has_center_cell:
                ribs_mesh += mesh_temp.copy().mirror("y")

        return openglider.rs.wgpu.MeshActor(ribs_mesh, draw_edges=True, boundary_only=True)

    def get_lines(self, numpoints: int=3):
        if self.glider_3d is None:
            raise ValueError("Glider3D not set")

        mesh_lineset = self.glider_3d.lineset.get_mesh(numpoints=numpoints)
        mesh = mesh_lineset + mesh_lineset.copy().mirror("y")
        return openglider.rs.wgpu.MeshActor(mesh)
    
    def get_diagonals(self, hole_numpoints: int, numribs: int):
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

    def get_straps(self, numribs: int):
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
    
    def get_miniribs(self):
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
        texture_key = f"{self.texture_svg_path or ''}|{self.texture_uv_mode}|{self.texture_precision:.3f}|{int(self.texture_overlay)}"

        if self.glider_3d is None or config.needs_recalc(self.config):
            self.glider_3d = self.project.get_glider_3d().copy()

            if self.glider_3d is None:
                return
                
            self.glider_3d.profile_numpoints = config.profile_numpoints
            for rib in self.glider_3d.ribs:
                rib.get_hull()
        
            self.actors = {
                "panels": self.get_panels_textured(config.numribs),
                "ribs": self.get_ribs(config.hole_numpoints),
                "lines": self.get_lines(config.line_numpoints),
                "diagonals": self.get_diagonals(config.hole_numpoints, config.numribs),
                "straps": self.get_straps(config.numribs),
                "miniribs": self.get_miniribs()
            }
            self._panel_texture_key = texture_key
        elif self._panel_texture_key != texture_key:
            self.actors["panels"] = self.get_panels_textured(config.numribs)
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

