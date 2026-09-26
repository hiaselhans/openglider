from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Callable, Dict, TypeAlias

from openglider.utils.types import expect_value
from openglider.glider.project import GliderProject
from openglider.glider.rib import SingleSkinRib
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views_2d import Canvas, RsLayoutGraphics
from openglider.gui.wizzards.base import Wizard
from openglider.plots import Patterns
from openglider.plots.glider import PlotMaker
from openglider.rs import drawing
from openglider.utils.tasks import Task

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)

class PlotLayerSettings(QtWidgets.QWidget):
    layer_settings: dict[str, bool]
    layer_buttons: dict[str, QtWidgets.QCheckBox]
    changed = QtCore.Signal()

    def __init__(self, parent: Any=None) -> None:
        super().__init__(parent)
        self.layer_settings = {}
        self.layer_buttons = {}

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)

    def toggle_layer(self, layer_name: str) -> None:
        self.layer_settings[layer_name] = not self.layer_settings[layer_name]
        if layer_name in self.layer_buttons:
            self.layer_buttons[layer_name].setChecked(self.layer_settings[layer_name])
        
        self.changed.emit()

    def update_layers(self, drawing: object) -> None:
        available_layers: set[str] = set()

        for part in drawing.parts:
            for layer_name, layer in part.layers.items():
                layer_len = len(layer.lines) if hasattr(layer, "lines") else len(layer)
                if layer_len:
                    self.layer_settings.setdefault(layer_name, True)
                    available_layers.add(layer_name)

        for checkbox in self.layer_buttons.values():
            checkbox.deleteLater()
        self.layer_buttons.clear()

        available_layers_lst = list(available_layers)
        available_layers_lst.sort()

        def get_clickhandler(layer_name: str) -> Callable[[], None]:
            return lambda: self.toggle_layer(layer_name)
        
        for layer_name in available_layers_lst:
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(self.layer_settings.get(layer_name, True))
            checkbox.setText(f"{layer_name}")
            checkbox.clicked.connect(get_clickhandler(layer_name))
            self.layer_buttons[layer_name] = checkbox

            expect_value(self.layout()).addWidget(checkbox)


class PlotWizzard(Wizard):
    copy_project = False

    patterns: Patterns
    plotmaker: PlotMaker
    patterns_class: TypeAlias = Patterns

    directory: str | None = None

    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app, project)
        logger.info(f"PlotWizzard project: {project.filename}")

        layout = QtWidgets.QGridLayout()
        self.setLayout(layout)

        self.select_type = QtWidgets.QComboBox()
        self.select_type.addItems([
            "Ribs", "Panels", "Diagonals", "Miniribs"
        ])
        self.select_type.currentIndexChanged.connect(self.changed_type)
        layout.addWidget(self.select_type, 0, 0)

        self.select_element = QtWidgets.QComboBox()
        layout.addWidget(self.select_element, 0, 1)
        self.select_element.currentIndexChanged.connect(self.changed_element)

        self.select_layers = PlotLayerSettings()
        self.select_layers.changed.connect(self.update_config)
        layout.addWidget(self.select_layers, 0, 2, 1, 3)

        self._current_plotpart: RsLayoutGraphics | None = None
        self.canvas = Canvas()
        self.canvas.locked_aspect_ratio = True
        self.canvas.grid = True
        self.canvas.update_data()
        #self.canvas.addItem(Shape2D(self.project))
        #self.canvas.grid = True
        layout.addWidget(self.canvas.get_widget(), 1, 0, 1, 5)
        #self.canvas.update()

        self.label_path = QtWidgets.QLabel()
        layout.addWidget(self.label_path, 2, 0, 1, 3)

        self.button_path = QtWidgets.QPushButton("Directory")
        self.button_path.clicked.connect(self.select_path)
        layout.addWidget(self.button_path, 2, 3)

        self.button_do = QtWidgets.QPushButton("Unwrap")
        self.button_do.clicked.connect(self.run)
        layout.addWidget(self.button_do, 2, 4)

        self.patterns = self.patterns_class(self.project)
        self.plotmaker = self.patterns.plotmaker(self.patterns.project.get_glider_3d(), self.patterns.config)
        self.project = self.patterns.project
        self.project.filename = project.filename  # allow file-dialog to start at glider directory
        
        self.changed_type()

    def changed_type(self) -> None:
        type_str = self.select_type.currentText()
        self.select_element.clear()

        glider_3d = self.project.get_glider_3d()

        if type_str == "Ribs":
            self.select_element.addItems([f"Rib {i+1}" for i in range(len(glider_3d.ribs))])
        elif type_str in ("Panels", "Diagonals", "Miniribs"):
            self.select_element.addItems([f"Cell {i+1}" for i in range(len(glider_3d.cells))])

    def changed_element(self) -> None:
        config = self.plotmaker.config
        glider_3d = self.project.get_glider_3d()

        type_str = self.select_type.currentText()
        element_index = self.select_element.currentIndex()

        dy = self.patterns.config.patterns_align_dist_y
        dx = self.patterns.config.patterns_align_dist_x
        layout = None
        if self._current_plotpart:
            self.canvas.removeItem(self._current_plotpart)

        if type_str == "Ribs":
            rib = glider_3d.ribs[element_index]
            if isinstance(rib, SingleSkinRib):
                rib_plot = self.plotmaker.SingleSkinRibPlot(rib)
            else:
                rib_plot = self.plotmaker.RibPlot(rib)  # type: ignore
            rib_plot.flatten(glider_3d)
            dwg = rib_plot.plotpart
            layout = drawing.Layout([dwg])

        elif type_str == "Panels":
            cell = glider_3d.cells[element_index]
            cell_plot = self.plotmaker.CellPlotMaker(cell, config=config)

            _, panel_marks = cell_plot.get_rigidfoils()

            upper_parts = cell_plot.get_panels_upper(extra_marks=panel_marks)
            lower_parts = cell_plot.get_panels_lower(extra_marks=panel_marks)
            layout_upper = drawing.Layout.stack_column([drawing.Layout([part]) for part in upper_parts], dy)
            layout_lower = drawing.Layout.stack_column([drawing.Layout([part]) for part in lower_parts], dy)
            layout_lower = layout_lower.rotate(180, radians=False, center=None)

            layout = drawing.Layout.stack_row([layout_upper, layout_lower], dx)

        elif type_str == "Diagonals":
            cell = glider_3d.cells[element_index]
            cell_plot = self.plotmaker.CellPlotMaker(cell, config=config)
            layout_dribs = drawing.Layout.stack_column([drawing.Layout([part]) for part in cell_plot.get_dribs()], dy)
            straps = cell_plot.get_straps()
            layout_straps_upper = drawing.Layout.stack_column([drawing.Layout([part]) for part in straps[0]], dy)
            layout_straps_lower = drawing.Layout.stack_column([drawing.Layout([part]) for part in straps[1]], dy)

            layout = drawing.Layout.stack_row([layout_dribs, layout_straps_upper, layout_straps_lower], 0.2)
            
        elif type_str == "Miniribs":
            cell = glider_3d.cells[element_index]
            minirib_plot = self.plotmaker.CellPlotMaker(cell, config=config)
            layout = drawing.Layout.stack_column([drawing.Layout([part]) for part in minirib_plot.get_miniribs()], dy)
            #layout_lower = Layout.stack_column(cell_plot.get_panels_lower(), dy)
            #layout_lower.rotate(180, radians=False)

            #layout = Layout.stack_row([layout_upper, layout_lower], dx)

        else:
            return
        
        if layout is not None and layout.parts:
            self._current_plotpart = RsLayoutGraphics(layout)
            self.select_layers.update_layers(layout)
            self.update_config()
            #self.canvas.clear()
            self.canvas.addItem(self._current_plotpart)
            self.canvas.update()

    def update_config(self) -> None:
        if self._current_plotpart is None:
            return
        self._current_plotpart.shown_layers = [name for name, value in self.select_layers.layer_settings.items() if value]
        self._current_plotpart.update()
        self.canvas.update()
        
            
    def select_path(self) -> None:
        home = os.path.expanduser("~")

        if self.project.filename:
            home = os.path.dirname(self.project.filename)
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Abwicklung", home)
        if path:
            self.directory = path
            self.label_path.setText(path)
        logger.info(f"directory {path}")

    def run(self) -> None:
        if not self.directory:
            return

        if len(os.listdir(self.directory) ) != 0:
            raise ValueError(f"Direcotry {self.directory} is not empty")

        task = PatternTask(self.patterns, self.directory)
        if self.app.task_queue is None:
            raise RuntimeError("task queue is not initialized")
        self.app.task_queue.append(task)

        self.close()


class PatternTask(Task):
    multiprocessed: bool = False
    
    def __init__(self, patterns: Patterns, directory: str):
        self.patterns = patterns
        self.directory = directory

    def __json__(self) -> Dict[str, Any]:
        return {
            "patterns": self.patterns,
            "directory": self.directory
        }

    def get_name(self) -> str:
        return f"Patterns: {self.patterns.project.name} ({self.directory})"
    
    async def run(self) -> None:
        logger.info("patterns running")
        await self.execute(self.patterns.unwrap, self.directory)  # type: ignore
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.directory))
