"""
Edit > Winglets: the winglet of the glider (see openglider.glider.winglet). Add or remove it,
draw its planform and rib distribution, and its profile and ballooning curves, which run into
the glider's airfoils and balloonings as the glider's ProfileCurve and BallooningCurve do. The
airfoils and balloonings are edited with the glider's own editors (Airfoils, Ballooning).
Where it sits, its cell count, cloth and rib holes are set in the Winglet sheet of the .ods.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openglider.glider.parametric.shape import ParametricShape
from openglider.glider.project import GliderProject
from openglider.glider.parametric.winglet import remove_winglet_entries
from openglider.glider.winglet import add_default_winglet
from openglider.gui.qt import QtCore, QtWidgets
from openglider.gui.wizzards.base import Wizard
from openglider.gui.wizzards.input.distribution import DistributionInput
from openglider.gui.wizzards.input.shape import RibDistInput, ShapeInput, as_editable_shape
from openglider.utils.types import expect_value

if TYPE_CHECKING:
    from openglider.glider.parametric.glider import ParametricGlider
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)


class WingletWizard(Wizard):
    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app=app, project=project)
        self.setLayout(QtWidgets.QHBoxLayout())
        self.page: QtWidgets.QWidget | None = None
        self._build()

    @property
    def glider(self) -> ParametricGlider:
        return self.project.glider

    def _build(self) -> None:
        layout = expect_value(self.layout())
        if self.page is not None:
            layout.removeWidget(self.page)
            self.page.deleteLater()

        self.page = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        layout.addWidget(self.page)

        winglet = self.glider.winglet
        if winglet is None:
            right = QtWidgets.QWidget()
            empty = QtWidgets.QVBoxLayout()
            right.setLayout(empty)
            button = QtWidgets.QPushButton("Add winglet")
            button.clicked.connect(self._add)
            empty.addWidget(QtWidgets.QLabel("This glider has no winglet."))
            empty.addWidget(button)
            empty.addStretch()
            self.page.addWidget(right)
            return

        # the planform, edited on the winglet as a glider of its own
        self.shape_project = GliderProject(glider=winglet.get_parametric(self.glider), name="winglet")
        self.shape_input = ShapeInput(self.shape_project)

        self.distribution_input = RibDistInput(as_editable_shape(self.shape_project.glider.shape))
        self.distribution_input.on_change.append(lambda *args: self.shape_input.redraw())

        # along the span of the winglet into the airfoils and balloonings of the glider, as its
        # ProfileCurve and BallooningCurve
        self.profile_curve = winglet.profile_merge_curve.copy()
        self.profile_input = DistributionInput(self.profile_curve)
        self.ballooning_curve = winglet.ballooning_merge_curve.copy()
        self.ballooning_input = DistributionInput(self.ballooning_curve)

        shape_view = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        shape_view.addWidget(self._titled("Rib distribution", self.distribution_input.get_widget()))
        shape_view.addWidget(self._titled("Shape", self.shape_input.get_widget()))
        shape_view.setSizes([300, 700])

        views = [
            ("Shape", shape_view),
            ("Profile distribution", self._titled(
                f"Profile curve (into the glider's airfoils, 0 to {len(self.glider.profiles) - 1})",
                self.profile_input.get_widget(),
            )),
            ("Ballooning distribution", self._titled(
                f"Ballooning curve (into the glider's balloonings, 0 to {len(self.glider.balloonings) - 1})",
                self.ballooning_input.get_widget(),
            )),
        ]

        # one view at a time, picked at the top
        left = QtWidgets.QWidget()
        left.setLayout(QtWidgets.QVBoxLayout())
        self.view_choice = QtWidgets.QComboBox()
        self.view_stack = QtWidgets.QStackedWidget()
        for name, view in views:
            self.view_choice.addItem(name)
            self.view_stack.addWidget(view)
        self.view_choice.currentIndexChanged.connect(self.view_stack.setCurrentIndex)
        expect_value(left.layout()).addWidget(self.view_choice)
        expect_value(left.layout()).addWidget(self.view_stack)
        self.page.addWidget(left)

        right = QtWidgets.QWidget()
        form = QtWidgets.QVBoxLayout()
        right.setLayout(form)

        # what the curves run into: the index of each airfoil and ballooning of the glider
        lists = QtWidgets.QLabel("\n".join(
            ["Airfoils:"] + [f"  {i}: {p.name}" for i, p in enumerate(self.glider.profiles)]
            + ["", "Balloonings:"] + [f"  {i}: {b.name}" for i, b in enumerate(self.glider.balloonings)]
        ))
        form.addWidget(lists)

        form.addWidget(QtWidgets.QLabel("Placement, cells, cloth and rib holes:\nWinglet sheet of the .ods"))
        form.addStretch()

        remove_winglet = QtWidgets.QPushButton("Remove winglet")
        remove_winglet.clicked.connect(self._remove)
        form.addWidget(remove_winglet)

        apply = QtWidgets.QPushButton("Apply")
        apply.clicked.connect(self.apply)
        form.addWidget(apply)

        self.page.addWidget(right)
        self.page.setSizes([800, 250])

    @staticmethod
    def _titled(title: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QGroupBox(title)
        box.setLayout(QtWidgets.QVBoxLayout())
        expect_value(box.layout()).addWidget(widget)
        return box

    def _add(self) -> None:
        add_default_winglet(self.glider)
        self._build()

    def _remove(self) -> None:
        """a new revision of the glider without its winglet, nor the airfoils and balloonings only it used"""
        self.glider.winglet = None
        remove_winglet_entries(self.glider)
        # the page without a winglet has nothing to apply: done here
        super().apply()

    def _store(self) -> None:
        """the page into the winglet"""
        winglet = self.glider.winglet
        if winglet is None:
            return
        shape = self.shape_project.glider.shape.copy()
        # get_parametric hands the editor the winglet's own ParametricShape
        assert isinstance(shape, ParametricShape)
        winglet.shape = shape
        winglet.profile_merge_curve = self.profile_curve.copy()
        winglet.ballooning_merge_curve = self.ballooning_curve.copy()

    def apply(self, update: bool = True) -> None:
        self._store()
        super().apply(update)
