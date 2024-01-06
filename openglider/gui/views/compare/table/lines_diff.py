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


class LinesTableCache(GliderCache[Table]):
    update_on_reference_change = True

    def get_index(self, project: GliderProject) -> Table:
        table = Table()
        table[0,0] = "Name"
        attachment_points = project.get_glider_3d().lineset.get_attachment_points_sorted()
        for i, p in enumerate(attachment_points):
            table[i+1, 0] = p.name
        
        return table


    def get_object(self, name: str) -> Table:
        table = Table()
        table[0,0] = name

        project = self.elements[name].element.get_glider_3d()
        is_reference = self.elements.selected_element == name
        reference = self.elements.get_selected()

        if reference is None:
            return table
        
        reference_glider = reference.get_glider_3d()
        reference_attachment_points = reference_glider.lineset.get_attachment_points_sorted()
        attachment_points = {p.name: p for p in project.lineset.attachment_points}
        
        for i, p in enumerate(reference_attachment_points):
            if p.name in attachment_points:
                checklength = 1000*project.lineset.get_checklength(attachment_points[p.name])

                if is_reference:
                    table[i+1, 0] = f"{checklength:.0f}"
                else:
                    difference = checklength - 1000*reference_glider.lineset.get_checklength(p)
                    table[i+1, 0] = f"{checklength:.0f} ({difference:.0f})"

        if is_reference:
            index = self.get_index(reference)
            index.append_right(table)
            return index
        
        return table


class GliderLineSetTable(QTable, CompareView):
    row_indices: list[str] = [

    ]
    def __init__(self, app: GliderApp, parent: QtWidgets.QWidget=None):
        ##ToDO: make cleaner implementation of the button

        super().__init__(parent)

        self.setLayout(QtWidgets.QHBoxLayout())

        self.main_widget = QtWidgets.QSplitter()
        self.main_widget.setOrientation(QtCore.Qt.Orientation.Vertical)

        self.splitter = QtWidgets.QSplitter()
        self.splitter.setOrientation(QtCore.Qt.Orientation.Horizontal)

        self.setLayout(QtWidgets.QHBoxLayout())
        self.layout().addWidget(self.splitter)

        self.right_widget = QtWidgets.QWidget()
        self.right_widget.setLayout(QtWidgets.QVBoxLayout())

        self.main_widget = QtWidgets.QWidget()
        self.main_widget.setLayout(QtWidgets.QVBoxLayout())

        self.button_copy = QtWidgets.QPushButton("Copy Table")
        self.button_copy.clicked.connect(self.copy)

        self.right_widget.layout().addWidget(self.button_copy)

        self.splitter.addWidget(self.main_widget)
        self.splitter.addWidget(self.right_widget)
        self.splitter.setSizes([800, 200])

        self.cache = LinesTableCache(app.state.projects)


    def update_view(self) -> None:
        self.table = Table()

        for i, active_project_table in enumerate(self.cache.get_update().active):
            self.table.append_right(active_project_table)
        
        self.clear()
        self.push_table(self.table)
        self.resizeColumnsToContents()


    def copy(self) -> None:
        #add contents of table to clipboard.
        copied = ''
        for row in range(0, self.table.num_rows):
            for col in range(0, self.table.num_columns):
                copied += self.item(row, col).text() + '\t'
            copied = copied[:-1] + '\n'

        clipboard = QClipboard()
        clipboard.setText(copied)
