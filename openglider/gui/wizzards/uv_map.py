from __future__ import annotations
from typing import TYPE_CHECKING
from openglider.glider.project import GliderProject

from openglider.gui.qt import QtWidgets
from openglider.gui.wizzards.base import Wizard
from openglider.gui.widgets import QTable

import pyqtgraph

from openglider.gui.app.app import GliderApp
from openglider.gui.state.glider_list import GliderCache
from openglider.gui.views_2d.canvas import Canvas, LayoutGraphics
from openglider.gui.widgets.select import EnumSelection
from openglider.plots.sketches.shapeplot import ShapePlot, ShapePlotConfig
from openglider.gui.qt import QtCore, QtWidgets

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow


class ShapePlotCache(GliderCache[tuple[ShapePlot, ShapePlot, str]]):
    def get_object(self, element: str) -> tuple[ShapePlot, ShapePlot, str]:
        project = self.elements[element]
        return ShapePlot(project.element), ShapePlot(project.element), element

class UVMapView(Wizard):
    grid = False
    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app, project)
        self.config = ShapePlotConfig()
        
        self.setLayout(QtWidgets.QVBoxLayout())
        self.app = app
        self.cache = ShapePlotCache(app.state.projects)
        update = self.cache.get_update()


        self.plots = Canvas()
        self.plots = pyqtgraph.GraphicsLayoutWidget()
        self.plots.setBackground('w')
        self.plot_upper = Canvas()
        dwg1 = ShapePlot(self.project)
        
        self.plot_upper.addItem(LayoutGraphics(dwg1))

        self.layout().addWidget(self.plots)



