import math

import pytest

from openglider.gui.views_3d.interactor import OrbitInteractor


def test_camera_view_hotkeys() -> None:
    interactor = OrbitInteractor()
    interactor.camera.target_z = -2.0

    assert interactor.handle_key("1")
    assert interactor.camera.yaw == pytest.approx(math.pi)
    assert interactor.camera.pitch == 0.0
    assert interactor.camera.target_z == -2.0

    assert interactor.handle_key("2")
    assert interactor.camera.pitch == pytest.approx(-1.54)

    assert interactor.handle_key("3")
    assert interactor.camera.yaw == pytest.approx(-math.pi / 2)
    assert interactor.camera.pitch == 0.0

    assert interactor.handle_key("4")
    assert interactor.camera.pitch == pytest.approx(1.54)
    assert not interactor.handle_key("x")


def test_projection_and_rotation_hotkeys() -> None:
    interactor = OrbitInteractor()

    assert interactor.projection_mode == "orthographic"
    assert interactor.handle_key("5")
    assert interactor.projection_mode == "perspective"
    assert interactor.handle_key("5")
    assert interactor.projection_mode == "orthographic"

    initial_yaw = interactor.camera.yaw
    assert interactor.handle_key("0")
    assert interactor.is_rotating
    assert interactor.update_rotation()
    assert interactor.camera.yaw != initial_yaw

    assert interactor.handle_key("0")
    assert not interactor.is_rotating
    assert not interactor.update_rotation()
