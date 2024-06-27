import logging
from openglider.glider.project import GliderProject
from openglider.gui.qt import QtCore, QtWidgets
from openglider.gui.qt import QClipboard

from openglider.gui.app.app import GliderApp
from openglider.utils.table import Table
from openglider.gui.widgets.table import QTable
from openglider.gui.state.glider_list import GliderCache
from openglider.gui.views.compare.base import CompareView



logger = logging.getLogger(__name__)


class StrapsTableCache(GliderCache[Table]):
    update_on_reference_change = True

    def get_object(self, name: str) -> Table:
        
        table = Table(name="straps")
        table[0,0] = name
        project = self.elements.get_selected()
        row = 1
        column = 0

        for cell in project.get_glider_3d().cells:
            for strap in sorted(cell.straps, key=lambda strap: abs(strap.get_average_x())):
                table[row, column] = strap.name
                table[row, column+1] = f"{strap.get_center_length(cell)*1000:.0f}"
                column +=2
            row += 1
            column = 0

        
        return table



class GliderStrapTable(QtWidgets.QWidget, CompareView):
    row_indices: list[str] = [

    ]
    def __init__(self, app: GliderApp, parent: QtWidgets.QWidget=None):

        super().__init__(parent)

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)
        self.table_widget = QTable()
        layout.addWidget(self.table_widget)
        button_copy = QtWidgets.QPushButton("Copy Table")
        layout.addWidget(button_copy)
        button_copy.clicked.connect(self.copy_to_clipboard)


        self.cache = StrapsTableCache(app.state.projects)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

    def update_view(self) -> None:
        self.table = Table()

        for i, active_project_table in enumerate(self.cache.get_update().active):
            self.table.append_right(active_project_table)

        self.table_widget.clear()
        self.table_widget.push_table(self.table)
        self.table_widget.resizeColumnsToContents()


    def copy_to_clipboard(self) -> None:
        #add contents of table to clipboard.
        copied = ''
        for row in range(0, self.table.num_rows):
            for col in range(0, self.table.num_columns):
                copied += self.table_widget.item(row, col).text() + '\t'
            copied = copied[:-1] + '\n'

        clipboard = QClipboard()
        clipboard.setText(copied)

