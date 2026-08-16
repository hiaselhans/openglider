from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np

from openglider.glider.glider import Glider
from openglider.glider.texture.texture import SVGTexture, Texture
import openglider.rs
from openglider.glider.project import GliderProject
from openglider.glider.texture.uv_map import UVMapMode
from openglider.glider.texture.uv_map.mirrored import UVMapMirrored
from openglider.glider.texture.uv_map.stacked import UVMapStacked
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views.compare.glider_3d.config import GliderViewConfig
from openglider.gui.views_2d.mpl.canvas import PlotCanvas
from openglider.gui.views_3d.widgets import View3D
from openglider.gui.wizzards.base import Wizard
from openglider.utils.types import expect_value

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow


logger = logging.getLogger(__name__)

WizardUVMap = UVMapMirrored | UVMapStacked


class DelayedFileWatcher(QtCore.QObject):
    """Debounce QFileSystemWatcher notifications until writes have settled."""

    fileChanged = QtCore.Signal(str)

    def __init__(self, parent: QtCore.QObject | None = None, delay_ms: int = 150):
        super().__init__(parent)
        self._watcher = QtCore.QFileSystemWatcher(self)
        self._delay_timer = QtCore.QTimer(self)
        self._delay_timer.setSingleShot(True)
        self._delay_timer.setInterval(delay_ms)
        self._delay_timer.timeout.connect(self._emit_pending_files)
        self._pending_files: set[str] = set()
        self._watcher.fileChanged.connect(self._on_file_changed)

    def _on_file_changed(self, file_path: str) -> None:
        if not file_path:
            return
        self._pending_files.add(file_path)
        self._delay_timer.start()

    def _emit_pending_files(self) -> None:
        pending_files = sorted(self._pending_files)
        self._pending_files.clear()
        for file_path in pending_files:
            self.fileChanged.emit(file_path)

    def addPath(self, path: str) -> None:
        self._watcher.addPath(path)

    def removePath(self, path: str) -> None:
        self._watcher.removePath(path)

    def removePaths(self, paths: list[str] | tuple[str, ...] | set[str]) -> None:
        self._watcher.removePaths(list(paths))

    def files(self) -> list[str]:
        return self._watcher.files()


class TexturePanelsActor:
    """Wizard-only textured panel actor with explicit reload control."""

    def __init__(
        self,
        project: GliderProject,
        get_uv_map: Callable[[Glider, UVMapMode], WizardUVMap],
    ):
        self.project = project
        self._get_uv_map = get_uv_map
        self.glider_3d: Glider | None = None
        self.texture_svg_path: str | None = None
        self.texture_uv_mode: UVMapMode = "stacked"
        self.texture_precision: float = 0.35
        self._cached_svg_texture: SVGTexture | None = None
        self._cached_svg_texture_key: str | None = None

    def set_texture_settings(
        self,
        texture_svg_path: str | None,
        uv_mode: UVMapMode,
        precision: float,
    ) -> None:
        self.texture_svg_path = texture_svg_path
        self.texture_uv_mode = uv_mode
        self.texture_precision = precision

    def invalidate_texture_cache(self) -> None:
        self._cached_svg_texture = None
        self._cached_svg_texture_key = None

    def _get_project_texture_svg(self) -> str | None:
        texture = self.project.glider.texture
        if texture.has_texture():
            return texture.svg
        return None

    def _get_panels(self, numribs: int) -> openglider.rs.wgpu.MeshActor:
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

    def _load_texture(self) -> SVGTexture | None:
        if self.texture_svg_path:
            texture_path = Path(self.texture_svg_path)
            if not texture_path.exists():
                logger.warning("texture svg does not exist: %s", texture_path)
                return None

            cache_key = f"path:{texture_path.resolve()}"
            if self._cached_svg_texture_key != cache_key:
                try:
                    self._cached_svg_texture = SVGTexture.read(texture_path)
                except Exception:
                    logger.exception("failed to load SVG texture: %s", texture_path)
                    return None
                self._cached_svg_texture_key = cache_key

            return self._cached_svg_texture

        project_texture_svg = self._get_project_texture_svg()
        if not project_texture_svg:
            return None

        cache_key = f"inline:{hash(project_texture_svg)}"
        if self._cached_svg_texture_key != cache_key:
            try:
                self._cached_svg_texture = SVGTexture(project_texture_svg)
            except Exception:
                logger.exception("failed to load inline project texture")
                return None
            self._cached_svg_texture_key = cache_key

        return self._cached_svg_texture

    def get_actor(self, numribs: int, profile_numpoints: int) -> openglider.rs.wgpu.MeshActor:
        if self.glider_3d is None or getattr(self.glider_3d, "profile_numpoints", None) != profile_numpoints:
            self.glider_3d = self.project.get_glider_3d().copy()
            self.glider_3d.profile_numpoints = profile_numpoints
            for rib in self.glider_3d.ribs:
                rib.get_hull()

        texture = self._load_texture()
        if texture is None:
            return self._get_panels(numribs)

        uv_map = self._get_uv_map(self.glider_3d, self.texture_uv_mode)
        self.glider_3d.texture = Texture(uv_map=uv_map, texture=texture)

        try:
            return uv_map.get_textured_panels_actor(
                texture=texture,
                numribs=numribs,
                precision=self.texture_precision,
                cache_texture=True,
            )
        except Exception:
            logger.exception("failed to build textured panel mesh")
            return self._get_panels(numribs)


class TextureWizardWidget(QtWidgets.QGroupBox):
    changed = QtCore.Signal()
    reload_requested = QtCore.Signal()
    export_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget, app: MainWindow) -> None:
        super().__init__("Texture Wizard", parent)
        self.app = app
        self._svg_path: str | None = None
        self._auto_reload = True

        main_layout = QtWidgets.QVBoxLayout()
        self.setLayout(main_layout)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(6)

        path_layout = QtWidgets.QGridLayout()
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setHorizontalSpacing(8)
        path_layout.setVerticalSpacing(4)

        path_layout.addWidget(QtWidgets.QLabel("Texture file:", self), 0, 0)
        self._label_path = QtWidgets.QLabel("(none)", self)
        self._label_path.setWordWrap(True)
        path_layout.addWidget(self._label_path, 0, 1, 1, 4)

        self._btn_load = QtWidgets.QPushButton("Set SVG...", self)
        self._btn_load.clicked.connect(self._load_texture)
        path_layout.addWidget(self._btn_load, 1, 0)

        self._btn_clear = QtWidgets.QPushButton("Clear", self)
        self._btn_clear.clicked.connect(self._clear_texture)
        self._btn_clear.setEnabled(False)
        path_layout.addWidget(self._btn_clear, 1, 1)

        self._btn_export = QtWidgets.QPushButton("Save Texture Template...", self)
        self._btn_export.clicked.connect(self.export_requested)
        path_layout.addWidget(self._btn_export, 1, 2)

        self._btn_reload = QtWidgets.QPushButton("Reload Now", self)
        self._btn_reload.clicked.connect(self.reload_requested)
        self._btn_reload.setEnabled(False)
        path_layout.addWidget(self._btn_reload, 1, 3)

        main_layout.addLayout(path_layout)

        style_layout = QtWidgets.QGridLayout()
        style_layout.setContentsMargins(0, 0, 0, 0)
        style_layout.setHorizontalSpacing(8)
        style_layout.setVerticalSpacing(4)

        style_layout.addWidget(QtWidgets.QLabel("Texture style:", self), 0, 0)
        self._combo_mode = QtWidgets.QComboBox(self)
        self._combo_mode.addItems(["stacked", "mirrored"])
        self._combo_mode.currentTextChanged.connect(self.changed)
        style_layout.addWidget(self._combo_mode, 0, 1)

        self._precision = QtWidgets.QDoubleSpinBox(self)
        self._precision.setRange(0.1, 1.0)
        self._precision.setSingleStep(0.05)
        self._precision.setDecimals(2)
        self._precision.setKeyboardTracking(False)
        self._precision.setValue(0.35)
        precision_line = self._precision.lineEdit()
        if precision_line is not None:
            precision_line.returnPressed.connect(self.changed)
        style_layout.addWidget(QtWidgets.QLabel("Texture precision:", self), 1, 0)
        style_layout.addWidget(self._precision, 1, 1)

        main_layout.addLayout(style_layout)

    @property
    def svg_path(self) -> str | None:
        return self._svg_path

    @property
    def auto_reload(self) -> bool:
        return self._auto_reload

    @property
    def uv_mode(self) -> UVMapMode:
        return "mirrored" if self._combo_mode.currentText() == "mirrored" else "stacked"

    @property
    def texture_precision(self) -> float:
        return float(self._precision.value())

    def set_uv_mode(self, mode: UVMapMode) -> None:
        self._combo_mode.setCurrentText(mode)

    def _load_texture(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load SVG Texture",
            "",
            "SVG files (*.svg)",
        )
        if not filename:
            return

        self._svg_path = filename
        self._label_path.setText(filename)
        self._btn_clear.setEnabled(True)
        self._btn_reload.setEnabled(True)
        self.changed.emit()

    def _clear_texture(self) -> None:
        self._svg_path = None
        self._label_path.setText("(none)")
        self._btn_clear.setEnabled(False)
        self._btn_reload.setEnabled(False)
        self.changed.emit()

class Texture3DPreview(QtWidgets.QWidget):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        app: MainWindow,
        glider: GliderProject,
        get_uv_map: Callable[[Glider, UVMapMode], WizardUVMap],
    ) -> None:
        super().__init__(parent)
        self.app = app
        self.glider = glider
        self._is_shutting_down = False
        self.setLayout(QtWidgets.QVBoxLayout())

        self._fixed_config = GliderViewConfig(
            show_panels=True,
            show_ribs=False,
            show_lines=False,
            show_diagonals=False,
            show_straps=False,
            show_miniribs=False,
        )

        self.view_3d = View3D(self)
        self.view_3d.show_axes = False
        self.view_3d.destroyed.connect(self._on_view_destroyed)
        expect_value(self.layout()).addWidget(self.view_3d)

        self.view_3d.render_widget.destroyed.connect(self._on_view_destroyed)

        self.actor = TexturePanelsActor(self.glider, get_uv_map)

        self.texture_svg_path: str | None = None
        self.texture_uv_mode: UVMapMode = "stacked"
        self.texture_precision: float = 0.35
        self._last_scene_key: tuple[str | None, UVMapMode, float] | None = None
    def set_texture_settings(
        self,
        texture_svg_path: str | None,
        uv_mode: UVMapMode,
        precision: float,
        overlay: bool,
    ) -> None:
        self.texture_svg_path = texture_svg_path
        self.texture_uv_mode = uv_mode
        self.texture_precision = precision

    def invalidate_texture_cache(self) -> None:
        self.actor.invalidate_texture_cache()
        self._last_scene_key = None

    def _on_view_destroyed(self, *_: object) -> None:
        self.shutdown()

    def update_scene(self) -> None:
        scene_key = (self.texture_svg_path, self.texture_uv_mode, round(self.texture_precision, 3))
        if scene_key == self._last_scene_key:
            return

        self.view_3d.clear()

        self.actor.set_texture_settings(
            self.texture_svg_path,
            self.texture_uv_mode,
            self.texture_precision,
        )
        panels = self.actor.get_actor(
            numribs=self._fixed_config.numribs,
            profile_numpoints=self._fixed_config.profile_numpoints,
        )
        self.view_3d.show_actor(panels)

        self.view_3d.rerender()
        self._last_scene_key = scene_key

    def clear_stale_scene(self) -> None:
        self._last_scene_key = None
        self.view_3d.clear()
        self.view_3d.rerender()

    def shutdown(self) -> None:
        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        try:
            self.view_3d.shutdown()
        except RuntimeError:
            # The Qt object may already be in destruction; ignore late shutdown attempts.
            pass


class Texture2DPreview(QtWidgets.QWidget):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        get_uv_map: Callable[[Glider, UVMapMode], WizardUVMap],
    ) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.canvas = PlotCanvas(zoom=True)
        self.canvas.grid = True
        self.canvas.update_settings()
        expect_value(self.layout()).addWidget(self.canvas)
        self._get_uv_map = get_uv_map
        self._panel_polys_by_mode: dict[UVMapMode, list[list[tuple[float, float]]]] = {}
        self._bbox_by_mode: dict[UVMapMode, tuple[float, float, float, float]] = {}
        self._cached_texture_path: str | None = None
        self._cached_texture: SVGTexture | None = None

    def invalidate_texture_cache(self) -> None:
        self._cached_texture_path = None
        self._cached_texture = None

    def _get_panel_polys(
        self,
        glider_3d: Glider,
        uv_mode: UVMapMode,
    ) -> tuple[list[list[tuple[float, float]]], tuple[float, float, float, float]]:
        cached_polys = self._panel_polys_by_mode.get(uv_mode)
        cached_bbox = self._bbox_by_mode.get(uv_mode)
        if cached_polys is not None and cached_bbox is not None:
            return cached_polys, cached_bbox

        uv_map = self._get_uv_map(glider_3d, uv_mode)
        layout = uv_map.get_layout()
        panel_polys: list[list[tuple[float, float]]] = []
        for part in layout.parts:
            for polyline in part.layers["marks"]:
                panel_polys.append(list(polyline))

        if not panel_polys:
            for part in layout.parts:
                for polyline in part.layers["cuts"]:
                    panel_polys.append(list(polyline))

        bbox = self._get_bbox(panel_polys)
        self._panel_polys_by_mode[uv_mode] = panel_polys
        self._bbox_by_mode[uv_mode] = bbox
        return panel_polys, bbox

    @staticmethod
    def _get_bbox(polylines: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
        points = [point for polyline in polylines for point in polyline]
        if not points:
            return (0.0, 1.0, 0.0, 1.0)

        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)

        if abs(max_x - min_x) < 1e-9:
            max_x = min_x + 1.0
        if abs(max_y - min_y) < 1e-9:
            max_y = min_y + 1.0

        return min_x, max_x, min_y, max_y

    def update_preview(
        self,
        project: GliderProject,
        texture_svg_path: str | None,
        uv_mode: UVMapMode,
        precision: float,
    ) -> None:
        axes = self.canvas.axes
        axes.clear()

        glider_3d = project.get_glider_3d()
        panel_polys, (min_x, max_x, min_y, max_y) = self._get_panel_polys(glider_3d, uv_mode)

        if texture_svg_path:
            texture_path = Path(texture_svg_path)
            if texture_path.exists():
                try:
                    texture_path_str = str(texture_path)
                    if self._cached_texture_path != texture_path_str:
                        self._cached_texture = SVGTexture.read(texture_path)
                        self._cached_texture_path = texture_path_str

                    texture = self._cached_texture
                    if texture is not None:
                        image = texture.get_raster_bounded(8192, precision=precision, cache=True)
                    else:
                        image = None
                    if image is not None:
                        image_data = np.asarray(image)
                        # Align SVG raster orientation with layout coordinates.
                        image_data = np.flip(image_data, axis=0)
                        axes.imshow(
                            image_data,
                            extent=(min_x, max_x, min_y, max_y),
                            origin="lower",
                            interpolation="bilinear",
                        )
                except Exception:
                    logger.exception("Failed to render 2D texture preview: %s", texture_path)

        for poly in panel_polys:
            if not poly:
                continue
            x_values = [point[0] for point in poly]
            y_values = [point[1] for point in poly]
            closed_x = x_values + [x_values[0]]
            closed_y = y_values + [y_values[0]]
            # High-contrast UV outline to stay visible on bright and dark texture areas.
            axes.plot(closed_x, closed_y, color="black", linewidth=1.8, alpha=0.85)
            axes.plot(closed_x, closed_y, color="#ffb000", linewidth=0.95, alpha=0.95)

        axes.set_title("Texture and UV Overlay")
        axes.set_aspect("equal", adjustable="box")
        axes.set_xlim(min_x, max_x)
        axes.set_ylim(min_y, max_y)
        self.canvas.draw()


class TextureWizard(Wizard):
    copy_project = True

    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app, project)

        self._cached_uv_maps: dict[tuple[int, UVMapMode], WizardUVMap] = {}

        self._watcher = DelayedFileWatcher(self)
        self._watcher.fileChanged.connect(self._on_texture_file_changed)
        self._deferred_3d_timer = QtCore.QTimer(self)
        self._deferred_3d_timer.setSingleShot(True)
        self._deferred_3d_timer.setInterval(180)
        self._deferred_3d_timer.timeout.connect(self._apply_3d_preview)
        self._pending_3d_update = False

        self.setLayout(QtWidgets.QHBoxLayout())

        left_panel = QtWidgets.QWidget(self)
        left_layout = QtWidgets.QVBoxLayout()
        left_panel.setLayout(left_layout)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._texture_widget = TextureWizardWidget(left_panel, app)
        self._texture_widget.changed.connect(self._on_texture_settings_changed)
        self._texture_widget.export_requested.connect(self._export_uv_map)
        self._texture_widget.reload_requested.connect(self._reload_texture_from_disk)
        left_layout.addWidget(self._texture_widget)

        self._status = QtWidgets.QLabel("", left_panel)
        left_layout.addWidget(self._status)

        self._btn_apply = QtWidgets.QPushButton("Apply as New Glider", left_panel)
        self._btn_apply.clicked.connect(self._apply_as_new_glider)
        left_layout.addWidget(self._btn_apply)

        left_layout.addStretch()

        self._tabs = QtWidgets.QTabWidget(self)
        self._preview_3d = Texture3DPreview(self._tabs, app, self.project, self._get_uv_map)
        self._preview_2d = Texture2DPreview(self._tabs, self._get_uv_map)
        self._tabs.addTab(self._preview_2d, "2D Overlay")
        self._tabs.addTab(self._preview_3d, "3D View")
        self._tabs.setCurrentIndex(0)
        self._tabs.currentChanged.connect(self._on_tab_changed)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        splitter.addWidget(left_panel)
        splitter.addWidget(self._tabs)
        splitter.setSizes([360, 980])
        expect_value(self.layout()).addWidget(splitter)

        self._texture_widget.set_uv_mode(self.project.glider.texture.style)

        self._apply_settings()

    @staticmethod
    def _decode_texture_svg(svg_bytes: bytes) -> str | None:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return svg_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    def _get_uv_map(self, glider_3d: Glider, uv_mode: UVMapMode) -> WizardUVMap:
        cache_key = (id(glider_3d), uv_mode)
        cached = self._cached_uv_maps.get(cache_key)
        if cached is not None:
            return cached

        shape = self.project.glider.get_shape()

        uv_map: WizardUVMap
        if uv_mode == "mirrored":
            uv_map = UVMapMirrored(shape, glider_3d)
        else:
            uv_map = UVMapStacked(shape, glider_3d)

        self._cached_uv_maps[cache_key] = uv_map
        return uv_map

    def _apply_texture_to_glider(self, glider_3d: Glider, texture_svg: str | None, uv_mode: UVMapMode) -> None:
        if not texture_svg:
            glider_3d.texture = None
            return

        uv_map = self._get_uv_map(glider_3d, uv_mode)
        glider_3d.texture = Texture(
            uv_map=uv_map,
            texture=SVGTexture(texture_svg, dpi=self.project.glider.texture.dpi),
        )

    def _set_texture_watch_target(self) -> None:
        current_files = self._watcher.files()
        if current_files:
            self._watcher.removePaths(current_files)

        svg_path = self._texture_widget.svg_path
        if not svg_path:
            return

        if Path(svg_path).exists():
            self._watcher.addPath(svg_path)

    def _apply_settings(self) -> None:
        svg_path = self._texture_widget.svg_path
        uv_mode = self._texture_widget.uv_mode
        precision = self._texture_widget.texture_precision
        overlay = False

        self._sync_model_texture(svg_path, uv_mode)

        self._preview_3d.set_texture_settings(svg_path, uv_mode, precision, overlay)
        self._schedule_3d_preview_update()

        try:
            self._preview_2d.update_preview(self.project, svg_path, uv_mode, precision)
            self._status.setText("Texture settings applied to wizard-local previews.")
        except Exception:
            logger.exception("Failed to update 2D texture preview")
            self._status.setText("Failed to update 2D preview. See logs.")

    def _sync_model_texture(self, svg_path: str | None, uv_mode: UVMapMode) -> None:
        texture_svg: str | None = None
        if svg_path:
            path = Path(svg_path)
            if path.exists():
                texture_svg = self._decode_texture_svg(path.read_bytes())

        self.project.glider.texture.svg = texture_svg
        self.project.glider.texture.style = uv_mode
        self._apply_texture_to_glider(self.project.get_glider_3d(), texture_svg, uv_mode)

    def _export_uv_map(self) -> None:
        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export UV Map Template",
            "",
            "SVG files (*.svg)",
        )
        if not filename:
            return
        if not filename.lower().endswith(".svg"):
            filename += ".svg"

        try:
            uv_map = self._get_uv_map(self.project.get_glider_3d(), self._texture_widget.uv_mode)
            layout = uv_map.get_layout()
            layout = layout.scale(1000)
            layout.export_svg(filename, border=0.0)
        except Exception:
            logger.exception("Failed to export UV map SVG")
            QtWidgets.QMessageBox.critical(self, "Export UV Map", "Export failed - see log for details.")

    def _apply_as_new_glider(self) -> None:
        self._sync_model_texture(self._texture_widget.svg_path, self._texture_widget.uv_mode)
        self.apply(update=True)

    def _schedule_3d_preview_update(self) -> None:
        self._pending_3d_update = True
        if self._tabs.currentWidget() is self._preview_3d:
            self._preview_3d.clear_stale_scene()
            self._status.setText("3D preview stale; updating...")
            self._deferred_3d_timer.start()
        else:
            self._status.setText("3D preview stale. Open 3D View to refresh.")
            self._deferred_3d_timer.stop()

    def _apply_3d_preview(self) -> None:
        if not self._pending_3d_update:
            return
        self._pending_3d_update = False
        self._preview_3d.update_scene()
        self._status.setText("Texture settings applied to wizard-local previews.")

    def _on_tab_changed(self, index: int) -> None:
        if self._tabs.widget(index) is self._preview_3d and self._pending_3d_update:
            self._preview_3d.clear_stale_scene()
            self._status.setText("3D preview stale; updating...")
            self._deferred_3d_timer.start(40)

    def _reload_texture_from_disk(self) -> None:
        self._preview_3d.invalidate_texture_cache()
        self._preview_2d.invalidate_texture_cache()
        self._apply_settings()

    def _on_texture_file_changed(self, file_path: str) -> None:
        if not file_path:
            return

        # Re-register in case editor write strategy replaces the file inode.
        self._set_texture_watch_target()
        self._reload_texture_from_disk()

    def _on_texture_settings_changed(self) -> None:
        self._set_texture_watch_target()
        self._apply_settings()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._deferred_3d_timer.stop()
        self._preview_3d.shutdown()
        super().closeEvent(event)
