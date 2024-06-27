from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, TypeAlias
import openglider.glider
import openglider.glider.parametric
import openglider
import euklid
from openglider.vector.drawing import Layout, PlotPart
from openglider.vector.unit import Percentage
from openglider.glider.rib.rib import Rib
from openglider.glider.cell.cell import Cell
from openglider import glider

if TYPE_CHECKING:
    from openglider.glider.cell.panel import Panel


logger = logging.getLogger(__name__)



class UVMap:
    def __init__(self, glider: glider.ParametricGlider) -> None:
        self.glider = glider
        self.glider3d = self.glider.get_glider_3d()
        self.cell_x_values = self.glider.shape.rib_x_values 


    def _get_length(self, x: Percentage, rib: Rib):
        ik_front = rib.profile_2d.get_ik(0)
        ik = rib.profile_2d.get_ik(x)

        length = rib.profile_2d.curve.get(ik_front, ik).get_length()

        if x.si < 0:
            length *= -1

        return length * rib.chord
    
    def _get_panel(self, cell_no: int, cell: Cell, panel: Panel) -> euklid.vector.PolyLine2D:
        p1 = (self.cell_x_values[cell_no],self._get_length(panel.cut_back.x_left, cell.rib1))
        p2 = (self.cell_x_values[cell_no+1],self._get_length(panel.cut_back.x_right, cell.rib2))
        p3 = (self.cell_x_values[cell_no+1],self._get_length(panel.cut_front.x_right, cell.rib2)) 
        p4 = (self.cell_x_values[cell_no],self._get_length(panel.cut_front.x_left, cell.rib1))

        return euklid.vector.PolyLine2D([p1, p2, p3, p4])
    
    def get_panels(self) -> dict[Panel, euklid.vector.PolyLine2D] | dict[Panel, euklid.vector.PolyLine2D]:
        panel_nodes: dict[Panel, euklid.vector.PolyLine2D] = {}
        panel_nodes_mirror: dict[Panel, euklid.vector.PolyLine2D] = {}

        for cell_no, cell in enumerate(self.glider3d.cells):
            for panel in cell.panels:
                nodes = self._get_panel(cell_no, cell, panel)
                panel_nodes[panel] = nodes
                if cell_no > 0 or not self.glider3d.has_center_cell:
                    panel_nodes_mirror[panel] = nodes.mirror()

        return panel_nodes, panel_nodes_mirror  
    
    def get_layout(self) -> Layout:
        points: list[euklid.vector.PolyLine2D] = []
        panel_nodes, panel_nodes_mirror = self.get_panels()

        for panel, panel_points in panel_nodes.items():
            points.append(panel_points.close())

        for panel, panel_points in panel_nodes_mirror.items():
            points.append(panel_points.close())

        layout = Layout()
        layout.parts.append(PlotPart(marks=points))
        layout = layout.scale(100)

        return layout

        