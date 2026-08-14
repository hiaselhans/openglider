from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any
from collections.abc import Callable, Iterator

from openglider.glider.project import GliderProject
from openglider.gui.app.app import get_window_icon
from openglider.gui.qt import QtCore, QtWidgets, QtGui, QAction
from openglider.version import __version__
from openglider.gui.icons import icon
from openglider.gui.views.compare import GliderPreview
from openglider.gui.views.console import ConsoleHandler, ConsoleWidget, LogFilterPanel
from openglider.gui.views.glider_list import GliderListWidget
from openglider.gui.views.tasks import QTaskQueue
from openglider.gui.views.window import Window

from openglider.gui.views.help import HelpView

from openglider.gui.wizzards.base import Wizard


if TYPE_CHECKING:
    from openglider.gui.app.app import GliderApp

logger = logging.getLogger(__name__)


class Action():
    action: QAction | None
    
    def __init__(self, main_window: MainWindow, name: str, widget: type[Wizard]) -> None:
        self.name = name
        self.widget = widget
        self.main_window = main_window
        self.action = None

    def run(self) -> None:
        glider = self.main_window.state.projects.get_selected()
        if glider is None:
            return

        logger.info(f"open {self.name}({glider.name})")

        window = self.widget(self.main_window, glider)
        self.main_window.show_tab(window)

    def get_qt_action(self) -> QAction:
        if self.action is None:
            self.action = QAction(icon("fa.minus"), self.name, self.main_window)
            self.action.triggered.connect(self.run)
        
        return self.action


class MainWindow(QtWidgets.QMainWindow):
    # actions need to be saved in a dict (prevent garbage collection)
    action_store: dict[str, Action]
    glider_preview: GliderPreview
    task_queue: QTaskQueue
    overview: QtWidgets.QSplitter
    glider_list: GliderListWidget
    console: ConsoleWidget
    log_filter_panel: LogFilterPanel

    def __init__(self, app: GliderApp):
        super().__init__()
        self.setWindowTitle(f"OpenGlider v {__version__}")
        self.setWindowIcon(get_window_icon())
        
        self.app = app
        self.state = app.state

        self.action_store = {}

        self.main_widget = QtWidgets.QSplitter()
        self.main_widget.setOrientation(QtCore.Qt.Orientation.Vertical)
        

        self.top_panel = QtWidgets.QTabWidget(self.main_widget)
        self.main_widget.addWidget(self.top_panel)

        self.bottom_panel = QtWidgets.QWidget(self.main_widget)
        bottom_panel_layout = QtWidgets.QHBoxLayout()
        self.bottom_panel.setLayout(bottom_panel_layout)
        self.main_widget.addWidget(self.bottom_panel)

        self.main_widget.setSizes([800, 200])

        self.setCentralWidget(self.main_widget)


        

        self.menus: dict[str, QtWidgets.QMenu] = {}
        self.add_menu()


        #self.glider_list = ListWidget(self, self.state.projects)
        self.glider_list = GliderListWidget(self, self.state.projects)
        self.glider_list.changed.connect(self.current_glider_changed)

        #self.overview = QtWidgets.QWidget(self.main_widget)

        self.overview = QtWidgets.QSplitter(self.main_widget)
        self.overview.setOrientation(QtCore.Qt.Orientation.Horizontal)
        self.overview.addWidget(self.glider_list)

        self.glider_preview = GliderPreview(self.app)
        self.overview.addWidget(self.glider_preview)

        self.overview.setSizes([200, 800])
        self.top_panel.addTab(self.overview, "Main")

        #self.diff_view = DiffView(self, self.state)
        #self.top_panel.addTab(self.diff_view, "Diff")

        if self.app.task_queue is None:
            raise RuntimeError("application task queue is not initialized")
        self.task_queue = QTaskQueue(self, self.app.task_queue)
        self.top_panel.addTab(self.task_queue, "Tasks")

        self.help = HelpView()
        self.top_panel.addTab(self.help, "Help")

        self.log_filter_panel = LogFilterPanel(self.bottom_panel)
        bottom_panel_layout.addWidget(self.log_filter_panel, 0)

        self.console = ConsoleWidget(self)
        bottom_panel_layout.addWidget(self.console, 75)

        self.signal_handler = ConsoleHandler(self.console, self.log_filter_panel)
        self._is_shutting_down = False

        self.setAcceptDrops(True)
        self.current_glider_changed()

    def shutdown(self) -> None:
        if self._is_shutting_down:
            return

        self._is_shutting_down = True

        if self.glider_preview is not None:
            self.glider_preview.shutdown()

        if self.task_queue is not None:
            self.task_queue.shutdown()

    def add_menu(self) -> None:
        menubar: QtWidgets.QMenuBar = self.menuBar()
        self.menus = {
            "file": menubar.addMenu("&File")
        }
        self.menu_actions = self._get_actions()

        for menu_name in self.menu_actions:
            self.menus[menu_name] = menubar.addMenu(f"&{menu_name}")

        self.menus["debug"] = menubar.addMenu("&Debug")
        reload_action = QAction(icon("fa.minus"), "Reload", self)
        reload_action.triggered.connect(self.app.reload_code)
        self.menus["debug"].addAction(reload_action)

        toggle_console = QAction(icon("mdi6.file-document-outline"), "Toggle Console", self)
        toggle_console.setShortcut("del")  #QtGui.QKeySequence(QtCore.Qt.Key_AsciiCircum)
        #toggle_console.setStatusTip("Toggle Console")
        toggle_console.triggered.connect(self.toggle_console)
        menubar.addAction(toggle_console)

        load_glider = QAction(icon("fa.folder"), "Open", self)
        load_glider.setShortcut("Ctrl+O")
        load_glider.setStatusTip("Load Glider")
        load_glider.triggered.connect(self.open_dialog)

        load_demowing = QAction(icon("fa.folder"), "demowing", self)
        load_demowing.setShortcut("Ctrl+D")
        load_demowing.setStatusTip("Load demowing")
        load_demowing.triggered.connect(self.load_demowing)

        diff_gliders = QAction(icon("fa.folder"), "Diff gliders", self)
        diff_gliders.setStatusTip("Diff gliders")
        diff_gliders.triggered.connect(self.diff)

        self.menus["file"].addAction(load_glider)
        self.menus["file"].addAction(load_demowing)

        for menu_name, actions in self.menu_actions.items():
            for widget, name in actions:
                action = Action(self, name, widget)
                qt_action = action.get_qt_action()

                self.menus[menu_name].addAction(qt_action)
                self.action_store[name] = action

        self.menus["view"].addAction(diff_gliders)

    def diff(self) -> None:
        active_gliders = self.state.projects.get_active()
        if len(active_gliders) != 2:
            raise ValueError("Need ti have two gliders selected")
        
        g1, g2 = active_gliders
        tempdir = pathlib.Path(tempfile.gettempdir())
        tmpname1 = str(tempdir / f"{g1.name}.og.md")
        tmpname2 = str(tempdir / f"{g2.name}.og.md")
        
        g1.save(tmpname1, keep_filename=True)
        g2.save(tmpname2, keep_filename=True)

        subprocess.run([
            "code",
            "--diff",
            tmpname1,
            tmpname2
        ])

    def _get_actions(self) -> dict[str, list[tuple[type[Wizard], str]]]:
        from openglider.gui.app.actions import menu_actions
        return menu_actions

    def show_tab(self, window: Window) -> None:
        tab_index = self.top_panel.count()

        self.top_panel.addTab(window, window.name)
        self.top_panel.setCurrentIndex(tab_index)

        self.state.current_tab = window.name
        
        tabbar: QtWidgets.QTabBar = self.top_panel.tabBar()
        tabbar.setTabButton(tab_index, QtWidgets.QTabBar.ButtonPosition.RightSide, window.close_button)

        def close() -> None:
            # iterate through all closable tabs (i>=2)
            for i, tab in enumerate(self.get_opened_tabs()):
                if tab == window:
                    self.top_panel.removeTab(i+2)
                    self.top_panel.setCurrentIndex(0)
                    return
            
            # hasn't returned yet? raise!
            raise Exception(f"couldn't close tab: {window}")

        window.closed.connect(close)
    
    def toggle_console(self) -> None:
        if self.console.height() > 0:
            self.main_widget.setSizes([1000, 0])
        else:
            self.main_widget.setSizes([700, 300])

    def get_opened_tabs(self) -> Iterator[QtWidgets.QWidget]:
        for i in range(2, self.top_panel.count()):
            widget = self.top_panel.widget(i)
            if widget is not None:
                yield widget

    def update_menu(self) -> None:
        num_gliders = self.glider_list.count()

        for name, menu in self.menus.items():
            menu.setEnabled(num_gliders > 0)
    
    @property
    def loop(self) -> QtCore.QEventLoop:
        return self.app.loop

    async def execute(self, function: Callable[[Any], Any], *args: Any, **kwargs: Any) -> Any:
        logger.info(f"use main application to execute function: {function}")
        result = await self.app.execute(function, *args, **kwargs)
        return result
    
    def dragEnterEvent(self, e: QtGui.QDragMoveEvent) -> None:
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QtGui.QDropEvent) -> None:
        """
        Drag and Drop glider files
        """
        if e.mimeData().hasUrls():
            e.setDropAction(QtCore.Qt.DropAction.CopyAction)
            e.accept()
            fname = None
            # Workaround for OSx dragging and dropping
            for url in e.mimeData().urls():
                #if op_sys == 'Darwin':
                #    fname = str(NSURL.URLWithString_(str(url.toString())).filePathURL().path())
                fname = str(url.toLocalFile())
            
            if fname:
                suffix = pathlib.Path(fname).suffix.lower()
                if suffix == ".obj":
                    preview = self.glider_preview.view_3d
                    if preview is None:
                        raise RuntimeError("3D preview is not initialized")
                    preview.import_obj(fname)
                    self.top_panel.setCurrentIndex(0)
                    self.glider_preview.tabs_widget.setCurrentIndex(self.glider_preview.tab_names.index("3D"))
                else:
                    asyncio.ensure_future(self.load_glider(fname))
            #self.load_image()
        else:
            e.ignore()
    
    def process(self) -> None:
        self.app.processEvents()
    
    @property
    def glider_projects(self) -> list[GliderProject]:
        return self.state.projects.get_all()

    def current_glider_changed(self) -> None:
        # cleanup widgets
        self.glider_preview.update_current()
        #self.diff_view.update_view()

        active_wing = self.state.projects.get_selected()
            
        self.console.push_local_ns("active_wing", active_wing)


    def add_glider(self, glider: GliderProject, focus: bool=True, increase_revision: bool=False) -> None:
        logger.info(f"Adding glider {glider.name}")

        if increase_revision:
            need_to_increase = True

            while need_to_increase:
                glider.increase_revision_nr()
                need_to_increase = False
                for project in self.glider_projects:
                    if glider.name == project.name:
                        need_to_increase = True
            
            logger.info(f"new name: {glider.name}")
        
        self.state.add_glider_project(glider)
        self.state.projects.selected_element = glider.name
        self.glider_list.render()

        self.console.push_local_ns("wings", list(self.glider_projects))
        self.current_glider_changed()
        self.update_menu()
        self.top_panel.setCurrentIndex(0)

    def load_demowing(self) -> None:
        import openglider
        filename = openglider.get_demowing_path()
        asyncio.ensure_future(self.load_glider(filename))


    def open_dialog(self) -> None:
        home = os.path.expanduser("~")
        filename, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "load glider",
            home,
            filter="Openglider (*.ods *.json *.og.md)"
        )

        if filename:
            asyncio.ensure_future(self.load_glider(filename))


    async def load_glider(self, filename: str) -> None:
        project = await self.execute(self.glider_list.import_glider, filename)

        self.add_glider(project)
    
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """
        Ask to save unsaved gliders
        """
        should_quit = True
        unsaved_gliders = [
            p for p in self.state.projects.elements.values()
            if p.is_temporary or p.element.filename is None
        ]

        if len(unsaved_gliders):
            msgBox = QtWidgets.QMessageBox()
            
            msgBox.setText("Unsaved Gliders")
            msgBox.setWindowTitle("Discard Changes?")

            text = "\n".join(["   - "+p.name for p in unsaved_gliders])
            msgBox.setInformativeText(text)

            msgBox.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard)
            msgBox.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)
            ret = msgBox.exec_()

            if ret == QtWidgets.QMessageBox.StandardButton.Save:
                event.ignore()
                should_quit = False
                return
            else:
                event.accept()

        if self.task_queue is not None and self.task_queue.queue.is_busy():
            msgBox = QtWidgets.QMessageBox()
            
            msgBox.setText("Running Tasks")
            msgBox.setWindowTitle("Stop?")

            text = "\n".join(["   - "+p.name for p in unsaved_gliders])
            msgBox.setInformativeText(text)

            msgBox.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Save | QtWidgets.QMessageBox.StandardButton.Discard)
            msgBox.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Save)

            ret = msgBox.exec_()

            if ret == QtWidgets.QMessageBox.StandardButton.Save:
                event.ignore()
                should_quit = False
                return
            else:
                if self.task_queue is not None:
                    self.app.loop.run_until_complete(self.task_queue.queue.quit())
                event.accept()
        if should_quit and not self.app.reloading:
            self.shutdown()
            self.top_panel.blockSignals(True)
            self.top_panel.clear()
            self.top_panel.blockSignals(False)
            self.app.quit()
        
        
