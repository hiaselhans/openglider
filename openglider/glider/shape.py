from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Self, TypeAlias
import abc

import openglider.rs
from openglider.utils.dataclass import BaseModel
from openglider.vector.unit import Angle, Percentage

if TYPE_CHECKING:
    from openglider.glider.cell.panel import Panel


logger = logging.getLogger(__name__)

V2: TypeAlias = openglider.rs.vector.Vector2D

class ShapeBase(abc.ABC):
    @abc.abstractmethod
    def copy(self) -> Self:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_half_shape(self, zrot: list[Angle | None] | None = None) -> Shape:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_shape(self) -> Shape:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def has_center_cell(self) -> bool:
        raise NotImplementedError()
    
    @abc.abstractmethod
    def get_point(self, x: float | int, y: float | Percentage) -> openglider.rs.vector.Vector2D:
        raise NotImplementedError()

    @abc.abstractmethod
    def get_baseline(self, position: Percentage) -> openglider.rs.vector.PolyLine2D:
        raise NotImplementedError()

    @abc.abstractmethod
    def chord_at(self, x: float) -> float:
        raise NotImplementedError()

    @abc.abstractmethod
    def scale(self, x: float = 1.0, y: float | None = None) -> Any:
        raise NotImplementedError()
    
    @property
    @abc.abstractmethod
    def cell_no(self) -> int:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def half_cell_num(self) -> int:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def rib_no(self) -> int:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def ribs(self) -> list[tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]]:
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def rib_x_values(self) -> list[float]:
        raise NotImplementedError()
    
    @property
    def cell_x_values(self) -> list[float]:
        ribs = self.rib_x_values

        cells = []
        for x1, x2 in zip(ribs[:-1], ribs[1:]):
            cells.append((x1+x2)/2)

        return cells
    
    @property
    @abc.abstractmethod
    def span(self) -> float:
        raise NotImplementedError()
    
    @property
    @abc.abstractmethod
    def chords(self) -> list[float]:
        raise NotImplementedError()#
    
    @property
    @abc.abstractmethod
    def area(self) -> float:
        raise NotImplementedError()
    
    @property
    def aspect_ratio(self) -> float:
        return self.span ** 2 / self.area

    @abc.abstractmethod
    def get_sweep(self) -> float:
        raise NotImplementedError()
    

class Shape(ShapeBase, BaseModel):
    front: openglider.rs.vector.PolyLine2D
    back: openglider.rs.vector.PolyLine2D

    def get_half_shape(self, zrot: list[Angle | None] | None = None) -> Shape:
        del zrot
        return self.copy()

    def get_shape(self) -> Shape:
        return self.copy()

    @property
    def has_center_cell(self) -> bool:
        return abs(self.front.nodes[0][0]) > 1e-5 and abs(self.back.nodes[0][0]) > 1e-5


    def get_point(self, x: float | int, y: float | Percentage) -> openglider.rs.vector.Vector2D:
        front = self.front.get(x)
        back = self.back.get(x)

        return front + (back-front) *  float(y)
    
    def get_baseline(self, position: Percentage) -> openglider.rs.vector.PolyLine2D:
        points = []
        for front, back in zip(self.front.nodes, self.back.nodes):
            points.append(
                front + (back - front) * position.si
            )

        return openglider.rs.vector.PolyLine2D(points)

    def chord_at(self, x: float) -> float:
        front = self.front.get(x)
        back = self.back.get(x)
        return (back - front).length()

    def get_panel(self, cell_no: int, panel: Panel) -> tuple[V2, V2, V2, V2]:
        p1 = self.get_point(cell_no, panel.cut_front.x_left)
        p2 = self.get_point(cell_no, panel.cut_back.x_left)
        p3 = self.get_point(cell_no+1, panel.cut_back.x_right)
        p4 = self.get_point(cell_no+1, panel.cut_front.x_right)

        return p1, p2, p3, p4

    @property
    def half_cell_num(self) -> int:
        return len(self.front.nodes) // 2 + self.has_center_cell

    @property
    def cell_no(self) -> int:
        return 2 * (len(self.front.nodes) - 1) - self.has_center_cell

    @property
    def rib_no(self) -> int:
        return 2 * len(self.front.nodes) - 1 + self.has_center_cell

    @property
    def ribs(self) -> list[tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]]:
        return [(self.front.get(x), self.back.get(x)) for x in range(len(self.front.nodes))]

    @property
    def rib_x_values(self) -> list[float]:
        return [float(point[0]) for point in self.front.nodes]

    @property
    def span(self) -> float:
        return self.front.nodes[-1][0] * 2
    
    @span.setter
    def span(self, span: float) -> None:
        span_old = self.span
        self.scale(span/span_old, 1)


    @property
    def chords(self) -> list[float]:
        return [(p1-p2).length() for p1, p2 in zip(self.front.nodes, self.back.nodes)]

    @property
    def cell_widths(self) -> list[float]:
        return [p2[0]-p1[0] for p1, p2 in zip(self.front.nodes[:-1], self.front.nodes[1:])]

    @property
    def area(self) -> float:
        front, back = self.front, self.back
        area = 0.
        for cell_no in range(len(self.front.nodes) - 1):
            l = (front.get(cell_no)[1] - back.get(cell_no)[1]) + (front.get(cell_no+1)[1] - back.get(cell_no+1)[1])
            cell_area = l * (front.get(cell_no+1)[0] - front.get(cell_no)[0]) / 2
            if not (cell_no == 0 and self.has_center_cell):
                cell_area *= 2
            area += cell_area
        return area
    
    @area.setter
    def area(self, area: float) -> None:
        factor = math.sqrt(area / self.area)

        self.scale(factor, factor)

    def scale(self, x: float=1, y: float =1.) -> Shape:
        self.front = self.front.scale(openglider.rs.vector.Vector2D([x, y]))
        self.back = self.back.scale(openglider.rs.vector.Vector2D([x, y]))

        return self

    def get_sweep(self) -> float:
        ribs = self.ribs
        if not ribs:
            return 0.0

        center_front, center_back = ribs[0]
        tip_front, tip_back = ribs[-1]
        denominator = float((center_front + center_back)[1])
        if abs(denominator) < 1e-9:
            return 0.0

        delta_y = float(((tip_front + tip_back) * 0.5)[1] - center_front[1])
        return delta_y / denominator
    
    def copy(self, *args: Any, **kwargs: Any) -> Self:
        return self.__class__(
            front=self.front.copy(),
            back=self.back.copy()
        )

    def copy_complete(self) -> Shape:
        front = self.front.mirror().reverse()
        back = self.back.mirror().reverse()

        if front.nodes[-1][0] != 0:
            start = 2
        else:
            start = 1

        front_nodes = front.nodes + self.front.copy().nodes[start:]
        back_nodes = back.nodes + self.back.copy().nodes[start:]

        return Shape(
            front=openglider.rs.vector.PolyLine2D(front_nodes),
            back=openglider.rs.vector.PolyLine2D(back_nodes)
        )

    @staticmethod
    def _close_polyline(polyline: openglider.rs.vector.PolyLine2D) -> openglider.rs.vector.PolyLine2D:
        nodes = list(polyline.nodes)
        if nodes and nodes[0] != nodes[-1]:
            nodes.append(nodes[0])
        return openglider.rs.vector.PolyLine2D(nodes)

    def _get_symmetric_outline(self) -> openglider.rs.vector.PolyLine2D:
        front_nodes = list(self.front.nodes)
        back_nodes = list(self.back.nodes)

        if front_nodes and abs(float(front_nodes[0][0])) > 1e-12:
            front_nodes[0] = openglider.rs.vector.Vector2D([0.0, float(front_nodes[0][1])])
        if back_nodes and abs(float(back_nodes[0][0])) > 1e-12:
            back_nodes[0] = openglider.rs.vector.Vector2D([0.0, float(back_nodes[0][1])])

        outline_nodes = front_nodes + back_nodes[::-1]
        return self._close_polyline(openglider.rs.vector.PolyLine2D(outline_nodes))

    def get_attachment_point_areas(
        self,
        attachment_points: list[tuple[str, openglider.rs.vector.Vector2D]],
    ) -> dict[str, openglider.rs.vector.PolyLine2D | None]:
        if not attachment_points:
            return {}

        outline = self._get_symmetric_outline()
        names_by_position: dict[tuple[float, float], list[str]] = {}
        unique_points: list[openglider.rs.vector.Vector2D] = []

        for name, point in attachment_points:
            key = (float(point[0]), float(point[1]))
            if key not in names_by_position:
                unique_points.append(openglider.rs.vector.Vector2D([key[0], key[1]]))
                names_by_position[key] = []
            names_by_position[key].append(name)

        voronoi_areas = openglider.rs.voronoi.voronoi_areas(outline, unique_points)

        result: dict[str, openglider.rs.vector.PolyLine2D | None] = {}
        for point, area in zip(unique_points, voronoi_areas):
            key = (float(point[0]), float(point[1]))

            closed_area: openglider.rs.vector.PolyLine2D | None = None
            if area is not None:
                closed_area = self._close_polyline(area)

            for name in names_by_position.get(key, []):
                result[name] = closed_area.copy() if closed_area is not None else None

        return result

    def apply_zrot(self, zrot: list[Angle | None], baseline_pct: Percentage) -> Shape:
        baseline = self.get_baseline(baseline_pct).nodes
        front_new: list[openglider.rs.vector.Vector2D] = []
        back_new: list[openglider.rs.vector.Vector2D] = []

        for rib_no, angle in enumerate(zrot):
            if angle is None:
                front_new.append(self.front.nodes[rib_no].copy())
                back_new.append(self.back.nodes[rib_no].copy())
            else:
                rotation = openglider.rs.vector.Rotation2D(angle.si)
                front_new.append(
                    baseline[rib_no] + rotation.apply(self.front.nodes[rib_no]-baseline[rib_no])
                )
                back_new.append(
                    baseline[rib_no] + rotation.apply(self.back.nodes[rib_no]-baseline[rib_no])
                )
        
        return Shape(
            front=openglider.rs.vector.PolyLine2D(front_new),
            back=openglider.rs.vector.PolyLine2D(back_new)
        )
