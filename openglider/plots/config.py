import numpy
import functools

from openglider.plots import marks


def inside(fctn):
    return lambda p1, p2: fctn(2 * p1 - p2, p1)


def on_line(fctn):
    return lambda p1, p2: fctn(0.5 * (p1 + p2), 1.5 * p1 - 0.5 * p2)


sewing_config = {
    "marks": {
        "diagonal": inside(marks.triangle),
        "attachment-point": on_line(functools.partial(marks.cross, rotation=numpy.pi/4)),
        "panel-cut": marks.line,
        "rigidfoil": inside(marks.line)
    },
    "allowance": {
        "parallel": 0.01,
        "orthogonal": 0.01,
        "folded": 0.01,
        "general": 0.01,
        "diagonals": 0.01
    },
    "scale": 1000,
    "layers":
        {"CUTS": {
            "id": 'outer',
            "stroke_width": "1",
            "stroke": "green",
            "fill": "none"},
         "MARKS": {
             "id": 'marks',
             "stroke_width": "1",
             "stroke": "black",
             "fill": "none"},
         "TEXT": {
             "id": 'text',
             "stroke_width": "1",
             "stroke": "black",
             "fill": "none"},
         }


}