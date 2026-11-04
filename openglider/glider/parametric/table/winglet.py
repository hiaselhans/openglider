"""
The winglet of a glider in a single sheet of the glider's file, in sections one below the
other, each under a row naming it:

    == Placement ==     where it sits, its cell count, its angle
    == Shape ==         its planform (front, back, rib_distribution) and its profile and
                        ballooning curves, a column pair each as in the Parametric sheet
    == Ribs ==          profile modifiers, holes, rib cloth (as the Rib Elements sheet)
    == Cells ==         panel cloth (as the Cell Elements sheet)

Its airfoils and balloonings are in the Airfoils and Balloonings sheets of the glider, its
profile and ballooning curves (into them) in the Shape section.

Read back by splitting at these rows. A section ends at the next one, its empty rows and
columns at the end are left out: some sheets are read by their size.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from openglider.utils.table import Table

if TYPE_CHECKING:
    from openglider.glider.parametric.config import ParametricGliderConfig
    from openglider.glider.parametric.winglet import Winglet
    from openglider.utils.types import CurveType

WINGLET_SHEET = "Winglet"

_section = re.compile(r"^== (.+) ==$")


def pack_winglet_tables(tables: list[Table]) -> Table:
    sheet = Table(name=WINGLET_SHEET)

    for table in tables:
        start = sheet.num_rows + 1 if sheet.num_rows else 0
        sheet[start, 0] = f"== {table.name} =="
        sheet.append_bottom(table)

    return sheet


def _used_size(table: Table) -> tuple[int, int]:
    rows = columns = 0
    for key, value in table.dct.items():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        column, row = table.coords[key]
        rows = max(rows, row + 1)
        columns = max(columns, column + 1)
    return rows, columns


def unpack_winglet_table(sheet: Table) -> list[Table]:
    starts = []
    for row in range(sheet.num_rows):
        value = sheet[row, 0]
        match = _section.match(value.strip()) if isinstance(value, str) else None
        if match:
            starts.append((row, match.group(1)))

    tables = []
    for index, (row, name) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else sheet.num_rows
        section = sheet.get_rows(row + 1, end)
        rows, columns = _used_size(section)
        table = section.get_rows(0, rows).get_columns(0, columns)
        table.name = name
        tables.append(table)

    return tables


PLACEMENT = ("rib_position", "chord_start", "chord_end", "height", "angle")
CURVES = ("front", "back", "rib_distribution", "profile_merge_curve", "ballooning_merge_curve")


def _get_curves(winglet: Winglet) -> list[CurveType]:
    shape = winglet.shape
    return [shape.front_curve, shape.back_curve, shape.rib_distribution, winglet.profile_merge_curve, winglet.ballooning_merge_curve]


def get_winglet_sheet(winglet: Winglet) -> Table:
    placement = Table(name="Placement")
    for row, key in enumerate(PLACEMENT):
        placement[row, 0] = key
        placement[row, 1] = getattr(winglet, key)
    placement[len(PLACEMENT), 0] = "cell_num"
    placement[len(PLACEMENT), 1] = winglet.shape.cell_num

    # a column pair per curve: its name and type, then its controlpoints
    shape = Table(name="Shape")
    for index, (name, curve) in enumerate(zip(CURVES, _get_curves(winglet))):
        column = 2 * index
        shape[0, column] = name
        shape[0, column + 1] = type(curve).__name__
        for row, (x, y) in enumerate(curve.controlpoints.nodes):
            shape[row + 1, column] = x
            shape[row + 1, column + 1] = y

    tables = winglet.get_tables()
    ribs = tables.get_rib_sheet()
    ribs.name = "Ribs"
    cells = tables.get_cell_sheet()
    cells.name = "Cells"

    return pack_winglet_tables([placement, shape, ribs, cells])


def read_winglet_sheet(sections: list[Table], config: ParametricGliderConfig) -> Winglet:
    import openglider.rs
    from openglider.glider.parametric.shape import ParametricShape
    from openglider.glider.parametric.table.material import CellClothTable, RibClothTable
    from openglider.glider.parametric.table.rib.holes import HolesTable
    from openglider.glider.parametric.table.rib.profile import ProfileModifierTable
    from openglider.glider.parametric.winglet import Winglet, winglet_config

    by_name = {table.name: table for table in sections}

    placement = by_name["Placement"]
    values: dict[str, Any] = {}
    for row in range(placement.num_rows):
        if placement[row, 0] is not None:
            values[str(placement[row, 0])] = placement[row, 1]

    shape_table = by_name["Shape"]
    curves: dict[str, Any] = {}
    for column in range(0, shape_table.num_columns, 2):
        name, curve_type = shape_table[0, column], shape_table[0, column + 1]
        if name in CURVES:
            points = [
                [shape_table[row, column], shape_table[row, column + 1]]
                for row in range(1, shape_table.num_rows) if shape_table[row, column] is not None
            ]
            curves[name] = getattr(openglider.rs.spline, curve_type)(points)

    shape = ParametricShape(
        curves["front"], curves["back"], curves["rib_distribution"], int(values["cell_num"]),
        config=winglet_config(config),
    )
    ribs = by_name.get("Ribs", Table())
    cells = by_name.get("Cells", Table())

    return Winglet(
        shape=shape,
        profile_merge_curve=curves["profile_merge_curve"],
        ballooning_merge_curve=curves["ballooning_merge_curve"],
        profile_modifiers=ProfileModifierTable(ribs),
        holes=HolesTable(ribs),
        material_ribs=RibClothTable(ribs),
        material_cells=CellClothTable(cells),
        rib_position=float(values.get("rib_position", 4.5)),
        chord_start=float(values.get("chord_start", 0.25)),
        chord_end=float(values.get("chord_end", 0.75)),
        height=float(values.get("height", 0.3)),
        angle=float(values.get("angle", 0.) or 0.),
    )
