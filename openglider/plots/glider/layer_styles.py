from __future__ import annotations

import openglider.rs
from openglider.rs import drawing

DEFAULT_LAYER_STROKES = {
    "cuts": "red",
    "outline": "red",
    "marks": "green",
    "debug": "grey",
    "inner": "green",
    "text": "blue",
    "stitches": "black",
    "sewing": "black",
    "L0": "black",
    "laser": "black",
    "rigidfoils": "green",
    "crossports": "red",
    "envelope": "white",
}


def initialize_part_layer_strokes(part: drawing.Part) -> drawing.Part:
    for layer_name, stroke in DEFAULT_LAYER_STROKES.items():
        with part.layer(layer_name) as layer:
            layer.style.stroke = stroke
    return part


def _stroke_is_unset(stroke: str | None) -> bool:
    if stroke is None:
        return True

    value = stroke.strip().lower()
    return value in {"white", "#fff", "#ffffff", "ffffff"}


def ensure_layer_stroke(part: drawing.Part, layer_name: str) -> None:
    with part.layer(layer_name) as layer:
        if _stroke_is_unset(layer.style.stroke):
            layer.style.stroke = DEFAULT_LAYER_STROKES.get(layer_name, "black")


def add_line(part: drawing.Part, layer_name: str, line: openglider.rs.vector.PolyLine2D) -> None:
    ensure_layer_stroke(part, layer_name)
    part.add_line(layer_name, line)


def add_lines(part: drawing.Part, layer_name: str, lines: list[openglider.rs.vector.PolyLine2D]) -> None:
    if not lines:
        return

    ensure_layer_stroke(part, layer_name)
    for line in lines:
        part.add_line(layer_name, line)
