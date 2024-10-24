import logging

from openglider.gui.app.app import GliderApp
from openglider.gui.qt import QtWidgets
from openglider.gui.state.glider_list import GliderCache
from openglider.gui.views.compare.base import CompareView
from openglider.gui.views.compare.glider_3d.actor import GliderActors
from openglider.gui.views.compare.glider_3d.config import \
    GliderViewConfigWidget
from openglider.gui.views_3d.widgets import View3D

logger = logging.getLogger(__name__)


class Glider3DCache(GliderCache[GliderActors]):
    update_on_color_change = False
    update_on_name_change = False
    
    def get_object(self, element: str) -> GliderActors:
        project = self.elements[element]
        return GliderActors(project.element)


class Glider3DView(QtWidgets.QWidget, CompareView):
    def __init__(self, app: GliderApp):
        super().__init__()
        self.setLayout(QtWidgets.QVBoxLayout())
        self.app = app
        
        self.config = GliderViewConfigWidget(self)
        self.config.changed.connect(self.update_config)
        self.layout().addWidget(self.config)
        self.actor_cache = Glider3DCache(app.state.projects)

        self.view_3d = View3D(self)
        self.view_3d.show_axes = False
        self.view_3d.clear()
        self.layout().addWidget(self.view_3d)
    
    def update_config(self) -> None:
        self.view_3d.clear()
        for actor in self.actor_cache.get_update().active:
            actor.add(self.view_3d, self.config.config)

    def update_view(self) -> None:
        changeset = self.actor_cache.get_update()

        for actor in changeset.removed:
            actor.remove(self.view_3d)

        for actor in changeset.added:
            actor.add(self.view_3d, self.config.config)
        
        self.view_3d.rerender()
