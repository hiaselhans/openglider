from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pyqtgraph

from openglider.airfoil.generators.parsec import ParsecAirfoil
from openglider.airfoil.profile_2d import Profile2D
from openglider.gui.qt import QtCore, QtWidgets
from openglider.gui.views.window import Window
from openglider.utils.colors import colorwheel

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)

SEPARATE_AIRFOILS = "Separate airfoils"
_KEY_ROLE = QtCore.Qt.ItemDataRole.UserRole

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
        self._parsec_trailing_angle_factor = _PARSEC_DEGREES
        self._parsec_trailing_percentage_factor = 100.0

        self.setLayout(QtWidgets.QHBoxLayout())
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.layout().addWidget(splitter)  # type: ignore[union-attr]

        # left: list + buttons
        left = QtWidgets.QWidget()
        left.setLayout(QtWidgets.QVBoxLayout())
        self.left_stack = QtWidgets.QStackedWidget()
        left.layout().addWidget(self.left_stack)  # type: ignore[union-attr]

        self.list_page = QtWidgets.QWidget()
        self.list_page.setLayout(QtWidgets.QVBoxLayout())
        self.left_stack.addWidget(self.list_page)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self.draw)
        self.tree.currentItemChanged.connect(self._current_changed)
        self.list_page.layout().addWidget(self.tree)  # type: ignore[union-attr]

        self.info = QtWidgets.QLabel()
        self.info.setWordWrap(True)
        self.list_page.layout().addWidget(self.info)  # type: ignore[union-attr]

        self.button_load = QtWidgets.QPushButton("Load airfoil (.dat)")
        self.button_load.clicked.connect(self.load_dialog)
        self.button_remove = QtWidgets.QPushButton("Remove")
        self.button_remove.clicked.connect(self.remove_current)
        self.button_export = QtWidgets.QPushButton("Export (.dat)")
        self.button_export.clicked.connect(self.export_current)
        self.button_fit = QtWidgets.QPushButton("Fit PARSEC...")
        self.button_fit.clicked.connect(self.fit_current)
        self.button_edit_parsec = QtWidgets.QPushButton("Edit PARSEC...")
        self.button_edit_parsec.clicked.connect(self.edit_current_parsec)

        for button in (
            self.button_load,
            self.button_remove,
            self.button_export,
            self.button_fit,
            self.button_edit_parsec
        ):
            self.list_page.layout().addWidget(button)  # type: ignore[union-attr]

        self.list_page.layout().addStretch()  # type: ignore[union-attr]

        self.parsec_page = QtWidgets.QWidget()
        self.parsec_page.setLayout(QtWidgets.QVBoxLayout())
        self.left_stack.addWidget(self.parsec_page)

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
        self.parsec_trailing_angle.setRange(-1.4 * _PARSEC_DEGREES, 1.4 * _PARSEC_DEGREES)
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
        self.button_parsec_cancel = QtWidgets.QPushButton("Back to list")
        self.button_parsec_cancel.clicked.connect(self._cancel_parsec_edit)
        self.parsec_page.layout().addWidget(self.button_parsec_add)  # type: ignore[union-attr]
        self.parsec_page.layout().addWidget(self.button_parsec_cancel)  # type: ignore[union-attr]
        self.parsec_page.layout().addStretch()  # type: ignore[union-attr]

        self.left_stack.setCurrentWidget(self.list_page)

        # right: plot
        self.plot = pyqtgraph.PlotWidget()
        self.plot.setAspectLocked(True)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.legend = self.plot.addLegend()

        splitter.addWidget(left)
        splitter.addWidget(self.plot)
        splitter.setSizes([300, 900])

        self.refresh()

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

    def _update_buttons(self) -> None:
        if self._parsec_edit_active:
            return

        entry = self.get_current()
        self.button_remove.setEnabled(entry is not None and entry.separate)
        self.button_export.setEnabled(entry is not None)
        self.button_fit.setEnabled(entry is not None)
        self.button_edit_parsec.setEnabled(
            entry is not None and hasattr(entry.airfoil, "_parsec_model")
        )

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

            parsec_controlpoints = getattr(entry.airfoil, "_parsec_controlpoints", None)
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
        setattr(airfoil, "_parsec_controlpoints", self._collect_parsec_controlpoints(model))
        setattr(airfoil, "_parsec_model", model)
        setattr(airfoil, "_parsec_numpoints", int(numpoints))

    def _set_parsec_edit_active(self, active: bool) -> None:
        self._parsec_edit_active = active
        if active:
            self.left_stack.setCurrentWidget(self.parsec_page)
            return

        self.left_stack.setCurrentWidget(self.list_page)
        self._parsec_edit_entry_key = None
        self._parsec_model = None
        self._parsec_preview_airfoil = None
        self._parsec_preview_controlpoints = None
        self.parsec_status.setText("")
        self._update_buttons()

    def _start_parsec_edit(self, entry: AirfoilEntry) -> None:
        model = getattr(entry.airfoil, "_parsec_model", None)
        if model is None:
            return

        self._parsec_edit_entry_key = entry.key
        self._parsec_model = model
        self.parsec_numpoints.setValue(int(getattr(entry.airfoil, "_parsec_numpoints", entry.airfoil.numpoints)))
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
            self._parsec_model.upper.trailing_edge_angle * self._parsec_trailing_angle_factor
        )
        self.parsec_trailing_angle.blockSignals(False)

        self.parsec_trailing_percentage.blockSignals(True)
        self.parsec_trailing_percentage.setValue(
            self._parsec_model.upper.trailing_edge_factor * self._parsec_trailing_percentage_factor
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

        self._set_parsec_parameter("upper_trailing_edge_angle", angle_value, refresh=False)
        self._set_parsec_parameter("lower_trailing_edge_angle", -angle_value, refresh=False)
        self._set_parsec_parameter("upper_trailing_edge_factor", percentage_value, refresh=False)
        self._set_parsec_parameter("lower_trailing_edge_factor", percentage_value, refresh=False)
        self._update_parsec_preview()

    def _set_parsec_parameter(self, key: str, value: float, refresh: bool=True) -> None:
        if self._parsec_model is None:
            return

        side, name = key.split("_", 1)
        factor = self._parsec_factors.get(key)
        if factor is None:
            if name == "trailing_edge_angle":
                factor = self._parsec_trailing_angle_factor
            elif name == "trailing_edge_factor":
                factor = self._parsec_trailing_percentage_factor
            else:
                factor = 1.0

        internal_value = value / factor
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

    def fit_current(self) -> None:
        entry = self.get_current()
        if entry is None:
            return

        from openglider.gui.wizzards.parsec import fit_parsec_popup

        fit_parsec_popup(self.app, entry.airfoil, entry.name)

    def edit_current_parsec(self) -> None:
        entry = self.get_current()
        if entry is None or not hasattr(entry.airfoil, "_parsec_model"):
            return

        self._start_parsec_edit(entry)
