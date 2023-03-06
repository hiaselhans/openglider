from __future__ import annotations
import asyncio

import os
import logging
from typing import TYPE_CHECKING, Dict, Any

from openglider.gui.state.glider_list import GliderList
import openglider.jsonify
from openglider.glider.project import GliderProject
from openglider.utils.dataclass import dataclass, Field

if TYPE_CHECKING:
    from openglider.gui.views.glider_list import GliderListWidget

@dataclass
class ApplicationState:
    projects: GliderList = Field(default_factory=lambda: GliderList())
    opened_tabs: Dict[str, Any] = Field(default_factory=lambda: {})

    current_tab: str = ""
    current_preview: str = ""
    debug_level: int = logging.WARNING

    def __json__(self) -> Dict[str, Any]:
        return {
            "projects": self.projects,
            "opened_tabs": {tab.name: tab.__class__.__name__ for tab in self.opened_tabs.values()},
            
            "current_tab": self.current_tab,
            "current_preview": self.current_preview,
            "debug_level": self.debug_level
        }

    def add_glider_project(self, project: GliderProject) -> None:
        if project.name in self.projects:
            raise Exception(f"project with name {project.name} already in the list")
        
        self.projects.add(project.name, project)
    
    def update_glider_project(self, project: GliderProject) -> None:
        self.projects[project.name] = project
    
    def remove_glider_project(self, project: GliderProject) -> None:
        self.projects.remove(project.name)

    _dump_path = "/tmp/openglider_state.json"

    def dump(self) -> None:
        with open(self._dump_path, "w") as fp:
            openglider.jsonify.dump(self, fp)
        
    @classmethod
    def load(cls) -> ApplicationState:
        if os.path.isfile(cls._dump_path):
            with open(cls._dump_path, "r") as state_file:
                result = openglider.jsonify.load(state_file)

                return result["data"]
            
        return cls()