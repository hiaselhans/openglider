from __future__ import annotations

from io import TextIOWrapper
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import OpenTextMode

user_dir = Path().expanduser()

class OpengliderDir:
    base_path = Path("~/openglider").expanduser()

    @classmethod
    def logfile(cls, mode: OpenTextMode="r") -> TextIOWrapper:
        return open(cls.base_path / "error_log", mode=mode)
    
    @classmethod
    def state_file_name(cls) -> Path:
        return cls.base_path / "state.json"

    def get_directory(cls, path: str | Path) -> Path:
        new_path = cls.base_path / path    
        new_path.mkdir(exist_ok=True)

        return new_path
