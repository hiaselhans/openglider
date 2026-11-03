from __future__ import annotations

import logging
import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from openglider.airfoil.generators.parsec import ParsecAirfoil
from openglider.airfoil.profile_2d import Profile2D
from openglider.gui.qt import QtCore, QtGui, QtWidgets

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)


@dataclass
class ParameterSpec:
    name: str
    label: str
    minimum: float
    maximum: float
    step: float
    decimals: int = 3
    factor: float = 1.


DEGREES = math.degrees(1)

SURFACE_PARAMETERS = [
    ParameterSpec("x_max", "x max", 0.05, 0.8, 0.01),
    ParameterSpec("y_max", "y max", -0.05, 0.4, 0.005),
    ParameterSpec("nose_radius", "Nose radius", 0.001, 0.3, 0.002),
    ParameterSpec("front_percentage", "Front percentage [% of y max]", -1, 1, 5, 1, 100),
    ParameterSpec("top_radius", "Top radius", 0.005, 0.5, 0.01),
    ParameterSpec("rear_factor", "Rear 1 percentage [% of y max]", -1, 1, 5, 1, 100),
    ParameterSpec("trailing_edge_angle", "Trailing edge angle [deg]", -1.4, 1.4, 1, 2, DEGREES),
    ParameterSpec("trailing_edge_factor", "Trailing edge percentage [% of y max]", -1, 1, 5, 1, 100),
]

@dataclass
class FitOptions:
    num_samples: int = 200
    "number of points the source airfoil is sampled at (dense at the nose)"
    effort: int = 3
    "effort of the global search"


EFFORTS = {
    "Fast": 1,
    "Normal": 3,
    "Thorough": 8
}


class ParsecFitDialog(QtWidgets.QDialog):
    """Compact popup to fit an airfoil with a PARSEC model"""

    def __init__(
        self,
        app: MainWindow,
        source: Profile2D | None=None,
        name: str="",
        options: FitOptions | None=None,
        numpoints: int=80
    ) -> None:
        super().__init__(app)
        self.app = app
        self.fit_options = options or FitOptions()
        self.setWindowTitle("PARSEC fit")
        self.setModal(True)

        form = QtWidgets.QFormLayout()

        self.source_airfoils: list[Profile2D] = []
        self.source_selector = QtWidgets.QComboBox()
        for entry in self.app.airfoil_view.get_entries():
            self.source_selector.addItem(f"{entry.source}: {entry.name}")
            self.source_airfoils.append(entry.airfoil)
            if source is not None and entry.airfoil is source:
                self.source_selector.setCurrentIndex(len(self.source_airfoils) - 1)
        form.addRow("Source airfoil", self.source_selector)

        self.num_samples = QtWidgets.QSpinBox()
        self.num_samples.setRange(40, 2000)
        self.num_samples.setSingleStep(20)
        self.num_samples.setValue(self.fit_options.num_samples)
        self.num_samples.setToolTip("Number of points the source airfoil is sampled at for the fit")
        form.addRow("Fit samples", self.num_samples)

        self.effort = QtWidgets.QComboBox()
        for name, value in EFFORTS.items():
            self.effort.addItem(f"{name} ({value})", value)
        index = self.effort.findData(self.fit_options.effort)
        self.effort.setCurrentIndex(index if index >= 0 else 1)
        self.effort.setToolTip("Effort of the global parameter search. Higher is slower")
        form.addRow("Search effort", self.effort)

        self.numpoints = QtWidgets.QSpinBox()
        self.numpoints.setRange(10, 300)
        self.numpoints.setValue(numpoints)
        self.numpoints.setToolTip("Number of points of the resulting airfoil")
        form.addRow("Result points", self.numpoints)

        base_name = name or (source.name if source is not None else "airfoil")
        self.result_name = QtWidgets.QLineEdit(f"{base_name}_parsec")
        form.addRow("Name", self.result_name)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        form.addRow("", self.status_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Fit and add")
        buttons.accepted.connect(self._fit_and_add)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _selected_source(self) -> Profile2D | None:
        index = self.source_selector.currentIndex()
        if 0 <= index < len(self.source_airfoils):
            return self.source_airfoils[index]

        return None


    def _fit_and_add(self) -> None:
        source = self._selected_source()
        if source is None:
            self.status_label.setText("No source airfoil selected")
            return

        self.fit_options = FitOptions(
            num_samples=self.num_samples.value(),
            effort=int(self.effort.currentData())
        )

        QtWidgets.QApplication.setOverrideCursor(QtGui.QCursor(QtCore.Qt.CursorShape.WaitCursor))
        try:
            result = ParsecAirfoil.fit(
                source,
                num_samples=self.fit_options.num_samples,
                effort=self.fit_options.effort
            )
        except Exception as e:
            logger.exception("parsec fit failed")
            self.status_label.setText(f"Fit failed: {e}")
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        result_name = self.result_name.text().strip() or "parsec"
        airfoil = result.airfoil.get_airfoil(self.numpoints.value(), name=result_name)
        self._attach_parsec_metadata(airfoil, result.airfoil, self.numpoints.value())

        added_name = self.app.airfoil_view.add_airfoil(result_name, airfoil)
        logger.info(f"added airfoil {added_name}")

        self.status_label.setText(
            f"Added '{added_name}'\n"
            f"rms error: {result.rms_error * 100:.3f}%  max error: {result.max_error * 100:.3f}%"
        )

        self.accept()

    def _collect_controlpoints(self, model: ParsecAirfoil) -> list[list[tuple[float, float]]]:
        controlpoints: list[list[tuple[float, float]]] = []
        for curve in model.get_curves().values():
            controlpoints.append([(float(p[0]), float(p[1])) for p in curve.controlpoints.nodes])

        return controlpoints

    def _attach_parsec_metadata(self, airfoil: Profile2D, model: ParsecAirfoil, numpoints: int) -> None:
        setattr(airfoil, "_parsec_controlpoints", self._collect_controlpoints(model))
        setattr(airfoil, "_parsec_model", model)
        setattr(airfoil, "_parsec_numpoints", int(numpoints))


class ParsecParameterDialog(QtWidgets.QDialog):
    """Parameter editor for existing PARSEC-generated airfoils"""

    def __init__(self, app: MainWindow, source_airfoil: Profile2D, name: str="") -> None:
        super().__init__(app)
        self.app = app
        self.model = getattr(source_airfoil, "_parsec_model", None)
        if self.model is None:
            self.model = ParsecAirfoil.fit(source_airfoil).airfoil

        self.specs: dict[str, ParameterSpec] = {}
        self.spinboxes: dict[str, QtWidgets.QDoubleSpinBox] = {}
        self.numpoints = QtWidgets.QSpinBox()

        self.setWindowTitle("Edit PARSEC parameters")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout()

        for side in ("upper", "lower"):
            box = QtWidgets.QGroupBox(side.capitalize())
            form = QtWidgets.QFormLayout()
            box.setLayout(form)
            for spec in SURFACE_PARAMETERS:
                key = f"{side}_{spec.name}"
                spinbox = QtWidgets.QDoubleSpinBox()
                spinbox.setDecimals(spec.decimals)
                spinbox.setRange(spec.minimum * spec.factor, spec.maximum * spec.factor)
                spinbox.setSingleStep(spec.step)
                spinbox.valueChanged.connect(
                    lambda value, key=key: self._parameter_changed(key, value)  # type: ignore[misc]
                )
                form.addRow(spec.label, spinbox)
                self.spinboxes[key] = spinbox
                self.specs[key] = spec
            layout.addWidget(box)

        details_form = QtWidgets.QFormLayout()
        self.numpoints.setRange(10, 300)
        self.numpoints.setValue(int(getattr(source_airfoil, "_parsec_numpoints", source_airfoil.numpoints)))
        details_form.addRow("Result points", self.numpoints)

        base_name = name or source_airfoil.name or "parsec"
        self.result_name = QtWidgets.QLineEdit(f"{base_name}_edited")
        details_form.addRow("Name", self.result_name)

        layout.addLayout(details_form)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Ok).setText("Add edited airfoil")
        buttons.accepted.connect(self._add_edited_airfoil)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)
        self._set_model(self.model)

    def _to_display(self, key: str, value: float) -> float:
        return value * self.specs[key].factor

    def _from_display(self, key: str, value: float) -> float:
        return value / self.specs[key].factor

    def _set_model(self, model: ParsecAirfoil) -> None:
        self.model = model
        for name, value in self.model.get_parameters().items():
            spinbox = self.spinboxes[name]
            spinbox.blockSignals(True)
            spinbox.setValue(self._to_display(name, value))
            spinbox.blockSignals(False)

    def _parameter_changed(self, key: str, value: float) -> None:
        side, name = key.split("_", 1)
        surface = replace(getattr(self.model, side), **{name: self._from_display(key, value)})
        self.model = replace(self.model, **{side: surface})

    def _collect_controlpoints(self, model: ParsecAirfoil) -> list[list[tuple[float, float]]]:
        controlpoints: list[list[tuple[float, float]]] = []
        for curve in model.get_curves().values():
            controlpoints.append([(float(p[0]), float(p[1])) for p in curve.controlpoints.nodes])

        return controlpoints

    def _attach_parsec_metadata(self, airfoil: Profile2D, model: ParsecAirfoil, numpoints: int) -> None:
        setattr(airfoil, "_parsec_controlpoints", self._collect_controlpoints(model))
        setattr(airfoil, "_parsec_model", model)
        setattr(airfoil, "_parsec_numpoints", int(numpoints))

    def _add_edited_airfoil(self) -> None:
        try:
            result_name = self.result_name.text().strip() or "parsec_edited"
            airfoil = self.model.get_airfoil(self.numpoints.value(), name=result_name)
        except Exception as e:
            logger.warning(f"invalid parsec parameters: {e}")
            self.status_label.setText(f"Invalid parameters: {e}")
            return

        self._attach_parsec_metadata(airfoil, self.model, self.numpoints.value())
        added_name = self.app.airfoil_view.add_airfoil(result_name, airfoil)
        self.status_label.setText(f"Added '{added_name}' to airfoil list")
        self.accept()


def fit_parsec_popup(app: MainWindow, source: Profile2D | None=None, name: str="") -> None:
    dialog = ParsecFitDialog(app, source=source, name=name)
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        index = app.top_panel.indexOf(app.airfoil_view)
        if index >= 0:
            app.top_panel.setCurrentIndex(index)


def edit_parsec_popup(app: MainWindow, source: Profile2D, name: str="") -> None:
    dialog = ParsecParameterDialog(app, source, name=name)
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        index = app.top_panel.indexOf(app.airfoil_view)
        if index >= 0:
            app.top_panel.setCurrentIndex(index)
