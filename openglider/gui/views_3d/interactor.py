from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from openglider.gui.qt import QtCore, QtGui


ProjectionMode = Literal["orthographic", "perspective"]


@dataclass
class OrbitCameraState:
    yaw: float = -1.2
    pitch: float = 0.3
    distance: float = 20.0
    target_x: float = 0.0
    target_y: float = 0.0
    target_z: float = 0.0


class OrbitInteractor:
    """Simple orbit/pan/zoom camera interactor driven by Qt mouse events."""

    ORBIT_SENSITIVITY = 0.008
    PAN_SENSITIVITY = 0.0025
    DOLLY_SENSITIVITY = 0.006

    def __init__(self) -> None:
        self.camera = OrbitCameraState()
        self.projection_mode: ProjectionMode = "orthographic"
        self.is_rotating = False
        self.rotation_speed = math.radians(1.0)
        self._last_pos: QtCore.QPointF | None = None

    def begin_drag(self, event: QtGui.QMouseEvent) -> None:
        self._last_pos = event.position()

    def end_drag(self) -> None:
        self._last_pos = None

    def drag(self, event: QtGui.QMouseEvent) -> bool:
        if self._last_pos is None:
            self._last_pos = event.position()
            return False

        current = event.position()
        delta = current - self._last_pos
        self._last_pos = current
        dx = float(delta.x())
        dy = float(delta.y())

        is_shift = bool(event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)

        # Requested mappings:
        # - Left drag: orbit
        # - Right drag: pan
        # - Middle drag or Shift+Left: pan
        if event.buttons() & QtCore.Qt.MouseButton.MiddleButton or (
            is_shift and event.buttons() & QtCore.Qt.MouseButton.LeftButton
        ):
            self._pan(dx, dy)
            return True

        if event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            self.camera.yaw -= dx * self.ORBIT_SENSITIVITY
            self.camera.pitch += dy * self.ORBIT_SENSITIVITY
            self.camera.pitch = max(-1.54, min(1.54, self.camera.pitch))
            return True

        if event.buttons() & QtCore.Qt.MouseButton.RightButton:
            self._pan(dx, dy)
            return True

        return False

    def zoom(self, angle_delta_y: int) -> bool:
        factor = math.exp(-angle_delta_y / 960.0)
        self.camera.distance = max(0.05, self.camera.distance * factor)
        return True

    def handle_key(self, key: str) -> bool:
        """Apply a viewport hotkey and report whether it was handled."""
        views = {
            "1": (math.pi, 0.0),
            "2": (0.0, -1.54),
            "3": (-math.pi / 2, 0.0),
            "4": (0.0, 1.54),
        }
        if key in views:
            self.camera.yaw, self.camera.pitch = views[key]
        elif key == "5":
            self.projection_mode = (
                "orthographic" if self.projection_mode == "perspective" else "perspective"
            )
        elif key == "0":
            self.is_rotating = not self.is_rotating
        else:
            return False
        return True

    def update_rotation(self) -> bool:
        if not self.is_rotating:
            return False
        self.camera.yaw = (self.camera.yaw + self.rotation_speed) % (2 * math.pi)
        return True

    def _pan(self, dx: float, dy: float) -> None:
        # Screen-space pan based on the current camera frame.
        scale = self.PAN_SENSITIVITY * max(0.05, self.camera.distance)

        cy = math.cos(self.camera.yaw)
        sy = math.sin(self.camera.yaw)
        cp = math.cos(self.camera.pitch)
        sp = math.sin(self.camera.pitch)

        # Forward points from camera to target in a z-up frame.
        fx = -cp * cy
        fy = -cp * sy
        fz = -sp

        # Right = normalize(forward x world_up), with world_up=(0,0,1)
        rx = fy
        ry = -fx
        rz = 0.0
        rlen = math.sqrt(rx * rx + ry * ry + rz * rz)
        if rlen > 1e-6:
            rx /= rlen
            ry /= rlen

        # Up = right x forward
        ux = ry * fz - rz * fy
        uy = rz * fx - rx * fz
        uz = rx * fy - ry * fx

        self.camera.target_x += (-rx * dx + ux * dy) * scale
        self.camera.target_y += (-ry * dx + uy * dy) * scale
        self.camera.target_z += (-rz * dx + uz * dy) * scale

    def _dolly(self, dy: float) -> None:
        factor = math.exp(dy * self.DOLLY_SENSITIVITY)
        self.camera.distance = max(0.05, self.camera.distance * factor)
