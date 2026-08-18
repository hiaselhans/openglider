from __future__ import annotations

import logging

from openglider.utils.types import expect_value
from openglider.gui.qt import QtCore, QtWidgets
from openglider.utils.dataclass import BaseModel

logger = logging.getLogger(__name__)

class GliderViewConfig(BaseModel):
    show_panels: bool = True
    show_ribs: bool = True
    show_lines: bool = True
    line_riser: str | int = "all"

    show_diagonals: bool = True
    show_straps: bool = True

    show_miniribs: bool = True

    show_highres: bool = False

    profile_numpoints: int = 25
    numribs: int = 3
    line_numpoints: int = 3
    hole_numpoints: int = 10
    texture_precision: float = 0.35

    def needs_recalc(self, old_config: GliderViewConfig | None=None) -> bool:
        if old_config is None:
            return True
        
        if self.show_highres:
            self.numribs = 12
            self.profile_numpoints = 120
            self.line_numpoints = 12
            self.hole_numpoints = 30
            self.texture_precision = 0.9
        else:
            self.numribs = 3
            self.profile_numpoints = 25
            self.line_numpoints = 3
            self.hole_numpoints = 10
            self.texture_precision = 0.35
        
        if old_config.numribs != self.numribs:
            return True
        if old_config.profile_numpoints != self.profile_numpoints:
            return True
        
        return False
    
    def get_active_keys(self) -> list[str]:
        keys = []
        if self.show_panels:
            keys.append("panels")
        if self.show_ribs:
            keys.append("ribs")
        if self.show_lines:
            keys.append("lines")
        if self.show_diagonals:
            keys.append("diagonals")
        if self.show_straps:
            keys.append("straps")
        if self.show_miniribs:
            keys.append("miniribs")
        return keys


def get_riser_indices(lower_node_names: list[str], brake_name: str) -> tuple[list[int], int | None]:
    regular = [i for i, name in enumerate(lower_node_names) if name != brake_name]
    brake = next((i for i, name in enumerate(lower_node_names) if name == brake_name), None)
    return regular, brake


def get_riser_label(index: int) -> str:
    label = ""
    while index >= 0:
        index, letter = divmod(index, 26)
        label = chr(ord("A") + letter) + label
        index -= 1
    return label


def get_riser_options(regular_riser_count: int, has_brake: bool) -> list[tuple[str, str | int]]:
    options: list[tuple[str, str | int]] = [("All", "all")]
    options.extend((get_riser_label(i), i) for i in range(regular_riser_count))
    if has_brake:
        options.append(("Br", "brake"))
    return options


class GliderViewConfigWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()
    def __init__(self, parent: QtWidgets.QWidget, config: GliderViewConfig=None) -> None:
        super().__init__(parent)
        self.config = config or GliderViewConfig()
        self._line_riser_layout: tuple[int, bool] | None = None

        self.setLayout(QtWidgets.QHBoxLayout())

        self.add_button("panels")
        self.add_button("ribs")
        self.add_lines_controls()
        self.add_button("diagonals")
        self.add_button("straps")
        self.add_button("miniribs")
        self.add_button("highres")

    def add_button(self, name: str) -> None:
        checkbox = QtWidgets.QCheckBox(self)
        checkbox.setText(f"show {name}")

        def toggle() -> None:
            setattr(self.config, f"show_{name}", not getattr(self.config, f"show_{name}"))
            self.changed.emit()

        checkbox.setChecked(getattr(self.config, f"show_{name}"))
        checkbox.setText(f"show {name}")
        checkbox.clicked.connect(toggle)
        expect_value(self.layout()).addWidget(checkbox)

    def add_lines_controls(self) -> None:
        widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        checkbox = QtWidgets.QCheckBox(widget)
        checkbox.setText("show lines")
        checkbox.setChecked(self.config.show_lines)
        layout.addWidget(checkbox)

        self.line_riser_selector = QtWidgets.QComboBox(widget)
        self.line_riser_selector.setMaximumWidth(72)
        layout.addWidget(self.line_riser_selector)

        def toggle() -> None:
            self.config.show_lines = not self.config.show_lines
            self.line_riser_selector.setEnabled(self.config.show_lines)
            self.changed.emit()

        def select_riser(_index: int) -> None:
            riser = self.line_riser_selector.currentData()
            if isinstance(riser, (int, str)) and self.config.line_riser != riser:
                self.config.line_riser = riser
                self.changed.emit()

        checkbox.clicked.connect(toggle)
        self.line_riser_selector.currentIndexChanged.connect(select_riser)
        self.line_riser_selector.setEnabled(self.config.show_lines)
        self.update_line_riser_options(0, False)
        expect_value(self.layout()).addWidget(widget)

    def update_line_riser_options(self, regular_riser_count: int, has_brake: bool) -> bool:
        options = get_riser_options(regular_riser_count, has_brake)
        valid_values = {value for _label, value in options}
        changed = False
        if self.config.line_riser not in valid_values:
            self.config.line_riser = "all"
            changed = True

        layout_key = (regular_riser_count, has_brake)
        if layout_key != self._line_riser_layout:
            self.line_riser_selector.blockSignals(True)
            self.line_riser_selector.clear()
            for label, value in options:
                self.line_riser_selector.addItem(label, value)
            self.line_riser_selector.blockSignals(False)
            self._line_riser_layout = layout_key

        self.line_riser_selector.blockSignals(True)
        self.line_riser_selector.setCurrentIndex(
            max(0, self.line_riser_selector.findData(self.config.line_riser))
        )
        self.line_riser_selector.blockSignals(False)
        return changed
