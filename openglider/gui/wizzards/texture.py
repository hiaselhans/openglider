from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from openglider.glider.project import GliderProject
from openglider.glider.uv_map import SVGTexture, UVMap, UVMapMode
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views.compare.glider_3d.config import GliderViewConfig
from openglider.gui.views.compare.glider_3d.view import Glider3DCache
from openglider.gui.views_2d.mpl.canvas import PlotCanvas
from openglider.gui.views_3d.widgets import View3D
from openglider.gui.wizzards.base import Wizard

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow


logger = logging.getLogger(__name__)


class TextureWizardWidget(QtWidgets.QGroupBox):
    changed = QtCore.Signal()
    reload_requested = QtCore.Signal()

    def __init__(self, parent: QtWidgets.QWidget, app: MainWindow) -> None:
        super().__init__("Texture Wizard", parent)
        self.app = app
        self._svg_path: str | None = None
        self._auto_reload = False

        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(8, 8, 8, 8)
        self.layout().setSpacing(6)

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
        self._btn_export.clicked.connect(self._export_uv_map)
        path_layout.addWidget(self._btn_export, 1, 2)

        self._btn_reload = QtWidgets.QPushButton("Reload Now", self)
        self._btn_reload.clicked.connect(self.reload_requested)
        self._btn_reload.setEnabled(False)
        path_layout.addWidget(self._btn_reload, 1, 3)

        self._chk_auto_reload = QtWidgets.QCheckBox("Auto-reload texture on save", self)
        self._chk_auto_reload.toggled.connect(self._toggle_auto_reload)
        path_layout.addWidget(self._chk_auto_reload, 2, 0, 1, 5)

        self.layout().addLayout(path_layout)

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
        self._precision.setValue(0.35)
        self._precision.valueChanged.connect(self.changed)
        style_layout.addWidget(QtWidgets.QLabel("Texture precision:", self), 1, 0)
        style_layout.addWidget(self._precision, 1, 1)

        self.layout().addLayout(style_layout)

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

    def _toggle_auto_reload(self, checked: bool) -> None:
        self._auto_reload = checked
        self.changed.emit()

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

    def _export_uv_map(self) -> None:
        project = None
        for entry in self.app.state.projects.elements.values():
            project = entry.element
            break

        if project is None:
            QtWidgets.QMessageBox.warning(self, "Export UV Map", "No glider loaded.")
            return

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
            uv_map = UVMap(project.glider)
            layout = uv_map.get_layout(mode=self.uv_mode)
            layout.export_svg(filename, border=0.0)
        except Exception:
            logger.exception("Failed to export UV map SVG")
            QtWidgets.QMessageBox.critical(self, "Export UV Map", "Export failed - see log for details.")


class Texture3DPreview(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget, app: MainWindow) -> None:
        super().__init__(parent)
        self.app = app
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
        self.layout().addWidget(self.view_3d)

        self.view_3d.render_widget.destroyed.connect(self._on_view_destroyed)

        self.actor_cache = Glider3DCache(app.state.projects)

        self.texture_svg_path: str | None = None
        self.texture_uv_mode: UVMapMode = "stacked"
        self.texture_precision: float = 0.35
        self.texture_overlay: bool = False

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
        self.texture_overlay = overlay

    def invalidate_texture_cache(self) -> None:
        for actor in self.actor_cache.cache.values():
            actor.invalidate_texture_cache()

    def _on_view_destroyed(self, *_: object) -> None:
        self.shutdown()

    def update_scene(self) -> None:
        self.view_3d.clear()

        changeset = self.actor_cache.get_update()
        for actor in changeset.active:
            actor.set_panel_texture(
                self.texture_svg_path,
                self.texture_uv_mode,
                self.texture_precision,
                self.texture_overlay,
            )
            actor.add(self.view_3d, self._fixed_config)

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
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QVBoxLayout())

        self.canvas = PlotCanvas(zoom=True)
        self.canvas.grid = True
        self.canvas.update_settings()
        self.layout().addWidget(self.canvas)

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

        uv_map = UVMap(project.glider)
        layout = uv_map.get_layout(mode=uv_mode)
        panel_polys: list[list[tuple[float, float]]] = []
        for part in layout.parts:
            for polyline in part.layers["marks"]:
                panel_polys.append(list(polyline))

        if not panel_polys:
            for part in layout.parts:
                for polyline in part.layers["cuts"]:
                    panel_polys.append(list(polyline))
        min_x, max_x, min_y, max_y = self._get_bbox(panel_polys)

        if texture_svg_path:
            texture_path = Path(texture_svg_path)
            if texture_path.exists():
                try:
                    texture = SVGTexture(texture_path)
                    image = texture.get_raster_bounded(8192, precision=precision, cache=False)
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

        for polyline in panel_polys:
            if not polyline:
                continue
            x_values = [point[0] for point in polyline]
            y_values = [point[1] for point in polyline]
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
    copy_project = False

    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app, project)

        self._watcher = QtCore.QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_texture_file_changed)

        self.setLayout(QtWidgets.QHBoxLayout())

        left_panel = QtWidgets.QWidget(self)
        left_panel.setLayout(QtWidgets.QVBoxLayout())
        left_panel.layout().setContentsMargins(0, 0, 0, 0)

        self._texture_widget = TextureWizardWidget(left_panel, app)
        self._texture_widget.changed.connect(self._on_texture_settings_changed)
        self._texture_widget.reload_requested.connect(self._reload_texture_from_disk)
        left_panel.layout().addWidget(self._texture_widget)

        self._status = QtWidgets.QLabel("", left_panel)
        left_panel.layout().addWidget(self._status)
        left_panel.layout().addStretch()

        self._tabs = QtWidgets.QTabWidget(self)
        self._preview_3d = Texture3DPreview(self._tabs, app)
        self._preview_2d = Texture2DPreview(self._tabs)
        self._tabs.addTab(self._preview_2d, "2D Overlay")
        self._tabs.addTab(self._preview_3d, "3D View")
        self._tabs.setCurrentIndex(0)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal, self)
        splitter.addWidget(left_panel)
        splitter.addWidget(self._tabs)
        splitter.setSizes([360, 980])
        self.layout().addWidget(splitter)

        self._apply_settings()

    def _set_texture_watch_target(self) -> None:
        current_files = self._watcher.files()
        if current_files:
            self._watcher.removePaths(current_files)

        svg_path = self._texture_widget.svg_path
        if not svg_path or not self._texture_widget.auto_reload:
            return

        if Path(svg_path).exists():
            self._watcher.addPath(svg_path)

    def _apply_settings(self) -> None:
        svg_path = self._texture_widget.svg_path
        uv_mode = self._texture_widget.uv_mode
        precision = self._texture_widget.texture_precision
        overlay = False

        self._preview_3d.set_texture_settings(svg_path, uv_mode, precision, overlay)
        self._preview_3d.update_scene()

        try:
            self._preview_2d.update_preview(self.project, svg_path, uv_mode, precision)
            self._status.setText("Texture settings applied to wizard-local previews.")
        except Exception:
            logger.exception("Failed to update 2D texture preview")
            self._status.setText("Failed to update 2D preview. See logs.")

    def _reload_texture_from_disk(self) -> None:
        self._preview_3d.invalidate_texture_cache()
        self._apply_settings()

    def _on_texture_file_changed(self, file_path: str) -> None:
        if not file_path:
            return

        # Re-register in case editor write strategy replaces the file inode.
        self._set_texture_watch_target()
        if self._texture_widget.auto_reload:
            self._reload_texture_from_disk()

    def _on_texture_settings_changed(self) -> None:
        self._set_texture_watch_target()
        self._apply_settings()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._preview_3d.shutdown()
        super().closeEvent(event)
