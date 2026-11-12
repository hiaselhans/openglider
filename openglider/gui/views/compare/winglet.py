"""The Winglet tab of the preview: the pieces of the winglet of the selected glider, flattened"""
from __future__ import annotations

import logging

from openglider.glider.winglet import WingletGeometry
from openglider.gui.app.app import GliderApp
from openglider.gui.qt import QtWidgets
from openglider.gui.views.compare.base import CompareView
from openglider.gui.views_2d import Canvas, RsLayoutGraphics
from openglider.plots.glider.winglet import get_winglet_layout
from openglider.plots.patterns import Patterns
from openglider.utils.types import expect_value

logger = logging.getLogger(__name__)


class WingletView(QtWidgets.QWidget, CompareView):
    def __init__(self, app: GliderApp):
        super().__init__()
        self.app = app
        self.setLayout(QtWidgets.QVBoxLayout())

        self.label = QtWidgets.QLabel()
        self.canvas = Canvas()
        expect_value(self.layout()).addWidget(self.label)
        expect_value(self.layout()).addWidget(self.canvas.get_widget())

        self._drawing: RsLayoutGraphics | None = None
        self._drawn: object | None = None

    def update_view(self) -> None:
        project = self.app.state.projects.get_selected()
        if project is None or project is self._drawn:
            return
        self._drawn = project

        if self._drawing is not None:
            self.canvas.removeItem(self._drawing)
            self._drawing = None

        try:
            winglet = WingletGeometry.from_project(project)
            if winglet is None:
                self.label.setText(f"{project.name} has no winglet (Edit > Winglets)")
                return
            layout = get_winglet_layout(winglet, Patterns.DefaultConf(), project.get_glider_3d())
        except Exception as e:
            logger.exception("winglet preview")
            self.label.setText(f"the winglet could not be drawn: {e}")
            return

        self.label.setText(f"winglet of {project.name}: ribs and panels, as in the patterns")
        self._drawing = RsLayoutGraphics(layout)
        self.canvas.addItem(self._drawing)
        self.canvas.autoRange()
