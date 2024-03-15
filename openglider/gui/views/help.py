from typing import Any
from openglider.gui.qt import QtWidgets, QClipboard

from openglider.gui.widgets.select import AutoComplete
from openglider.glider.parametric.table import GliderTables
from openglider.glider.parametric.table.base.table import ElementTable
from openglider.glider.parametric.table.base.dto import DTO

class HelpView(QtWidgets.QWidget):
    all_dtos: dict[str, type[DTO]]

    def __init__(self, parent: QtWidgets.QWidget | None=None) -> None:
        super().__init__(parent)

        self.all_dtos = {}
        self.dto_names = {}

        for table_name, _cls in GliderTables.__annotations__.items():
            if issubclass(_cls, ElementTable):
                table_type = _cls.table_type.name

                for dto_name, dto in _cls.dtos.items():
                    self.all_dtos[f"{table_type} -> {table_name} -> {dto_name}"] = dto
                    self.dto_names[dto] = dto_name

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        dto_names = list(self.all_dtos.keys())
        dto_names.sort()
        self.search = AutoComplete(dto_names)
        layout.addWidget(self.search)
        self.search.changed.connect(self.select)

        self.copy_header_button = QtWidgets.QPushButton(text="Copy Header")
        layout.addWidget(self.copy_header_button)
        self.copy_header_button.clicked.connect(self.copy_header)

        self.content = QtWidgets.QTextEdit()
        self.content.setReadOnly(True)
        layout.addWidget(self.content)

        self.select()

    def get_selected(self) -> type[DTO]:
        dto_name = self.search.selected
        if dto_name not in self.all_dtos:
            raise ValueError

        dto = self.all_dtos[dto_name]
        return dto


    def copy_header(self) -> None:
        dto = self.get_selected()
        #add contents of table to clipboard.
        text = f"{self.dto_names[dto]}\n"

        annotations = [
            f"{name}: {annotation}"
            for name, annotation in
            dto.describe()
        ]
        
        text += "\t".join(annotations)

        clipboard = QClipboard()
        clipboard.setText(text)

    def select(self, *args: Any, **kwargs: Any) -> None:
        dto = self.get_selected()

        annotations = dto.describe()

        text = f"{dto.__name__}\n"
        for name, annotation in annotations:
            text += f"    - {name}: {annotation}\n"

        if dto.__doc__:
            text += dto.__doc__

        self.content.setText(text)
