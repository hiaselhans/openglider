from __future__ import annotations
import logging
import math
from typing import TYPE_CHECKING

import openglider.rs
from openglider.rs import drawing
from openglider.glider.cell import cell
from openglider.glider.cell.panel import cuts
from openglider.mesh import Mesh
from openglider.glider.cell.panel.panel import PANELCUT_TYPES, FlattenedPanel
from openglider.utils.dataclass import dataclass
from openglider.vector.unit import Length, Percentage

if TYPE_CHECKING:
    from openglider.glider.cell import Cell
    from openglider.glider.cell.panel import Panel

logger = logging.getLogger(__name__)

@dataclass
class EntryStrap:
    position: Percentage
    opening_index: int
    material: str
    extra_material: Length

    def _get_entry_index(self, cell: Cell, midribs: int) -> int:
        entry_count = 0

        for i in range(len(cell.panels)-1):
            panel1 = cell.panels[i]
            panel2 = cell.panels[i+1]

            if panel1.cut_back != panel2.cut_front:
                if entry_count < self.opening_index:
                    entry_count += 1
                else:
                    return i
            
        raise ValueError(f"invalid opening index {self.opening_index} for EntryStrap on cell {cell.name}: not enough openings in cell (only {entry_count})")

    def get_data(self, cell: Cell, midribs: int) -> tuple[int, float, float, float]:
        profile_3d = cell.midrib(self.position.si)
        panel_1_index = self._get_entry_index(cell, midribs)

        cut_front = cell.panels[panel_1_index].cut_back
        cut_back = cell.panels[panel_1_index+1].cut_front
        
        ik1 = cut_front.get_ik_values(cell, [self.position.si], False)[0]
        ik2 = cut_back.get_ik_values(cell, [self.position.si], False)[0]

        p1: openglider.rs.vector.Vector3D = profile_3d.curve.get(ik1)
        p2: openglider.rs.vector.Vector3D = profile_3d.curve.get(ik2)

        length = (p2 - p1).length() + self.extra_material.si

        return panel_1_index, ik1, ik2, length
    
    def get_marks(self, cell: Cell, midribs: int, cut_types: dict[PANELCUT_TYPES, type[cuts.Cut]] | None) -> dict[Panel, list[openglider.rs.vector.PolyLine2D]]:
        data = self.get_data(cell, midribs)
        panel_1_index = data[0]

        panel_front = cell.panels[panel_1_index]
        panel_back = cell.panels[panel_1_index+1]

        def get_mark(panel: Panel, is_first: bool) -> list[openglider.rs.vector.PolyLine2D]:
            flattended = panel.get_flattened(cell, midribs=midribs, cut_types=cut_types)

            if is_first:
                cut = panel.cut_back
                cut_result = flattended.cut_back
                offset = cut.seam_allowance
            else:
                cut = panel.cut_front
                cut_result = flattended.cut_front
                offset = -cut.seam_allowance

            curve = flattended.flattened_cell.at_position(self.position)
            index = cut_result.get_inner_index(self.position.si)

            p1 = curve.get(curve.walk(index, offset.si * 0.25))
            p2 = curve.get(curve.walk(index, offset.si * 0.75))

            return [openglider.rs.vector.PolyLine2D([p1]), openglider.rs.vector.PolyLine2D([p2])]      

        return {
            panel_front: get_mark(panel_front, True),
            panel_back: get_mark(panel_back, False)
        }
    
    def get_mesh(self, cell: Cell, midribs: int) -> Mesh:
        data = self.get_data(cell, midribs)
        print(data)
        midrib = cell.midrib(self.position.si)
        nodes = [
            midrib.curve.get(data[1]),
            midrib.curve.get(data[2])
        ]
        print((nodes[1] - nodes[0]).length())

        return Mesh.from_indexed(nodes, {"EntryStrap": [((0, 1), {})]}, name="EntryStrap")

@dataclass
class PanelRigidFoil:
    x_start: Percentage
    x_end: Percentage
    y: Percentage = Percentage(0.5)
    channel_width: Length = Length("1cm")
    pocket_length: Length = Length("2cm")

    total_length: float | None = None

    def get_mesh(self, cell: Cell, midribs: int) -> Mesh:
        profile_3d = cell.midrib(self.y.si)
        nodes = profile_3d.curve.get(
            cell.rib1.profile_2d.get_ik(self.x_start.si),
            cell.rib1.profile_2d.get_ik(self.x_end.si)
        ).nodes

        return Mesh.from_indexed(nodes, {"PanelRigidFoil": [((i, i+1), {}) for i in range(len(nodes)-1)]}, name="PanelRigidFoil")

    def get_flattened(self, cell: Cell, midribs: int, cut_types: dict[PANELCUT_TYPES, type[cuts.Cut]] | None) -> tuple[drawing.Part, dict[Panel, list[openglider.rs.vector.PolyLine2D]]]:
        dwg = drawing.Part(material_code="rigidfoil")
        panels = list(sorted(cell.panels, key=lambda p: p.mean_x()))
        
        # check lengths for each panels
        # generate sections of connected panels with some off-panel section in between
        # for each section generate 
        flat_panels: dict[Panel, FlattenedPanel] = {}
        lines: dict[Panel, openglider.rs.vector.PolyLine2D] = {} # panel -> line
        profile_3d = cell.midrib(self.y.si)

        panel_marks: dict[Panel, list[openglider.rs.vector.PolyLine2D]] = {}

        for panel in panels:
            panel_flat = panel.get_flattened(cell, midribs=midribs, cut_types=cut_types)
            line = panel_flat.draw_straight_line(self.y, self.x_start, self.x_end)
            if line is not None:
                flat_panels[panel] = panel_flat
                lines[panel] = line
        
        current_section: list[Panel] = []
        current_section_offset = 0.

        def add_section(next_panel: Panel | None) -> None:
            nonlocal current_section_offset
            # get all panel line lengths
            lengths = [
                lines[panel].get_length() for panel in current_section
            ]
            total_length = sum(lengths)
            print(lengths)
            
            # start and end mark offset
            mark_offset_side = 0.01
            # distance between marks: nearest to 5cm but divides evenly
            distance_between = 0.05
            num_marks = math.ceil((total_length - 2*mark_offset_side) / distance_between)
            distance_between = (total_length - 2*mark_offset_side) / (num_marks + 1)
            
            # add lines
            for i in range(len(current_section)+1):
                x = current_section_offset + sum(lengths[:i])
                dwg.add_line(
                    "marks",
                    openglider.rs.vector.PolyLine2D([
                        openglider.rs.vector.Vector2D([x, -self.channel_width.si/2]),
                        openglider.rs.vector.Vector2D([x, self.channel_width.si/2]),
                    ]),
                )
            
            # add marks
            mark_positions = [
                mark_offset_side + i * distance_between for i in range(num_marks+1)
            ] + [total_length - mark_offset_side]
            mark_distance = 0.002 # 2mm

            for mark_position in mark_positions:
                dwg.add_line(
                    "L0",
                    openglider.rs.vector.PolyLine2D([openglider.rs.vector.Vector2D([current_section_offset + mark_position, -mark_distance])]),
                )
                dwg.add_line(
                    "L0",
                    openglider.rs.vector.PolyLine2D([openglider.rs.vector.Vector2D([current_section_offset + mark_position, mark_distance/2])]),
                )

            # add to panels
            for i, panel in enumerate(current_section):
                line = lines[panel]
                panel_start = sum(lengths[:i])
                panel_end = panel_start + lengths[i]
                panel_marks.setdefault(panel, [])
                panel_marks[panel] += [
                    line
                ]

                for mark_position in mark_positions:
                    if mark_position > panel_start and mark_position < panel_end:
                        p1 = line.get(line.walk(0, mark_position - panel_start))
                        p2 = line.offset(mark_distance/2).get(line.walk(0, mark_position - panel_start))
                        panel_marks[panel] += [
                            openglider.rs.vector.PolyLine2D([p2]),
                            openglider.rs.vector.PolyLine2D([p1 + (p1 - p2)])
                        ]



            current_section_offset += total_length

            if next_panel is not None:
                # add region without panel
                ik_1 = flat_panels[current_section[-1]].cut_back.get_inner_index(self.y.si)
                ik_2 = flat_panels[next_panel].cut_front.get_inner_index(self.y.si)

                current_section_offset += profile_3d.curve.get(ik_1, ik_2).get_length()




        for panel in panels:
            if panel in lines:
                if len(current_section) and current_section[-1].cut_back == panel.cut_front:
                    current_section.append(panel)
                else:
                    if len(current_section) > 0:
                        add_section(panel)
                    current_section = [panel]
        
        if current_section:
            add_section(None)

        # draw outline
        outline = openglider.rs.vector.PolyLine2D([
            openglider.rs.vector.Vector2D([-self.pocket_length.si, -self.channel_width.si/2]),
            openglider.rs.vector.Vector2D([current_section_offset + self.pocket_length.si, -self.channel_width.si/2]),
            openglider.rs.vector.Vector2D([current_section_offset + self.pocket_length.si, self.channel_width.si/2]),
            openglider.rs.vector.Vector2D([-self.pocket_length.si, self.channel_width.si/2]),
        ]).close()

        dwg.add_line("cuts", outline)

        self.total_length = current_section_offset

        return dwg, panel_marks
