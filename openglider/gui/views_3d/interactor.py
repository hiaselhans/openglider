from typing import Any
from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera


class Interactor(vtkInteractorStyleTrackballCamera):
    def __init__(self) -> None:
        super().__init__()
        self.AddObserver("MiddleButtonPressEvent",self.middleButtonPressEvent)  # type: ignore
        self.AddObserver("MiddleButtonReleaseEvent",self.middleButtonReleaseEvent)  # type: ignore
        self.AddObserver("RightButtonPressEvent",self.rightButtonPressEvent)  # type: ignore
        self.AddObserver("RightButtonReleaseEvent",self.rightButtonReleaseEvent)  # type: ignore

    def middleButtonPressEvent(self, obj: Any,event: Any) -> None:
        self.OnRightButtonDown()
        return

    def middleButtonReleaseEvent(self, obj: Any,event: Any) -> None:
        self.OnRightButtonUp()
        return

    def rightButtonPressEvent(self, obj: Any,event: Any) -> None:
        self.OnMiddleButtonDown()
        return

    def rightButtonReleaseEvent(self, obj: Any,event: Any) -> None:
        self.OnMiddleButtonUp()
        return