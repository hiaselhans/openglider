import logging
from typing import Any

from openglider.gui.qt import QtWidgets, QClipboard, QtCore

from openglider.gui.widgets.select import AutoComplete
from openglider.glider.parametric.table import GliderTables
from openglider.glider.parametric.table.base.table import ElementTable
from openglider.glider.parametric.table.base.dto import DTO

logger = logging.getLogger(__name__)

class DtoChooser(QtWidgets.QWidget):
    changed = QtCore.Signal()
    all_dtos: dict[str, ElementTable]

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)

        self.all_dtos = {
            f"{_cls.table_type.name} -> {table_name}": _cls
            for table_name, _cls in GliderTables.__annotations__.items()
            if issubclass(_cls, ElementTable)
        }
        table_names = list(self.all_dtos.keys())
        table_names.sort()

        self.table_chooser = AutoComplete(table_names)
        self.element_chooser = AutoComplete([])
        self.copy_header_button = QtWidgets.QPushButton(text="Copy Header")

        self.table_chooser.changed.connect(self.update_choices)
        self.element_chooser.changed.connect(self.changed.emit)
        self.copy_header_button.clicked.connect(self.copy_header)

        layout.addWidget(self.table_chooser)
        layout.addWidget(self.element_chooser)
        layout.addWidget(self.copy_header_button)

        self.update_choices()

    def update_choices(self) -> None:
        table_name = self.table_chooser.selected

        if table_name not in self.all_dtos:
            raise ValueError

        dto_names = list(self.all_dtos[table_name].dtos.keys())
        dto_names.sort()

        self.element_chooser.update_choices(dto_names)
        if len(dto_names):
            self.element_chooser.select(dto_names[0])
        
        self.changed.emit()

    def get_selected(self) -> type[DTO] | None:
        if not self.element_chooser.choices:
            return None
        dto_name = self.element_chooser.selected
        table_name = self.table_chooser.selected

        table = self.all_dtos.get(table_name, None)

        if table is None or dto_name not in table.dtos:
            return None

        dto = table.dtos[dto_name]

        return dto

    def copy_header(self) -> None:
        dto = self.get_selected()
        if dto is None:
            logger.warning("no element selected")
            return

        dto_name = self.element_chooser.selected
        #add contents of table to clipboard.
        text = f"{dto_name}\n"

        annotations = [
            f"{name}: {annotation}"
            for name, annotation in
            dto.describe()
        ]
        
        text += "\t".join(annotations)

        clipboard = QClipboard()
        clipboard.setText(text)
        logger.info(f"copied header for {dto_name}")


class HelpView(QtWidgets.QWidget):
    all_dtos: dict[str, type[DTO]]

    def __init__(self, parent: QtWidgets.QWidget | None=None) -> None:
        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.chooser = DtoChooser(self)
        self.content = QtWidgets.QTextEdit()
        self.content.setReadOnly(True)

        layout.addWidget(self.chooser)
        layout.addWidget(self.content)

        self.chooser.changed.connect(self.select)

        self.select()

    def select(self, *args: Any, **kwargs: Any) -> None:
        dto = self.chooser.get_selected()

        if dto is None:
            self.content.setText("")
            return

        annotations = dto.describe()

        text = f"{dto.__name__}\n"
        
        if dto.__doc__:
            text += f"{dto.__doc__}\n"

        text += "\n"
        for name, annotation in annotations:
            text += f"    - {name}: {annotation}\n"


        self.content.setText(text)
