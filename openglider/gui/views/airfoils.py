from __future__ import annotations

import copy
import datetime
import logging
import math
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pyqtgraph

from openglider.airfoil.generators.parsec import ParsecAirfoil
from openglider.airfoil.profile_2d import Profile2D
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views.window import Window
from openglider.utils.colors import colorwheel

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)

SEPARATE_AIRFOILS = "Separate airfoils"
_KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole
_MODE_BASE = "base"
_MODE_ANALYTICS = "analytics"
_MODE_PARSEC = "parsec"

_ANALYTICS_SERIES = [
    ("Alpha", "aoa"),
    ("Cl", "cl"),
    ("Cd", "cd"),
    ("Cdp", "cdp"),
    ("Cm", "cm"),
    ("L/D", "cl_over_cd"),
]
_ANALYTICS_PLOT_PRESETS = [
    ("aoa", "cl"),
    ("aoa", "cd"),
    ("cd", "cl"),
    ("aoa", "cl_over_cd"),
]

_PARSEC_DEGREES = math.degrees(1)
_PARSEC_PARAMETERS = [
    ("x_max", "x max", 0.05, 0.8, 0.01, 3, 1.0),
    ("y_max", "y max", -0.05, 0.4, 0.005, 3, 1.0),
    ("nose_radius", "Nose radius", 0.001, 0.3, 0.002, 3, 1.0),
    ("front_percentage", "Front percentage [% of y max]", -1, 1, 5.0, 1, 100.0),
    ("top_radius", "Top radius", 0.005, 0.5, 0.01, 3, 1.0),
    ("rear_factor", "Rear 1 percentage [% of y max]", -100, 100, 5.0, 1, 100.0),
]


@dataclass
class AirfoilEntry:
    key: str
    source: str
    name: str
    airfoil: Profile2D
    separate: bool = False


class ModeSwitch(QtWidgets.QWidget):
    modeChanged = QtCore.Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)  # type: ignore[union-attr]
        self.layout().setSpacing(6)  # type: ignore[union-attr]
        self._buttons: dict[str, QtWidgets.QPushButton] = {}

    def add_mode(self, label: str, mode: str) -> None:
        button = QtWidgets.QPushButton(label)
        button.setCheckable(True)
        button.clicked.connect(lambda checked, mode=mode: self._clicked(mode, checked))
        self.layout().addWidget(button)  # type: ignore[union-attr]
        self._buttons[mode] = button

    def _clicked(self, mode: str, checked: bool) -> None:
        if not checked:
            self._buttons[mode].setChecked(True)
            return

        for key, button in self._buttons.items():
            button.setChecked(key == mode)
        self.modeChanged.emit(mode)

    def set_current_mode(self, mode: str) -> None:
        for key, button in self._buttons.items():
            button.blockSignals(True)
            button.setChecked(key == mode)
            button.blockSignals(False)

    def set_mode_enabled(self, mode: str, enabled: bool) -> None:
        button = self._buttons.get(mode)
        if button is not None:
            button.setEnabled(enabled)


class ApplyAirfoilsDialog(QtWidgets.QDialog):
    def __init__(self, app: MainWindow, entries: list[AirfoilEntry], parent: QtWidgets.QWidget | None=None) -> None:
        super().__init__(parent)
        self.app = app
        self._entries = {entry.key: entry for entry in entries}

        self.setWindowTitle("Apply airfoils to glider")
        self.resize(900, 520)
        self.setLayout(QtWidgets.QVBoxLayout())

        target_row = QtWidgets.QHBoxLayout()
        target_row.addWidget(QtWidgets.QLabel("Target glider"))
        self.target_combo = QtWidgets.QComboBox()
        for project in self.app.glider_projects:
            self.target_combo.addItem(project.name, project.name)
        selected_name = self.app.state.projects.selected_element
        if isinstance(selected_name, str):
            index = self.target_combo.findData(selected_name)
            if index >= 0:
                self.target_combo.setCurrentIndex(index)
        target_row.addWidget(self.target_combo, stretch=1)
        self.layout().addLayout(target_row)  # type: ignore[union-attr]

        lists_row = QtWidgets.QHBoxLayout()
        self.layout().addLayout(lists_row)  # type: ignore[union-attr]

        left_box = QtWidgets.QGroupBox("Available airfoils")
        left_box.setLayout(QtWidgets.QVBoxLayout())
        self.available_list = QtWidgets.QListWidget()
        self.available_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        for entry in entries:
            item = QtWidgets.QListWidgetItem(f"{entry.source}: {entry.name}")
            item.setData(_KEY_ROLE, entry.key)
            self.available_list.addItem(item)
        left_box.layout().addWidget(self.available_list)  # type: ignore[union-attr]
        lists_row.addWidget(left_box, stretch=3)

        middle = QtWidgets.QWidget()
        middle.setLayout(QtWidgets.QVBoxLayout())
        middle.layout().addStretch()  # type: ignore[union-attr]
        self.button_add = QtWidgets.QPushButton("Add ->")
        self.button_add.clicked.connect(self._add_selected)
        middle.layout().addWidget(self.button_add)  # type: ignore[union-attr]
        self.button_remove = QtWidgets.QPushButton("<- Remove")
        self.button_remove.clicked.connect(self._remove_selected)
        middle.layout().addWidget(self.button_remove)  # type: ignore[union-attr]
        self.button_clear = QtWidgets.QPushButton("Clear")
        self.button_clear.clicked.connect(self._clear_selected)
        middle.layout().addWidget(self.button_clear)  # type: ignore[union-attr]
        middle.layout().addStretch()  # type: ignore[union-attr]
        lists_row.addWidget(middle, stretch=1)

        right_box = QtWidgets.QGroupBox("Profiles to apply (ordered)")
        right_box.setLayout(QtWidgets.QVBoxLayout())
        self.selected_list = QtWidgets.QListWidget()
        self.selected_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        right_box.layout().addWidget(self.selected_list)  # type: ignore[union-attr]
        reorder_row = QtWidgets.QHBoxLayout()
        self.button_up = QtWidgets.QPushButton("Up")
        self.button_up.clicked.connect(self._move_up)
        self.button_down = QtWidgets.QPushButton("Down")
        self.button_down.clicked.connect(self._move_down)
        reorder_row.addWidget(self.button_up)
        reorder_row.addWidget(self.button_down)
        right_box.layout().addLayout(reorder_row)  # type: ignore[union-attr]
        lists_row.addWidget(right_box, stretch=3)

        self.status_label = QtWidgets.QLabel("Select one or more airfoils and build the target profile list.")
        self.layout().addWidget(self.status_label)  # type: ignore[union-attr]

        actions = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok |
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        actions.accepted.connect(self._apply)
        actions.rejected.connect(self.reject)
        self.layout().addWidget(actions)  # type: ignore[union-attr]

        self.available_list.itemDoubleClicked.connect(lambda _item: self._add_selected())
        self.selected_list.itemDoubleClicked.connect(lambda _item: self._remove_selected())

    def _add_selected(self) -> None:
        for item in self.available_list.selectedItems():
            key = item.data(_KEY_ROLE)
            if not isinstance(key, str):
                continue

            copied_item = QtWidgets.QListWidgetItem(item.text())
            copied_item.setData(_KEY_ROLE, key)
            self.selected_list.addItem(copied_item)

        self.status_label.setText(f"Selected profiles: {self.selected_list.count()}")

    def _remove_selected(self) -> None:
        for item in list(self.selected_list.selectedItems()):
            row = self.selected_list.row(item)
            self.selected_list.takeItem(row)

        self.status_label.setText(f"Selected profiles: {self.selected_list.count()}")

    def _clear_selected(self) -> None:
        self.selected_list.clear()
        self.status_label.setText("Selected profiles: 0")

    def _move_up(self) -> None:
        rows = sorted(self.selected_list.row(item) for item in self.selected_list.selectedItems())
        if not rows or rows[0] == 0:
            return

        for row in rows:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row - 1, item)
            item.setSelected(True)

    def _move_down(self) -> None:
        rows = sorted((self.selected_list.row(item) for item in self.selected_list.selectedItems()), reverse=True)
        if not rows or rows[0] == self.selected_list.count() - 1:
            return

        for row in rows:
            item = self.selected_list.takeItem(row)
            self.selected_list.insertItem(row + 1, item)
            item.setSelected(True)

    def _clone_airfoil(self, entry: AirfoilEntry) -> Profile2D:
        airfoil = entry.airfoil.copy()
        model = entry.airfoil.parsec_data
        if model is not None:
            airfoil.parsec_data = copy.deepcopy(model)

        return airfoil

    def _apply(self) -> None:
        if self.selected_list.count() < 1:
            self.status_label.setText("Add at least one airfoil.")
            return

        target_name = self.target_combo.currentData()
        if not isinstance(target_name, str):
            self.status_label.setText("Select a target glider.")
            return

        project = next((p for p in self.app.glider_projects if p.name == target_name), None)
        if project is None:
            self.status_label.setText("Target glider not found.")
            return

        new_profiles: list[Profile2D] = []
        for i in range(self.selected_list.count()):
            item = self.selected_list.item(i)
            key = item.data(_KEY_ROLE)
            if not isinstance(key, str):
                continue
            entry = self._entries.get(key)
            if entry is None:
                continue

            profile = self._clone_airfoil(entry)
            if not profile.name:
                profile.name = f"profile_{i + 1}"
            new_profiles.append(profile)

        if not new_profiles:
            self.status_label.setText("No valid airfoils selected.")
            return

        new_project = copy.deepcopy(project)
        new_project.glider.profiles = new_profiles
        new_project.update_all()
        new_project.changelog.append((
            datetime.datetime.now(),
            "ApplyAirfoilsWizard",
            f"Applied {len(new_profiles)} airfoil(s) from Airfoils tab"
        ))

        self.app.add_glider(new_project, increase_revision=True)
        self.app.state.projects.selected_element = new_project.name
        self.app.glider_list.render()
        self.app.current_glider_changed()
        self.app.update_menu()
        self.app.airfoil_view.refresh()
        self.accept()


class AirfoilView(Window):
    """
    Overview of all loaded airfoils: the airfoils of all gliders and separately loaded airfoils
    """
    widget_name = "Airfoils"

    def __init__(self, app: MainWindow) -> None:
        super().__init__(app)
        self.entries: dict[str, AirfoilEntry] = {}
        self._checked: dict[str, bool] = {}
        self._parsec_edit_active = False
        self._parsec_edit_entry_key: str | None = None
        self._parsec_model: ParsecAirfoil | None = None
        self._parsec_preview_airfoil: Profile2D | None = None
        self._parsec_preview_controlpoints: list[list[tuple[float, float]]] | None = None
        self._parsec_factors: dict[str, float] = {}
        self._parsec_spinboxes: dict[str, QtWidgets.QDoubleSpinBox] = {}
        self._analytics_cache: dict[str, dict[str, object]] = {}
        self._mode = _MODE_BASE
        self.analytics_plot_widgets: list[pyqtgraph.PlotWidget] = []
        self.analytics_x_selectors: list[QtWidgets.QComboBox] = []
        self.analytics_y_selectors: list[QtWidgets.QComboBox] = []

        self.setLayout(QtWidgets.QHBoxLayout())
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.layout().addWidget(splitter)  # type: ignore[union-attr]

        # left: mode switcher + shared list + mode-specific controls
        left = QtWidgets.QWidget()
        left.setLayout(QtWidgets.QVBoxLayout())

        mode_row = QtWidgets.QHBoxLayout()
        mode_row.addWidget(QtWidgets.QLabel("Mode"))
        self.mode_switch = ModeSwitch()
        self.mode_switch.add_mode("Base", _MODE_BASE)
        self.mode_switch.add_mode("Analytics", _MODE_ANALYTICS)
        self.mode_switch.add_mode("Parsec edit", _MODE_PARSEC)
        self.mode_switch.modeChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode_switch)
        left.layout().addLayout(mode_row)  # type: ignore[union-attr]

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self.draw)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.tree.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        left.layout().addWidget(self.tree)  # type: ignore[union-attr]

        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.info.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Maximum)
        left.layout().addWidget(self.info)  # type: ignore[union-attr]

        self.mode_stack = QtWidgets.QStackedWidget()
        self.mode_stack.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Ignored)
        left.layout().addWidget(self.mode_stack)  # type: ignore[union-attr]
        left.layout().setStretch(1, 8)  # type: ignore[union-attr]
        left.layout().setStretch(3, 2)  # type: ignore[union-attr]

        self.base_page = QtWidgets.QWidget()
        self.base_page.setLayout(QtWidgets.QVBoxLayout())
        self.mode_stack.addWidget(self.base_page)

        self.button_load = QtWidgets.QPushButton("Load airfoil (.dat)")
        self.button_load.clicked.connect(self.load_dialog)
        self.button_remove = QtWidgets.QPushButton("Remove")
        self.button_remove.clicked.connect(self.remove_current)
        self.button_export = QtWidgets.QPushButton("Export (.dat)")
        self.button_export.clicked.connect(self.export_current)
        self.button_fit = QtWidgets.QPushButton("Fit PARSEC...")
        self.button_fit.clicked.connect(self.open_parsec_wizard)
        self.button_apply_to_glider = QtWidgets.QPushButton("Apply to glider...")
        self.button_apply_to_glider.clicked.connect(self.open_apply_to_glider_dialog)

        for button in (
            self.button_load,
            self.button_remove,
            self.button_export,
            self.button_fit,
            self.button_apply_to_glider,
        ):
            self.base_page.layout().addWidget(button)  # type: ignore[union-attr]

        self.base_page.layout().addStretch()  # type: ignore[union-attr]

        self.analytics_page = QtWidgets.QWidget()
        self.analytics_page.setLayout(QtWidgets.QVBoxLayout())
        self.mode_stack.addWidget(self.analytics_page)

        analytics_form = QtWidgets.QFormLayout()

        self.analytics_reynolds = QtWidgets.QDoubleSpinBox()
        self.analytics_reynolds.setRange(1e4, 1e9)
        self.analytics_reynolds.setDecimals(0)
        self.analytics_reynolds.setSingleStep(1e5)
        self.analytics_reynolds.setValue(2e6)
        self.analytics_reynolds.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("Reynolds", self.analytics_reynolds)

        self.analytics_mach = QtWidgets.QDoubleSpinBox()
        self.analytics_mach.setRange(0, 0.95)
        self.analytics_mach.setDecimals(3)
        self.analytics_mach.setSingleStep(0.01)
        self.analytics_mach.setValue(0.0)
        self.analytics_mach.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("Mach", self.analytics_mach)

        self.analytics_ncrit = QtWidgets.QDoubleSpinBox()
        self.analytics_ncrit.setRange(0, 20)
        self.analytics_ncrit.setDecimals(2)
        self.analytics_ncrit.setSingleStep(0.2)
        self.analytics_ncrit.setValue(4.0)
        self.analytics_ncrit.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("Ncrit", self.analytics_ncrit)

        self.analytics_xtr_top = QtWidgets.QDoubleSpinBox()
        self.analytics_xtr_top.setRange(0, 1)
        self.analytics_xtr_top.setDecimals(3)
        self.analytics_xtr_top.setSingleStep(0.05)
        self.analytics_xtr_top.setValue(0.5)
        self.analytics_xtr_top.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("Xtr top", self.analytics_xtr_top)

        self.analytics_xtr_bottom = QtWidgets.QDoubleSpinBox()
        self.analytics_xtr_bottom.setRange(0, 1)
        self.analytics_xtr_bottom.setDecimals(3)
        self.analytics_xtr_bottom.setSingleStep(0.05)
        self.analytics_xtr_bottom.setValue(0.5)
        self.analytics_xtr_bottom.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("Xtr bottom", self.analytics_xtr_bottom)

        self.analytics_aoa_start = QtWidgets.QDoubleSpinBox()
        self.analytics_aoa_start.setRange(-25, 25)
        self.analytics_aoa_start.setDecimals(2)
        self.analytics_aoa_start.setSingleStep(0.5)
        self.analytics_aoa_start.setValue(-3.0)
        self.analytics_aoa_start.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("AOA start [deg]", self.analytics_aoa_start)

        self.analytics_aoa_end = QtWidgets.QDoubleSpinBox()
        self.analytics_aoa_end.setRange(-25, 25)
        self.analytics_aoa_end.setDecimals(2)
        self.analytics_aoa_end.setSingleStep(0.5)
        self.analytics_aoa_end.setValue(12.0)
        self.analytics_aoa_end.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("AOA end [deg]", self.analytics_aoa_end)

        self.analytics_steps = QtWidgets.QSpinBox()
        self.analytics_steps.setRange(3, 120)
        self.analytics_steps.setValue(20)
        self.analytics_steps.valueChanged.connect(lambda _value: self._draw_analytics())
        analytics_form.addRow("AOA steps", self.analytics_steps)

        self.analytics_page.layout().addLayout(analytics_form)  # type: ignore[union-attr]

        self.button_calc_analytics = QtWidgets.QPushButton("Recalculate stale")
        self.button_calc_analytics.clicked.connect(self._recalculate_stale_analytics)
        self.analytics_page.layout().addWidget(self.button_calc_analytics)  # type: ignore[union-attr]

        self.analytics_status = QtWidgets.QLabel()
        self.analytics_status.setWordWrap(True)
        self.analytics_page.layout().addWidget(self.analytics_status)  # type: ignore[union-attr]
        self.analytics_page.layout().addStretch()  # type: ignore[union-attr]

        self.parsec_page = QtWidgets.QWidget()
        self.parsec_page.setLayout(QtWidgets.QVBoxLayout())
        self.mode_stack.addWidget(self.parsec_page)

        self.parsec_page.layout().addWidget(QtWidgets.QLabel("PARSEC parameters"))  # type: ignore[union-attr]

        for side in ("upper", "lower"):
            box = QtWidgets.QGroupBox(side.capitalize())
            form = QtWidgets.QFormLayout()
            box.setLayout(form)
            for name, label, minimum, maximum, step, decimals, factor in _PARSEC_PARAMETERS:
                key = f"{side}_{name}"
                spinbox = QtWidgets.QDoubleSpinBox()
                spinbox.setDecimals(int(decimals))
                spinbox.setRange(float(minimum * factor), float(maximum * factor))
                spinbox.setSingleStep(float(step))
                spinbox.valueChanged.connect(
                    lambda value, key=key: self._parsec_parameter_changed(key, value)  # type: ignore[misc]
                )
                form.addRow(label, spinbox)
                self._parsec_factors[key] = float(factor)
                self._parsec_spinboxes[key] = spinbox
            self.parsec_page.layout().addWidget(box)  # type: ignore[union-attr]

        
        shared_trailing = QtWidgets.QGroupBox("Shared trailing edge")
        shared_trailing_form = QtWidgets.QFormLayout()
        shared_trailing.setLayout(shared_trailing_form)

        self.parsec_trailing_angle = QtWidgets.QDoubleSpinBox()
        self.parsec_trailing_angle.setDecimals(2)
        self.parsec_trailing_angle.setRange(-80, 80)
        self.parsec_trailing_angle.setSingleStep(1.0)
        self.parsec_trailing_angle.valueChanged.connect(self._parsec_shared_trailing_changed)
        shared_trailing_form.addRow("Trailing edge angle [deg]", self.parsec_trailing_angle)

        self.parsec_trailing_percentage = QtWidgets.QDoubleSpinBox()
        self.parsec_trailing_percentage.setDecimals(1)
        self.parsec_trailing_percentage.setRange(-100.0, 100.0)
        self.parsec_trailing_percentage.setSingleStep(5.0)
        self.parsec_trailing_percentage.valueChanged.connect(self._parsec_shared_trailing_changed)
        shared_trailing_form.addRow("Trailing edge percentage [% of y max]", self.parsec_trailing_percentage)

        self.parsec_page.layout().addWidget(shared_trailing)  # type: ignore[union-attr]

        parsec_result = QtWidgets.QFormLayout()
        self.parsec_numpoints = QtWidgets.QSpinBox()
        self.parsec_numpoints.setRange(10, 300)
        self.parsec_numpoints.setValue(80)
        self.parsec_numpoints.valueChanged.connect(self._update_parsec_preview)
        parsec_result.addRow("Result points", self.parsec_numpoints)

        self.parsec_result_name = QtWidgets.QLineEdit("parsec_edited")
        parsec_result.addRow("Name", self.parsec_result_name)
        self.parsec_page.layout().addLayout(parsec_result)  # type: ignore[union-attr]

        self.parsec_status = QtWidgets.QLabel()
        self.parsec_status.setWordWrap(True)
        self.parsec_page.layout().addWidget(self.parsec_status)  # type: ignore[union-attr]

        self.button_parsec_add = QtWidgets.QPushButton("Add edited airfoil")
        self.button_parsec_add.clicked.connect(self._add_parsec_edited_airfoil)
        self.parsec_page.layout().addWidget(self.button_parsec_add)  # type: ignore[union-attr]
        self.parsec_page.layout().addStretch()  # type: ignore[union-attr]


        # right: mode-specific view
        self.right_stack = QtWidgets.QStackedWidget()

        self.plot = pyqtgraph.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.legend = self.plot.addLegend()

        self.analytics_view = QtWidgets.QWidget()
        self.analytics_view.setLayout(QtWidgets.QVBoxLayout())
        plots_grid = QtWidgets.QGridLayout()
        self.analytics_view.layout().addLayout(plots_grid)  # type: ignore[union-attr]

        for i in range(4):
            container = QtWidgets.QWidget()
            container.setLayout(QtWidgets.QVBoxLayout())

            selectors_row = QtWidgets.QHBoxLayout()
            selectors_row.addWidget(QtWidgets.QLabel(f"Plot {i + 1}"))

            x_selector = QtWidgets.QComboBox()
            y_selector = QtWidgets.QComboBox()
            for label, key in _ANALYTICS_SERIES:
                x_selector.addItem(f"x: {label}", key)
                y_selector.addItem(f"y: {label}", key)

            x_default, y_default = _ANALYTICS_PLOT_PRESETS[i]
            x_selector.setCurrentIndex(max(0, x_selector.findData(x_default)))
            y_selector.setCurrentIndex(max(0, y_selector.findData(y_default)))
            x_selector.currentIndexChanged.connect(lambda _idx: self._draw_analytics())
            y_selector.currentIndexChanged.connect(lambda _idx: self._draw_analytics())

            selectors_row.addWidget(x_selector)
            selectors_row.addWidget(y_selector)
            container.layout().addLayout(selectors_row)  # type: ignore[union-attr]

            plot = pyqtgraph.PlotWidget()
            plot.showGrid(x=True, y=True, alpha=0.3)
            plot.addLegend()
            container.layout().addWidget(plot)  # type: ignore[union-attr]

            row = i // 2
            col = i % 2
            plots_grid.addWidget(container, row, col)

            self.analytics_plot_widgets.append(plot)
            self.analytics_x_selectors.append(x_selector)
            self.analytics_y_selectors.append(y_selector)

        self.right_stack.addWidget(self.plot)
        self.right_stack.addWidget(self.analytics_view)
        splitter.addWidget(left)
        splitter.addWidget(self.right_stack)
        splitter.setSizes([300, 900])

        self.refresh()
        self._set_mode(_MODE_BASE)

    def get_entries(self) -> list[AirfoilEntry]:
        entries: list[AirfoilEntry] = []

        for project in self.app.glider_projects:
            for i, airfoil in enumerate(project.glider.profiles):
                entries.append(AirfoilEntry(
                    key=f"glider:{project.name}:{i}",
                    source=project.name,
                    name=f"{i}: {airfoil.name}",
                    airfoil=airfoil
                ))

        for name, airfoil in self.app.state.airfoils.items():
            entries.append(AirfoilEntry(
                key=f"separate:{name}",
                source=SEPARATE_AIRFOILS,
                name=name,
                airfoil=airfoil,
                separate=True
            ))

        return entries

    def refresh(self) -> None:
        """rebuild the list from the current application state"""
        if self.entries:
            self._checked.update(self._get_checked())

        current = self._current_key()
        selected_glider = self.app.state.projects.selected_element

        self.entries = {entry.key: entry for entry in self.get_entries()}

        self.tree.blockSignals(True)
        self.tree.clear()

        groups: dict[str, QtWidgets.QTreeWidgetItem] = {}
        current_item: QtWidgets.QTreeWidgetItem | None = None
        for entry in self.entries.values():
            group = groups.get(entry.source)
            if group is None:
                group = QtWidgets.QTreeWidgetItem(self.tree, [entry.source])
                group.setFlags(
                    group.flags() |
                    QtCore.Qt.ItemFlag.ItemIsUserCheckable |
                    QtCore.Qt.ItemFlag.ItemIsAutoTristate
                )
                group.setExpanded(True)
                groups[entry.source] = group

            item = QtWidgets.QTreeWidgetItem(group, [entry.name])
            item.setData(0, _KEY_ROLE, entry.key)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)

            checked = self._checked.get(entry.key)
            if checked is None:
                checked = entry.separate or entry.source == selected_glider
            item.setCheckState(
                0, QtCore.Qt.CheckState.Checked if checked else QtCore.Qt.CheckState.Unchecked
            )

            if entry.key == current:
                current_item = item

        if current_item is not None:
            self.tree.setCurrentItem(current_item)

        self.tree.blockSignals(False)
        self._update_buttons()
        self.draw()
        self._draw_analytics()

    def _items(self) -> list[QtWidgets.QTreeWidgetItem]:
        result = []
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            if group is None:
                continue
            for j in range(group.childCount()):
                result.append(group.child(j))

        return result

    def _get_checked(self) -> dict[str, bool]:
        return {
            item.data(0, _KEY_ROLE): item.checkState(0) == QtCore.Qt.CheckState.Checked
            for item in self._items()
        }

    def _current_key(self) -> str | None:
        item = self.tree.currentItem()
        if item is None:
            return None

        key = item.data(0, _KEY_ROLE)
        return key if isinstance(key, str) else None

    def get_current(self) -> AirfoilEntry | None:
        key = self._current_key()
        if key is None:
            return None

        return self.entries.get(key)

    def _current_changed(self, *args: object) -> None:
        self._update_buttons()
        self.draw()

    def _mode_changed(self, mode: str) -> None:
        if mode == _MODE_PARSEC and not self._parsec_edit_active:
            entry = self.get_current()
            model = entry.airfoil.parsec_data
            if model is not None:
                self._start_parsec_edit(entry)
                return

            self.mode_switch.set_current_mode(_MODE_BASE)
            mode = _MODE_BASE

        if mode != _MODE_PARSEC and self._parsec_edit_active:
            self._set_parsec_edit_active(False)

        self._set_mode(mode)

    def _set_mode(self, mode: str) -> None:
        self.mode_switch.set_current_mode(mode)
        self._mode = mode
        self.info.setVisible(mode == _MODE_BASE)
        self.tree.setVisible(mode != _MODE_PARSEC)
        if mode == _MODE_ANALYTICS:
            self.mode_stack.setCurrentWidget(self.analytics_page)
            self.right_stack.setCurrentWidget(self.analytics_view)
            self._draw_analytics()
        elif mode == _MODE_PARSEC:
            self.mode_stack.setCurrentWidget(self.parsec_page)
            self.right_stack.setCurrentWidget(self.plot)
        else:
            self.mode_stack.setCurrentWidget(self.base_page)
            self.right_stack.setCurrentWidget(self.plot)
            self._update_buttons()

    def _update_buttons(self) -> None:
        if self._parsec_edit_active:
            return

        entry = self.get_current()
        self.button_remove.setEnabled(entry is not None and entry.separate)
        self.button_export.setEnabled(entry is not None)
        self.button_fit.setEnabled(entry is not None)
        self.button_apply_to_glider.setEnabled(len(self.entries) > 0 and len(self.app.glider_projects) > 0)
        parsec_enabled = entry is not None and  entry.airfoil.parsec_data is not None
        self.mode_switch.set_mode_enabled(_MODE_PARSEC, parsec_enabled or self._parsec_edit_active)

        if self._mode == _MODE_PARSEC and not self._parsec_edit_active and not parsec_enabled:
            self._set_mode(_MODE_BASE)

        if entry is None:
            self.info.setText("")
            return

        airfoil = entry.airfoil
        self.info.setText(
            f"{entry.name} ({entry.source})\n"
            f"points: {airfoil.numpoints}\n"
            f"thickness: {airfoil.thickness * 100:.2f}%\n"
            f"camber: {airfoil.camber * 100:.2f}%"
        )

    def draw(self, *args: object) -> None:
        self.plot.clear()

        checked = self._get_checked()
        current = self._current_key()
        colors = colorwheel(max(len(checked), 1))

        for color, (key, is_checked) in zip(colors, checked.items()):
            if key not in self.entries or (not is_checked and key != current):
                continue

            entry = self.entries[key]
            nodes = entry.airfoil.curve.nodes
            pen = pyqtgraph.mkPen(color=color.rgb(), width=3 if key == current else 1.5)
            self.plot.plot(
                [p[0] for p in nodes],
                [p[1] for p in nodes],
                pen=pen,
                name=f"{entry.source}: {entry.name}"
            )

            parsec_controlpoints = None
            parsec_model = entry.airfoil.parsec_data
            if parsec_model is not None:
                parsec_controlpoints = self._collect_parsec_controlpoints(parsec_model)
            if key == current and isinstance(parsec_controlpoints, list):
                for polyline in parsec_controlpoints:
                    if not polyline:
                        continue
                    self.plot.plot(
                        [p[0] for p in polyline],
                        [p[1] for p in polyline],
                        pen=pyqtgraph.mkPen(color=(120, 120, 120), width=1, style=QtCore.Qt.PenStyle.DotLine),
                        symbol="o",
                        symbolSize=4,
                        symbolBrush=(120, 120, 120)
                    )

        if self._parsec_edit_active and self._parsec_preview_airfoil is not None:
            nodes = self._parsec_preview_airfoil.curve.nodes
            self.plot.plot(
                [p[0] for p in nodes],
                [p[1] for p in nodes],
                pen=pyqtgraph.mkPen(color=(255, 70, 70), width=2.5),
                name="parsec preview"
            )

            if self._parsec_preview_controlpoints is not None:
                for polyline in self._parsec_preview_controlpoints:
                    if not polyline:
                        continue
                    self.plot.plot(
                        [p[0] for p in polyline],
                        [p[1] for p in polyline],
                        pen=pyqtgraph.mkPen(color=(255, 120, 120), width=1, style=QtCore.Qt.PenStyle.DotLine),
                        symbol="o",
                        symbolSize=4,
                        symbolBrush=(255, 120, 120)
                    )
        if self._mode == _MODE_ANALYTICS:
            self._draw_analytics()

    def _analytics_settings(self) -> tuple[float, float, float, float, float, float, float, int]:
        return (
            float(self.analytics_reynolds.value()),
            float(self.analytics_mach.value()),
            float(self.analytics_ncrit.value()),
            float(self.analytics_xtr_top.value()),
            float(self.analytics_xtr_bottom.value()),
            float(self.analytics_aoa_start.value()),
            float(self.analytics_aoa_end.value()),
            int(self.analytics_steps.value())
        )

    def _entry_geometry_hash(self, entry: AirfoilEntry) -> int:
        rounded_nodes = tuple((round(float(p[0]), 6), round(float(p[1]), 6)) for p in entry.airfoil.curve.nodes)
        return hash(rounded_nodes)

    def _analytics_signature(self, entry: AirfoilEntry) -> tuple[tuple[float, float, float, float, float, float, float, int], int]:
        return (self._analytics_settings(), self._entry_geometry_hash(entry))

    def _entry_color_map(self) -> dict[str, tuple[int, int, int]]:
        checked = self._get_checked()
        colors = colorwheel(max(len(checked), 1))
        return {
            key: color.rgb()
            for color, key in zip(colors, checked)
        }

    def _is_visible_entry(self, key: str, is_checked: bool, current: str | None) -> bool:
        return is_checked or key == current

    def _clear_plot(self, plot: pyqtgraph.PlotWidget) -> None:
        legend = getattr(plot.plotItem, "legend", None)
        if legend is not None:
            legend.clear()
        plot.clear()

    def _analytics_values(self, data: object, key: str) -> list[float]:
        if key == "cl_over_cd":
            cl = data["cl"].to_list()
            cd = data["cd"].to_list()
            return [float(c_l / c_d) if abs(float(c_d)) > 1e-9 else float("nan") for c_l, c_d in zip(cl, cd)]

        return [float(value) for value in data[key].to_list()]

    def _draw_analytics(self) -> None:
        for plot in self.analytics_plot_widgets:
            self._clear_plot(plot)

        checked = self._get_checked()
        current = self._current_key()
        color_map = self._entry_color_map()
        visible = [
            (key, self.entries[key])
            for key, is_checked in checked.items()
            if key in self.entries and self._is_visible_entry(key, is_checked, current)
        ]

        stale_count = 0
        plotted = 0
        missing_count = 0
        error_count = 0

        for key, entry in visible:
            signature = self._analytics_signature(entry)
            cached = self._analytics_cache.get(key)
            is_stale = cached is None or cached.get("signature") != signature
            if is_stale:
                stale_count += 1

            if cached is None:
                missing_count += 1
                continue

            error = cached.get("error")
            if isinstance(error, str) and error:
                error_count += 1
                continue

            data = cached.get("data")
            if data is None or data.empty:  # type: ignore[attr-defined]
                continue

            color = color_map.get(key, (255, 255, 255))
            pen = pyqtgraph.mkPen(
                color=color,
                width=2 if key == current else 1.5,
                style=QtCore.Qt.PenStyle.DotLine if is_stale else QtCore.Qt.PenStyle.SolidLine
            )
            label = f"{entry.source}: {entry.name}{' (stale)' if is_stale else ''}"

            for i, plot in enumerate(self.analytics_plot_widgets):
                x_key = str(self.analytics_x_selectors[i].currentData())
                y_key = str(self.analytics_y_selectors[i].currentData())
                x_values = self._analytics_values(data, x_key)
                y_values = self._analytics_values(data, y_key)
                plot.plot(
                    x_values,
                    y_values,
                    pen=pen,
                    name=label
                )
                plot.setLabel("bottom", self.analytics_x_selectors[i].currentText().replace("x: ", ""))
                plot.setLabel("left", self.analytics_y_selectors[i].currentText().replace("y: ", ""))
            plotted += 1

        self.analytics_status.setText(
            f"visible: {len(visible)}  plotted: {plotted}  stale: {stale_count}  "
            f"missing: {missing_count}  errors: {error_count}"
        )

    def _calculate_analytics_for_entry(self, entry: AirfoilEntry) -> None:
        reynolds, mach, ncrit, xtr_top, xtr_bottom, aoa_start, aoa_end, steps = self._analytics_settings()

        entry.airfoil.reynolds = reynolds
        entry.airfoil.mach = mach
        entry.airfoil.ncrit = ncrit
        entry.airfoil.xtr_top = xtr_top
        entry.airfoil.xtr_bottom = xtr_bottom

        signature = self._analytics_signature(entry)
        try:
            data = entry.airfoil.xfoil_polar(aoa_start, aoa_end, steps=steps, degree=True)
            self._analytics_cache[entry.key] = {
                "signature": signature,
                "data": data,
                "error": ""
            }
        except Exception as e:
            logger.warning(f"xfoil polar failed for {entry.name}: {e}")
            self._analytics_cache[entry.key] = {
                "signature": signature,
                "data": None,
                "error": str(e)
            }

    def _recalculate_stale_analytics(self) -> None:
        if not self.entries:
            self.analytics_status.setText("No airfoils available")
            return

        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        try:
            count = 0
            for entry in self.entries.values():
                signature = self._analytics_signature(entry)
                cached = self._analytics_cache.get(entry.key)
                if cached is not None and cached.get("signature") == signature:
                    continue

                self._calculate_analytics_for_entry(entry)
                count += 1
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        self._draw_analytics()
        self.analytics_status.setText(f"Recalculated {count} stale result(s)")

    # editing separate airfoils

    def add_airfoil(self, name: str, airfoil: Profile2D) -> str:
        """add a separate airfoil. returns the (unique) name"""
        unique_name = name
        i = 1
        while unique_name in self.app.state.airfoils:
            i += 1
            unique_name = f"{name}_{i}"

        airfoil.name = unique_name
        self.app.state.airfoils[unique_name] = airfoil
        self._checked[f"separate:{unique_name}"] = True
        self.refresh()

        return unique_name

    def _select_entry_by_key(self, key: str) -> None:
        for item in self._items():
            if item.data(0, _KEY_ROLE) == key:
                self.tree.setCurrentItem(item)
                return

    def _collect_parsec_controlpoints(self, model: ParsecAirfoil) -> list[list[tuple[float, float]]]:
        controlpoints: list[list[tuple[float, float]]] = []
        for curve in model.get_curves().values():
            controlpoints.append([(float(p[0]), float(p[1])) for p in curve.controlpoints.nodes])

        return controlpoints

    def _attach_parsec_metadata(self, airfoil: Profile2D, model: ParsecAirfoil, numpoints: int) -> None:
        model_copy = copy.deepcopy(model)
        model_copy.numpoints = int(numpoints)
        airfoil.parsec_data = model_copy

    def _set_parsec_edit_active(self, active: bool) -> None:
        self._parsec_edit_active = active
        if active:
            self._set_mode(_MODE_PARSEC)
            return

        self._set_mode(_MODE_BASE)
        self._parsec_edit_entry_key = None
        self._parsec_model = None
        self._parsec_preview_airfoil = None
        self._parsec_preview_controlpoints = None
        self.parsec_status.setText("")
        self._update_buttons()

    def _start_parsec_edit(self, entry: AirfoilEntry) -> None:
        if entry.airfoil.parsec_data is None:
            return

        self._parsec_edit_entry_key = entry.key
        self._parsec_model = copy.deepcopy(entry.airfoil.parsec_data)
        self.parsec_numpoints.setValue(int(entry.airfoil.parsec_data.numpoints))
        self.parsec_result_name.setText(f"{entry.name}_edited")

        for key, value in self._parsec_model.get_parameters().items():
            spinbox = self._parsec_spinboxes.get(key)
            if spinbox is None:
                continue
            spinbox.blockSignals(True)
            spinbox.setValue(value * self._parsec_factors[key])
            spinbox.blockSignals(False)

        self.parsec_trailing_angle.blockSignals(True)
        self.parsec_trailing_angle.setValue(
            math.degrees(self._parsec_model.trailing_edge_angle)
        )
        self.parsec_trailing_angle.blockSignals(False)

        self.parsec_trailing_percentage.blockSignals(True)
        self.parsec_trailing_percentage.setValue(
            self._parsec_model.trailing_edge_factor * 100
        )
        self.parsec_trailing_percentage.blockSignals(False)

        self._set_parsec_edit_active(True)
        self._update_parsec_preview()

    def _cancel_parsec_edit(self) -> None:
        self._set_parsec_edit_active(False)
        self.draw()

    def _parsec_parameter_changed(self, key: str, value: float) -> None:
        if self._parsec_model is None:
            return

        self._set_parsec_parameter(key, value)

    def _parsec_shared_trailing_changed(self, *args: object) -> None:
        if self._parsec_model is None:
            return

        angle_value = self.parsec_trailing_angle.value()
        percentage_value = self.parsec_trailing_percentage.value()

        self._parsec_model.trailing_edge_angle = math.radians(angle_value)
        self._parsec_model.trailing_edge_factor = percentage_value / 100

        self._update_parsec_preview()

    def _set_parsec_parameter(self, key: str, value: float, refresh: bool=True) -> None:
        if self._parsec_model is None:
            return

        factor = self._parsec_factors.get(key)
        if factor is None:
            raise ValueError(f"no parsec factor for key '{key}'")

        internal_value = value / factor
        if key in ("trailing_edge_angle", "trailing_edge_factor"):
            self._parsec_model = replace(self._parsec_model, **{key: internal_value})
        else:
            side, name = key.split("_", 1)
            surface = replace(getattr(self._parsec_model, side), **{name: internal_value})
            self._parsec_model = replace(self._parsec_model, **{side: surface})

        spinbox = self._parsec_spinboxes.get(key)
        if spinbox is not None:
            spinbox.blockSignals(True)
            spinbox.setValue(value)
            spinbox.blockSignals(False)

        if refresh:
            self._update_parsec_preview()

    def _update_parsec_preview(self, *args: object) -> None:
        if self._parsec_model is None:
            return

        try:
            self._parsec_preview_airfoil = self._parsec_model.get_airfoil(self.parsec_numpoints.value(), "preview")
            self._parsec_preview_controlpoints = self._collect_parsec_controlpoints(self._parsec_model)
            self.parsec_status.setText("")
        except Exception as e:
            self._parsec_preview_airfoil = None
            self._parsec_preview_controlpoints = None
            self.parsec_status.setText(f"Invalid parameters: {e}")

        self.draw()

    def _add_parsec_edited_airfoil(self) -> None:
        if self._parsec_model is None:
            return

        result_name = self.parsec_result_name.text().strip() or "parsec_edited"
        try:
            airfoil = self._parsec_model.get_airfoil(self.parsec_numpoints.value(), result_name)
        except Exception as e:
            self.parsec_status.setText(f"Invalid parameters: {e}")
            return

        self._attach_parsec_metadata(airfoil, self._parsec_model, self.parsec_numpoints.value())
        added_name = self.add_airfoil(result_name, airfoil)
        self._set_parsec_edit_active(False)
        self._select_entry_by_key(f"separate:{added_name}")
        self.draw()

    def load_files(self, filenames: list[str]) -> None:
        for filename in filenames:
            try:
                airfoil = Profile2D.import_from_dat(filename)
                name = airfoil.name or os.path.basename(filename)
                normalized = airfoil.normalized(close=False)
            except Exception as e:
                logger.error(f"could not load airfoil {filename}: {e}")
                continue

            self.add_airfoil(name, normalized)

    def load_dialog(self) -> None:
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "load airfoils",
            os.path.expanduser("~"),
            filter="Airfoil (*.dat *.txt);;All files (*)"
        )

        if filenames:
            self.load_files(filenames)

    def remove_current(self) -> None:
        entry = self.get_current()
        if entry is None or not entry.separate:
            return

        self.app.state.airfoils.pop(entry.name, None)
        self._checked.pop(entry.key, None)
        self.refresh()

    def export_current(self) -> None:
        entry = self.get_current()
        if entry is None:
            return

        filename, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            f"Export {entry.name}",
            f"{entry.airfoil.name or 'airfoil'}.dat",
            filter="Airfoil (*.dat)"
        )

        if filename:
            if not filename.endswith(".dat"):
                filename += ".dat"
            entry.airfoil.export_dat(filename)

    def open_parsec_wizard(self) -> None:
        from openglider.gui.wizzards.parsec import fit_parsec_popup

        entry = self.get_current()
        if entry is None:
            entries = self.get_entries()
            entry = entries[0] if entries else None

        if entry is None:
            fit_parsec_popup(self.app)
            return

        fit_parsec_popup(self.app, entry.airfoil, entry.name)

    def fit_current(self) -> None:
        self.open_parsec_wizard()

    def edit_current_parsec(self) -> None:
        entry = self.get_current()
        if entry is None or entry.airfoil.parsec_data is None:
            return

        self._start_parsec_edit(entry)

    def open_apply_to_glider_dialog(self) -> None:
        dialog = ApplyAirfoilsDialog(self.app, list(self.entries.values()), self)
        dialog.exec()
