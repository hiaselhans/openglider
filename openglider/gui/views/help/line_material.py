from __future__ import annotations

from collections.abc import Callable
import logging

import openglider.lines.line_types  # ensure all line types are registered
from openglider.lines.line_types.linetype import LineType, registry
from openglider.utils.colors import Color
from openglider.gui.qt import QtWidgets, QtCore

logger = logging.getLogger(__name__)


def _make_copy_handler(text: str) -> Callable[[bool], None]:
    def handler(checked: bool = False) -> None:
        QtWidgets.QApplication.clipboard().setText(text)
    return handler


class LineTypeRow(QtWidgets.QWidget):
    def __init__(
        self,
        copy_text: str,
        color: Color | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 2, 0, 2)
        self.setLayout(layout)

        swatch = QtWidgets.QLabel()
        swatch.setFixedSize(20, 20)
        if color is not None:
            swatch.setStyleSheet(
                f"background-color: rgb({color.r},{color.g},{color.b}); border: 1px solid #888;"
            )
        else:
            swatch.setStyleSheet("border: 1px solid #888;")

        name_label = QtWidgets.QLabel(copy_text)

        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.setFixedWidth(60)
        copy_btn.clicked.connect(_make_copy_handler(copy_text))

        layout.addWidget(swatch)
        layout.addWidget(copy_btn)
        layout.addWidget(name_label)
        layout.addStretch()


class LineMaterialView(QtWidgets.QWidget):
    # list of (row_widget, searchable_text, parent_group_box)
    _rows: list[tuple[QtWidgets.QWidget, str, QtWidgets.QGroupBox]]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows = []

        outer_layout = QtWidgets.QVBoxLayout()
        self.setLayout(outer_layout)

        self._filter_input = QtWidgets.QLineEdit()
        self._filter_input.setPlaceholderText("Filter line types…")
        self._filter_input.setClearButtonEnabled(True)
        self._filter_input.textChanged.connect(self._apply_filter)
        outer_layout.addWidget(self._filter_input)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        outer_layout.addWidget(scroll)

        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        content.setLayout(content_layout)
        scroll.setWidget(content)

        # Group by manufacturer prefix (part before first ".")
        groups: dict[str, list[LineType]] = {}
        for line_type in registry.values():
            manufacturer = line_type.name.split(".")[0] if "." in line_type.name else "other"
            groups.setdefault(manufacturer, []).append(line_type)

        for manufacturer, line_types in sorted(groups.items()):
            group_box = QtWidgets.QGroupBox(manufacturer)
            group_layout = QtWidgets.QVBoxLayout()
            group_box.setLayout(group_layout)

            for line_type in sorted(line_types, key=lambda lt: lt.name):
                if line_type.colors:
                    for color_name, color in line_type.colors.items():
                        copy_text = f"{line_type.name}:{color_name}"
                        row = LineTypeRow(copy_text, color, group_box)
                        group_layout.addWidget(row)
                        self._rows.append((row, copy_text.lower(), group_box))
                else:
                    row = LineTypeRow(line_type.name, None, group_box)
                    group_layout.addWidget(row)
                    self._rows.append((row, line_type.name.lower(), group_box))

            content_layout.addWidget(group_box)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        visible_groups: set[QtWidgets.QGroupBox] = set()

        for row, search_text, group_box in self._rows:
            visible = not needle or needle in search_text
            row.setVisible(visible)
            if visible:
                visible_groups.add(group_box)

        for _, _, group_box in self._rows:
            group_box.setVisible(group_box in visible_groups)
