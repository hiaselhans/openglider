from typing import Any
from collections.abc import Callable
from openglider.gui.qt import QtCore, QtWidgets
from openglider.utils.config import Config


class ToggleGroup(QtWidgets.QWidget):
    config: Config
    changed = QtCore.Signal()
    
    def __init__(self, options: Any, horizontal: bool=True) -> None:
        super().__init__()
        if horizontal:
            self.setLayout(QtWidgets.QHBoxLayout())
        else:
            self.setLayout(QtWidgets.QVBoxLayout())
        
        self.checkboxes = {}

        def get_clickhandler(prop: str) -> Callable[[Any], None]:
            
            def toggle_prop(value: bool) -> None:
                setattr(self.config, prop, value)
                self.changed.emit()
            
            return toggle_prop

        for prop in self.config.__annotations__:

            checkbox = QtWidgets.QCheckBox(self)
            checkbox.setChecked(getattr(self.config, prop))
            checkbox.setText(f"{prop}")
            checkbox.clicked.connect(get_clickhandler(prop))
            self.layout().addWidget(checkbox)
            self.checkboxes[prop] = checkbox
