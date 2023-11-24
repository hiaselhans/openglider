from __future__ import annotations

import os
import logging
from typing import TYPE_CHECKING, Any, ClassVar
from openglider.gui.app.files import OpengliderDir

from openglider.gui.state.glider_list import GliderList
import openglider.jsonify
from openglider.glider.project import GliderProject
from openglider.utils.dataclass import BaseModel, Field

if TYPE_CHECKING:
    pass


class ApplicationState(BaseModel):
    projects: GliderList = Field(default_factory=lambda: GliderList())
    opened_tabs: dict[str, Any] = Field(default_factory=lambda: {})

    current_tab: str = ""
    current_preview: str = ""
    debug_level: int = logging.WARNING

    def __json__(self) -> dict[str, Any]:
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

    _dump_path: ClassVar[str] = "/tmp/openglider_state.json"

    def dump(self) -> None:
        with open(OpengliderDir.state_file_name(), "w") as state_file:
            openglider.jsonify.dump(self, state_file)
        
    @classmethod
    def load(cls) -> ApplicationState:
        try:
            with open(OpengliderDir.state_file_name(), "r") as state_file:
                result = openglider.jsonify.load(state_file)

                return result["data"]
        except Exception as e:
            print(e)
            return cls()
    
    @classmethod
    def clean(cls) -> None:
        state_filename = OpengliderDir.state_file_name()
        state_filename.unlink(missing_ok=True)

