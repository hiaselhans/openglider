"""The marks of a winglet on the upper panels it is sewn on (see openglider.glider.winglet)"""
from __future__ import annotations

import logging
from collections.abc import Callable

import openglider.rs
from openglider.glider.cell.cell import Cell, FlattenedCell
from openglider.glider.cell.panel import Panel
from openglider.glider.cell.panel.panel import FlattenedPanel
from openglider.glider.glider import Glider
from openglider.glider.winglet import WingletGeometry
from openglider.plots.config import PatternConfig
from openglider.plots.glider.cell import CellPlotMaker
from openglider.rs import drawing

logger = logging.getLogger(__name__)

PolyLine2D = openglider.rs.vector.PolyLine2D
Vector2D = openglider.rs.vector.Vector2D


def _sewn_area(flattened: FlattenedPanel) -> PolyLine2D:
    """the panel between its sewing lines: the seam allowances overlap the neighbours"""
    inner = flattened.flattened_cell.inner
    front = flattened.cut_front.inner_indices
    back = flattened.cut_back.inner_indices

    nodes = [line.get(ik) for line, ik in zip(inner, front)]
    nodes += inner[-1].get(front[-1], back[-1]).nodes
    nodes += [line.get(ik) for line, ik in zip(inner[::-1], back[::-1])]
    nodes += inner[0].get(back[0], front[0]).nodes

    return PolyLine2D(nodes).close()


def _outer_contour(footprint: PolyLine2D, allowance: float) -> PolyLine2D:
    """the footprint pushed outwards by the allowance, whichever way the outline runs"""
    candidates = [footprint.offset(allowance), footprint.offset(-allowance)]
    return max(candidates, key=lambda line: abs(line.get_area()))


def _rings(contour: PolyLine2D, spacing: float) -> list[Vector2D]:
    """points evenly spaced along a closed contour, as close to spacing as divides it"""
    length = contour.get_length()
    count = max(round(length / spacing), 3)
    return [contour.get(contour.walk(0, i * length / count)) for i in range(count)]


class _CellMap:
    """
    The flattened cell as a map from (span position, profile index) to the plane. The span
    position runs on past the cell (below 0, above 1): the panels of the cells next to it
    """
    def __init__(self, flattened: FlattenedCell):
        self.left, self.right = flattened.ballooned[0], flattened.ballooned[1]
        self.last = min(len(self.left), len(self.right)) - 1

    def point(self, span: float, ik: float) -> Vector2D:
        ik = min(max(ik, 0.), self.last)
        return self.left.get(ik) * (1 - span) + self.right.get(ik) * span

    def width(self, ik: float) -> float:
        return (self.right.get(ik) - self.left.get(ik)).length()

    def locate(self, point: Vector2D, span: float, ik: float) -> tuple[float, float]:
        """the (span position, profile index) of a point, by newton from a guess"""
        for _ in range(12):
            here = self.point(span, ik)
            d_span = (self.point(span + 1e-3, ik) - here) * 1e3
            d_ik = (self.point(span, ik + 1e-2) - here) * 1e2
            error = point - here
            det = d_span[0] * d_ik[1] - d_span[1] * d_ik[0]
            if abs(det) < 1e-15:
                break
            step_span = (error[0] * d_ik[1] - error[1] * d_ik[0]) / det
            step_ik = (d_span[0] * error[1] - d_span[1] * error[0]) / det
            span += step_span
            ik = min(max(ik + step_ik, 0.), self.last)
            if abs(step_span) < 1e-9 and abs(step_ik) < 1e-7:
                break
        return span, ik


def _lay(located: list[tuple[float, float]], step: int, home: _CellMap, cell: _CellMap) -> list[Vector2D]:
    """
    points located on the home cell, laid on the cell step cells away (-1, 0, 1): the span
    runs on over the rib by the width of the cells
    """
    points = []
    for span, ik in located:
        if step > 0:
            span = (span - 1) * home.width(ik) / cell.width(ik)
        elif step < 0:
            span = 1 + span * home.width(ik) / cell.width(ik)
        points.append(cell.point(span, ik))
    return points


def get_winglet_marks(
    winglet: WingletGeometry, glider: Glider, get_plotmaker: Callable[[Cell], CellPlotMaker]
) -> dict[int, dict[Panel, list[PolyLine2D]]]:
    """
    The marks of the winglet, by cell index and upper panel: the footprint (the sewing line), the
    same outline grown by the allowance, and rings along both. A ring is a single point: the
    panel plot lays it out as the laser marks are (marks_controlpoint).

    The footprint is drawn on the cell the winglet is on. Turned (its angle), it can run over
    the ribs: its points are located on that cell, by span position and profile index, and laid
    on the cells next to it from there.
    get_plotmaker: the prepared plotmaker of a cell (PlotMaker._get_cellplotmaker)
    """
    cell_index, span_position = winglet.get_cell(glider)
    home = get_plotmaker(glider.cells[cell_index])
    config = home.config

    home_flat = next(
        plot.flattened_panel for panel, plot in home.panel_plots.items() if not panel.is_lower()
    )
    assert home_flat is not None
    footprint = winglet.get_footprint(home_flat.flattened_cell, home_flat.x_distribution, span_position)
    contours = [footprint, _outer_contour(footprint, config.winglet_allowance.si)]
    rings = [_rings(contour, config.winglet_mark_spacing.si) for contour in contours]

    # every point by (span position on the home cell, profile index)
    home_map = _CellMap(home_flat.flattened_cell)
    ik_guess = sum(home_flat.cut_front.inner_indices + home_flat.cut_back.inner_indices) / (2 * len(home_flat.cut_front.inner_indices))

    def locate(points: list[Vector2D]) -> list[tuple[float, float]]:
        return [home_map.locate(point, span_position, ik_guess) for point in points]

    located_contours = [locate(contour.nodes) for contour in contours]
    located_rings = [locate(points) for points in rings]

    result: dict[int, dict[Panel, list[PolyLine2D]]] = {}
    for index in (cell_index - 1, cell_index, cell_index + 1):
        if not 0 <= index < len(glider.cells):
            continue

        pm = home if index == cell_index else get_plotmaker(glider.cells[index])
        upper = [(panel, plot.flattened_panel) for panel, plot in pm.panel_plots.items() if not panel.is_lower()]
        if not upper:
            continue
        cell_map = _CellMap(upper[0][1].flattened_cell)  # type: ignore[union-attr]

        step = index - cell_index
        laid_contours = [PolyLine2D(_lay(located, step, home_map, cell_map)) for located in located_contours]
        laid_rings = [_lay(located, step, home_map, cell_map) for located in located_rings]

        panel_marks: dict[Panel, list[PolyLine2D]] = {}
        for panel, flattened in upper:
            assert flattened is not None
            area = _sewn_area(flattened)
            marks: list[PolyLine2D] = []
            for contour, points in zip(laid_contours, laid_rings):
                marks += [segment for segment in contour.clip(area) if len(segment) > 1]
                marks += [PolyLine2D([point]) for point in points if area.contains(point)]
            if marks:
                panel_marks[panel] = marks

        if panel_marks:
            result[index] = panel_marks

    if not result:
        logger.warning(f"winglet: no upper panel of cell {glider.cells[cell_index].name} carries the footprint")

    return result


def get_winglet_layout(winglet: WingletGeometry, config: PatternConfig, glider: Glider) -> drawing.Layout:
    """
    The pieces of the winglet, flattened as the ones of a glider: its ribs (the flat tip left out)
    and its panels, upper and lower, in a frame named winglet. The panels are flattened from the
    winglet in place on the cloth of the glider, as in 3d. The names of its pieces start with W,
    apart from the glider's.
    """
    from openglider.plots.glider import PlotMaker

    glider = winglet.get_placed_glider(glider)
    for rib in glider.ribs:
        rib.name = f"W{rib.name}"
    for cell in glider.cells:
        for panel in cell.panels:
            panel.name = f"W{panel.name}"

    plots = PlotMaker(glider, config)
    plots.get_panels()
    plots.get_ribs()

    ribs = drawing.Layout.stack_column(plots.ribs, config.patterns_align_dist_y)
    layout = drawing.Layout.stack_row([ribs, plots.panels], 2 * config.patterns_align_dist_x)

    border = PlotMaker._border_part(layout)
    if border is not None:
        layout.add_part(border)
    PlotMaker._add_label(layout, "winglet")
    return layout
