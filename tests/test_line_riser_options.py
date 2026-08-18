from openglider.gui.views.compare.glider_3d.config import get_riser_indices, get_riser_options


def test_brake_is_identified_by_its_configured_ods_name() -> None:
    assert get_riser_indices(["handles", "main", "main"], "handles") == ([1, 2], 0)


def test_brake_riser_is_labeled_and_listed_last() -> None:
    assert get_riser_options(3, has_brake=True) == [
        ("All", "all"),
        ("A", 0),
        ("B", 1),
        ("C", 2),
        ("Br", "brake"),
    ]


def test_brake_option_is_omitted_when_no_brake_cascade_exists() -> None:
    assert get_riser_options(2, has_brake=False) == [
        ("All", "all"),
        ("A", 0),
        ("B", 1),
    ]
