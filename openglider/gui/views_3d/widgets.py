from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

from openglider.utils.types import expect_value
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.mesh import Mesh
import openglider.rs

from openglider.gui.views_3d.interactor import OrbitInteractor


class _RendererShim:
    def __init__(self, view: "View3D") -> None:
        self._view = view

    def RemoveActor(self, actor: "openglider.rs.wgpu.MeshActor") -> None:
        self._view.remove_actor(actor)


class WgpuRenderWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)

        self._surface = QtGui.QWindow()
        self._container = QtWidgets.QWidget.createWindowContainer(self._surface, self)
        self._container.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        self._container.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self._container.setMouseTracking(True)
        self.setFocusProxy(self._container)
        self._container.installEventFilter(self)
        self._surface.installEventFilter(self)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._container)

        self._renderer: openglider.rs.wgpu.NativeWgpuRenderer | None = None
        self._mesh = Mesh()
        self._interactor = OrbitInteractor()
        self._is_closing = False
        self._render_scheduled = False
        # Maps id(actor) -> (actor, visible): tracks desired state for renderer re-creation
        self._actor_state: dict[int, tuple[openglider.rs.wgpu.MeshActor, bool]] = {}
        self._activate_timer = QtCore.QTimer(self)
        self._activate_timer.setSingleShot(True)
        self._activate_timer.timeout.connect(self._activate_surface)
        self._render_timer = QtCore.QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_now)
        self._rotation_timer = QtCore.QTimer(self)
        self._rotation_timer.setInterval(33)  # approximately 30 FPS
        self._rotation_timer.timeout.connect(self._update_rotation)

    def shutdown(self) -> None:
        """Deterministically release native renderer resources before app exit."""
        if self._is_closing:
            return

        self._is_closing = True
        self._activate_timer.stop()
        self._render_timer.stop()
        self._rotation_timer.stop()

        # Prevent any late input callbacks during destruction.
        self._container.removeEventFilter(self)
        self._surface.removeEventFilter(self)

        self.clearFocus()
        self._container.clearFocus()
        self._actor_state.clear()

        renderer = self._renderer
        if renderer is not None:
            renderer.clear_meshes()
            renderer.close()
        self._renderer = None

        self._container.hide()
        self._surface.hide()

    def _platform_info(self) -> tuple[str, int | None]:
        if sys.platform.startswith("win"):
            return ("win32", None)

        if sys.platform == "darwin":
            return ("appkit", None)

        app = QtWidgets.QApplication.instance()
        if isinstance(app, QtWidgets.QApplication) and hasattr(app, "nativeInterface"):
            native = app.nativeInterface()
            # Use the platform plugin name to pick the backend. QX11Application
            # exposes both display() (Xlib Display*) and connection() (xcb), so
            # inferring the backend from which accessors exist mislabels X11 as
            # Wayland and feeds an Xlib Display* to wgpu's Wayland path (SIGSEGV).
            platform_name = app.platformName()
            if platform_name.startswith("wayland") and hasattr(native, "display"):
                display = int(native.display())
                return ("wayland", display if display else None)
            if hasattr(native, "display"):
                display = int(native.display())
                return ("x11", display if display else None)
            if hasattr(native, "connection"):
                connection = int(native.connection())
                return ("xcb", connection if connection else None)

        # Fallback: explicit X11 display for Linux when Qt native interface is unavailable.
        x11_name = ctypes.util.find_library("X11")
        if x11_name:
            x11 = ctypes.CDLL(x11_name)
            x11.XOpenDisplay.restype = ctypes.c_void_p
            display = int(x11.XOpenDisplay(None) or 0)
            if display:
                return ("x11", display)

        # Final fallback keeps API call deterministic with an informative Rust-side error.
        return ("x11", None)

    def _render_size(self) -> tuple[int, int]:
        dpr = self.devicePixelRatioF()
        width = max(1, int(self.width() * dpr))
        height = max(1, int(self.height() * dpr))
        return width, height

    def _ensure_renderer(self) -> openglider.rs.wgpu.NativeWgpuRenderer | None:
        if self._is_closing:
            return None

        if not self.isVisible():
            return None

        if self._renderer is not None:
            return self._renderer

        if not self._surface.winId():
            return None

        width, height = self._render_size()
        platform, display_id = self._platform_info()
        self._renderer = openglider.rs.wgpu.NativeWgpuRenderer(
            platform,
            int(self._surface.winId()),
            width,
            height,
            display_id,
        )
        self._apply_camera()
        self._apply_projection()
        return self._renderer

    def _apply_camera(self) -> None:
        if self._renderer is None:
            return

        camera = self._interactor.camera
        self._renderer.set_camera(
            float(camera.yaw),
            float(camera.pitch),
            float(camera.distance),
            float(camera.target_x),
            float(camera.target_y),
            float(camera.target_z),
        )

    def _apply_projection(self) -> None:
        if self._renderer is not None:
            self._renderer.set_projection(self._interactor.projection_mode)

    def _update_rotation(self) -> None:
        if self._interactor.update_rotation():
            self._apply_camera()
            self._request_render()

    def _request_render(self) -> None:
        if self._is_closing or self._render_scheduled:
            return

        self._render_scheduled = True

        self._render_timer.start(0)

    def _render_now(self) -> None:
        self._render_scheduled = False
        if self._is_closing:
            return
        renderer = self._renderer
        if renderer is not None and self.isVisible():
            renderer.render()

    def _activate_surface(self) -> None:
        if self._is_closing or not self.isVisible():
            return

        renderer = self._ensure_renderer()
        if renderer is not None:
            # Sync all actors that should be visible to the (possibly new) renderer
            for actor, visible in self._actor_state.values():
                if visible:
                    renderer.add_actor(actor)
            self._request_render()

    def add_actor(self, actor: openglider.rs.wgpu.MeshActor) -> None:
        """Register a MeshActor and make it visible."""
        if self._is_closing:
            return
        self._actor_state[id(actor)] = (actor, True)
        renderer = self._ensure_renderer()
        if renderer is not None:
            renderer.add_actor(actor)
            self._request_render()

    def remove_actor(self, actor: openglider.rs.wgpu.MeshActor) -> None:
        """Hide a MeshActor (keeps GPU data cached for instant re-show)."""
        if self._is_closing:
            return
        if id(actor) in self._actor_state:
            self._actor_state[id(actor)] = (actor, False)
        renderer = self._renderer
        if renderer is not None:
            renderer.remove_actor(actor)
            self._request_render()

    def set_mesh(self, mesh: Mesh) -> None:
        if self._is_closing:
            return

        self._mesh = mesh
        renderer = self._renderer
        if renderer is not None:
            renderer.set_mesh(mesh)
            # Enable boundary-only edges so each mesh keeps its boundary cached
            renderer.set_draw_edges(True)
            renderer.set_boundary_only(True)
            self._request_render()

    def add_mesh(self, name: str, mesh: Mesh, draw_edges: bool | None = None, boundary_only: bool | None = None) -> None:
        """Add a named mesh to the renderer with optional per-mesh edge settings."""
        if self._is_closing:
            return

        renderer = self._ensure_renderer()
        if renderer is not None:
            renderer.add_mesh(name, mesh, draw_edges=draw_edges, boundary_only=boundary_only)
            self._request_render()

    def remove_mesh(self, name: str) -> None:
        """Remove a named mesh from the renderer."""
        if self._is_closing:
            return

        renderer = self._renderer
        if renderer is not None:
            renderer.remove_mesh(name)
            self._request_render()

    def clear_meshes(self) -> None:
        """Clear all meshes from the renderer."""
        if self._is_closing:
            return

        renderer = self._renderer
        if renderer is not None:
            renderer.clear_meshes()
            self._request_render()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        self._activate_timer.start(0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._surface.resize(self._render_size()[0], self._render_size()[1])
        renderer = self._renderer
        if renderer is not None:
            width, height = self._render_size()
            renderer.resize(width, height)
            self._request_render()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        _ = event
        self._request_render()

    def _handle_key_event(self, event: QtGui.QKeyEvent) -> bool:
        if not self._interactor.handle_key(event.text()):
            return False

        self._apply_camera()
        self._apply_projection()
        if event.text() in {"1", "2", "3", "4"} and self._renderer is not None:
            fitted_camera = self._renderer.fit_camera()
            if fitted_camera is not None:
                camera = self._interactor.camera
                camera.target_x, camera.target_y, camera.target_z, camera.distance = fitted_camera
        if self._interactor.is_rotating:
            self._rotation_timer.start()
        else:
            self._rotation_timer.stop()
        self._request_render()
        event.accept()
        return True

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched in (self._container, self._surface) and not self._is_closing:
            event_type = event.type()
            if event_type == QtCore.QEvent.Type.MouseButtonPress and isinstance(event, QtGui.QMouseEvent):
                self._interactor.begin_drag(event)
                return False
            if event_type == QtCore.QEvent.Type.MouseMove and isinstance(event, QtGui.QMouseEvent):
                if self._interactor.drag(event):
                    self._apply_camera()
                    self._request_render()
                return False
            if event_type == QtCore.QEvent.Type.MouseButtonRelease and isinstance(event, QtGui.QMouseEvent):
                self._interactor.end_drag()
                return False
            if event_type == QtCore.QEvent.Type.Wheel and isinstance(event, QtGui.QWheelEvent):
                if self._interactor.zoom(event.angleDelta().y()):
                    self._apply_camera()
                    self._request_render()
                return False
            if event_type == QtCore.QEvent.Type.KeyPress and isinstance(event, QtGui.QKeyEvent):
                if self._handle_key_event(event):
                    return True

        return super().eventFilter(watched, event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if not self._is_closing and self._handle_key_event(event):
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._is_closing:
            return
        self._interactor.begin_drag(event)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._is_closing:
            return
        if self._interactor.drag(event):
            self._apply_camera()
            self._request_render()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._is_closing:
            return
        self._interactor.end_drag()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        if self._is_closing:
            return
        if self._interactor.zoom(event.angleDelta().y()):
            self._apply_camera()
            self._request_render()
        super().wheelEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)


class View3D(QtWidgets.QWidget):
    show_axes = True

    def __init__(self, parent: QtWidgets.QWidget=None) -> None:
        super().__init__(parent)
        self.setLayout(QtWidgets.QHBoxLayout(self))
        expect_value(self.layout()).setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)

        self.frame = QtWidgets.QFrame()
        self.frame.setLayout(QtWidgets.QVBoxLayout())
        expect_value(self.frame.layout()).setContentsMargins(0, 0, 0, 0)
        self.frame.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Expanding)
        expect_value(self.layout()).addWidget(self.frame)
        self.render_widget = WgpuRenderWidget(self.frame)
        expect_value(self.frame.layout()).addWidget(self.render_widget)

        # Backwards-compatible names used by drop handlers.
        self.render_window_interactor = self.render_widget
        self.renderer = _RendererShim(self)

        self._actors: list[openglider.rs.wgpu.MeshActor] = []

        self._has_rendered = False
        self.clear(autorerender=False)

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        if self.render_widget._is_closing:
            return
        if not self._has_rendered:
            self.rerender()
            self._has_rendered = True

    def clear(self, autorerender: bool=True) -> None:
        for actor in self._actors:
            self.render_widget.remove_actor(actor)
        self._actors.clear()
        if autorerender:
            self.render_widget._request_render()

    @staticmethod
    def _unwrap_actor(actor: object) -> openglider.rs.wgpu.MeshActor:
        if isinstance(actor, openglider.rs.wgpu.MeshActor):
            return actor
        wrapped = getattr(actor, "actor", None)
        if isinstance(wrapped, openglider.rs.wgpu.MeshActor):
            return wrapped
        raise TypeError("View3D.show_actor expects MeshActor or wrapper with .actor")

    def show_actor(self, actor: object) -> None:
        actor_obj = self._unwrap_actor(actor)
        if actor_obj not in self._actors:
            self._actors.append(actor_obj)
        self.render_widget.add_actor(actor_obj)

    def remove_actor(self, actor: object) -> None:
        actor_obj = self._unwrap_actor(actor)
        if actor_obj in self._actors:
            self._actors.remove(actor_obj)
        self.render_widget.remove_actor(actor_obj)

    def _add_actor_to_renderer(self, mesh: Mesh, actor_type: str) -> None:
        """Legacy helper - kept for any external callers."""
        pass

    def rerender(self) -> None:
        if self.render_widget._is_closing:
            return
        # Re-register all visible actors (idempotent - GPU data cached after first upload)
        for actor in self._actors:
            self.render_widget.add_actor(actor)

    def shutdown(self) -> None:
        if self.render_widget._is_closing:
            return

        self.clear(autorerender=False)
        self.render_widget.shutdown()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)


