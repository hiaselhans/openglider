import logging
import math
from pathlib import Path
from collections.abc import Callable

from openglider.utils.types import expect_value
from openglider.mesh import Mesh
import openglider.rs
from openglider.gui.app.app import GliderApp
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.state.glider_list import GliderCache
from openglider.gui.views.compare.base import CompareView
from openglider.gui.views.compare.glider_3d.actor import GliderActors
from openglider.gui.views.compare.glider_3d.config import \
    GliderViewConfigWidget, get_riser_indices
from openglider.gui.views_3d.widgets import View3D

logger = logging.getLogger(__name__)


class Glider3DCache(GliderCache[GliderActors]):
    update_on_color_change = False
    update_on_name_change = False
    
    def get_object(self, element: str) -> GliderActors:
        project = self.elements[element]
        return GliderActors(project.element)


class DropView3D(View3D):
    def __init__(self, parent: QtWidgets.QWidget, on_obj_drop: Callable[[str], None]) -> None:
        super().__init__(parent)
        self.on_obj_drop = on_obj_drop
        self.setAcceptDrops(True)
        self.frame.setAcceptDrops(True)
        self.render_window_interactor.setAcceptDrops(True)
        self.frame.installEventFilter(self)
        self.render_window_interactor.installEventFilter(self)


        # set defautl camera
        self.render_widget._interactor.camera.yaw = -math.pi * 3 / 4
        self.render_widget._interactor.camera.pitch = 0.3
        self.render_widget._interactor.camera.distance = 10.0


    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        event_type = event.type()
        if event_type == QtCore.QEvent.Type.DragEnter and isinstance(event, QtGui.QDragEnterEvent):
            if self._get_obj_path(event):
                event.acceptProposedAction()
                return True
            return False

        if event_type == QtCore.QEvent.Type.Drop and isinstance(event, QtGui.QDropEvent):
            filename = self._get_obj_path(event)
            if filename is None:
                return False

            event.setDropAction(QtCore.Qt.DropAction.CopyAction)
            event.accept()
            self.on_obj_drop(filename)
            return True

        return super().eventFilter(watched, event)

    @staticmethod
    def _get_obj_path(event: QtGui.QDropEvent | QtGui.QDragEnterEvent) -> str | None:
        if not event.mimeData().hasUrls():
            return None

        for url in event.mimeData().urls():
            filename = Path(url.toLocalFile())
            if filename.suffix.lower() == ".obj":
                return str(filename)

        return None

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        filename = self._get_obj_path(event)
        if filename is None:
            event.ignore()
            return

        event.setDropAction(QtCore.Qt.DropAction.CopyAction)
        event.accept()
        self.on_obj_drop(filename)


class Glider3DView(QtWidgets.QWidget, CompareView):
    def __init__(self, app: GliderApp):
        super().__init__()
        self.setLayout(QtWidgets.QVBoxLayout())
        self.app = app
        
        self.config = GliderViewConfigWidget(self)
        self.config.changed.connect(self.update_config)
        expect_value(self.layout()).addWidget(self.config)
        self.actor_cache = Glider3DCache(app.state.projects)

        self.imported_mesh_actor: "openglider.rs.wgpu.MeshActor | None" = None

        self.clear_obj_button = QtWidgets.QPushButton("Remove OBJ", self)
        self.clear_obj_button.setVisible(False)
        self.clear_obj_button.clicked.connect(self.clear_imported_obj)
        expect_value(self.layout()).addWidget(self.clear_obj_button)

        self.view_3d = DropView3D(self, self.import_obj)
        self.view_3d.show_axes = False
        self.view_3d.clear()
        expect_value(self.layout()).addWidget(self.view_3d)

    def update_line_riser_options(self) -> bool:
        regular_riser_count = 0
        has_brake = False
        for project in self.app.state.projects.get_active():
            lineset = project.get_glider_3d().lineset
            regular, brake = get_riser_indices(
                [line.lower_node.name for line in lineset.lowest_lines],
                project.glider.config.brake_name,
            )
            regular_riser_count = max(regular_riser_count, len(regular))
            has_brake |= brake is not None

        return self.config.update_line_riser_options(regular_riser_count, has_brake)

    def import_obj(self, filename: str) -> None:
        try:
            mesh = Mesh.from_obj(filename)
        except Exception:
            logger.exception("Failed to import OBJ file: %s", filename)
            return

        if self.imported_mesh_actor is not None:
            self.view_3d.remove_actor(self.imported_mesh_actor)

        self.imported_mesh_actor = openglider.rs.wgpu.MeshActor(mesh)
        self.view_3d.show_actor(self.imported_mesh_actor)
        self.clear_obj_button.setVisible(True)

    def clear_imported_obj(self) -> None:
        if self.imported_mesh_actor is None:
            return

        self.view_3d.renderer.RemoveActor(self.imported_mesh_actor)
        self.imported_mesh_actor = None
        self.clear_obj_button.setVisible(False)
        self.view_3d.rerender()
    
    def update_config(self) -> None:
        self.update_line_riser_options()
        self.view_3d.clear()
        changeset = self.actor_cache.get_update()
        for actor in changeset.active:
            actor.add(self.view_3d, self.config.config)

        if self.imported_mesh_actor is not None:
            self.view_3d.show_actor(self.imported_mesh_actor)

    def update_view(self) -> None:
        filter_changed = self.update_line_riser_options()
        changeset = self.actor_cache.get_update()

        for actor in changeset.removed:
            actor.remove(self.view_3d)

        for actor in changeset.added:
            actor.add(self.view_3d, self.config.config)

        if filter_changed:
            for actor in changeset.active:
                if actor not in changeset.added:
                    actor.update(self.view_3d, self.config.config)
        
        self.view_3d.rerender()

    def shutdown(self) -> None:
        if self.imported_mesh_actor is not None:
            self.view_3d.remove_actor(self.imported_mesh_actor)
            self.imported_mesh_actor = None
        self.view_3d.shutdown()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)
