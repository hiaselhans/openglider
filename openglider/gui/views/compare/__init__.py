import logging

from openglider.utils.types import expect_value
from openglider.gui.app.app import GliderApp
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views.compare.arc import ArcView
from openglider.gui.views.compare.base import CompareView
from openglider.gui.views.compare.cell import CellView
from openglider.gui.views.compare.cell_plots import CellPlotView
from openglider.gui.views.compare.data import GliderTable
from openglider.gui.views.compare.glider_3d import Glider3DView
from openglider.gui.views.compare.rib import RibView
from openglider.gui.views.compare.rib_plots import RibPlotView
from openglider.gui.views.compare.shape import ShapeView
from openglider.gui.views.compare.table.lines_diff import GliderLineSetTable
from openglider.gui.views.compare.table.straps_diff import GliderStrapTable
from openglider.gui.views.compare.winglet import WingletView

logger = logging.getLogger(__name__)

class GliderPreview(QtWidgets.QWidget):
    tabs_widget: QtWidgets.QTabWidget
    tabs: dict[str, CompareView]
    shape_tab: ShapeView | None = None
    arc_tab: ArcView | None = None
    rib_plots_tab: RibPlotView | None = None
    ribs_tab: RibView | None = None
    cell_plots_tab: CellPlotView | None = None
    cells_tab: CellView | None = None
    table_tab: GliderTable | None = None
    lines_tab: GliderLineSetTable | None = None
    straps_tab: GliderStrapTable | None = None
    view_3d: Glider3DView | None = None
    _is_closing = False

    def __init__(self, app: GliderApp) -> None:
        super().__init__()
        self.app = app

        self.setLayout(QtWidgets.QHBoxLayout())
        self.tabs_widget = QtWidgets.QTabWidget(self)

        self.shape_tab = ShapeView(app)
        self.arc_tab = ArcView(app)
        self.rib_plots_tab = RibPlotView(app)
        self.ribs_tab = RibView(app)
        self.cell_plots_tab = CellPlotView(app)
        self.cells_tab = CellView(app)
        self.table_tab = GliderTable(app)
        self.lines_tab = GliderLineSetTable(app)
        self.straps_tab = GliderStrapTable(app)
        self.winglet_tab = WingletView(app)
        self.view_3d = Glider3DView(app)

        self.tabs = {
            "Shape": self.shape_tab,
            "Arc": self.arc_tab,
            "Rib Plots": self.rib_plots_tab,
            "Ribs": self.ribs_tab,
            "Cell Plots": self.cell_plots_tab,
            "Cells": self.cells_tab,
            "Table": self.table_tab,
            "Lines": self.lines_tab,
            "Straps": self.straps_tab,
            "Winglet": self.winglet_tab,
            "3D": self.view_3d
        }
        self.tab_names = list(self.tabs.keys())

        for name, widget in self.tabs.items():
            self.tabs_widget.addTab(widget, name)  # type: ignore

        self.tabs_widget.currentChanged.connect(self.set_tab)
        expect_value(self.layout()).addWidget(self.tabs_widget)


        #self._layout.addWidget(self.buttons, 0, 1)

        self.update()
    
    def get_active_view_name(self) -> str:
        index = self.tabs_widget.currentIndex()
        try:
            name = self.tab_names[index]
            return name
        except IndexError:
            return ""
    
    def set_tab(self) -> None:
        name = self.get_active_view_name()
        self.app.state.current_preview = name
        QtCore.QTimer.singleShot(0, self.update_current)

    def update_current(self) -> None:
        if self._is_closing:
            return

        if not self.app.state.current_preview:
            name = self.get_active_view_name()
            if name:
                self.app.state.current_preview = name
            else:
                return

        if self.app.state.current_preview not in self.tabs:
            return

        if self.app.state.current_preview != self.get_active_view_name():
            if self.app.state.current_preview in self.tab_names:
                self.tabs_widget.setCurrentIndex(self.tab_names.index(self.app.state.current_preview))

        self.tabs[self.app.state.current_preview].update_view()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        if self._is_closing:
            return

        self._is_closing = True
        blocker = QtCore.QSignalBlocker(self.tabs_widget)

        if self.view_3d is not None:
            self.view_3d.shutdown()

        for widget in self.tabs.values():
            widget.close()

        self.tabs_widget.clear()
        self.tabs.clear()
        self.shape_tab = None
        self.arc_tab = None
        self.rib_plots_tab = None
        self.ribs_tab = None
        self.cell_plots_tab = None
        self.cells_tab = None
        self.table_tab = None
        self.lines_tab = None
        self.straps_tab = None
        self.view_3d = None
        del blocker

