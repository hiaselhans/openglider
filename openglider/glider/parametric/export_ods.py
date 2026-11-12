from __future__ import annotations

import math
from typing import TYPE_CHECKING

import openglider.rs
from openglider.airfoil.generators.parsec import ParsecAirfoil

from openglider.glider.parametric.arc import ExplicitArc, LeparaglidingArc
from openglider.glider.parametric.shape import ParametricShape, LeparaglidingShape
from openglider.glider.shape import Shape
from openglider.glider.parametric.table.winglet import get_winglet_sheet
from openglider.glider.parametric.table.ballooning import BallooningTable
from openglider.utils.table import Table
from openglider.utils.types import CurveType

if TYPE_CHECKING:
    from openglider.glider.parametric import ParametricGlider
    from openglider.glider.project import GliderProject

file_version = "V4"
WIDTH_SKIP_TABLES = {"Cell Elements", "Rib Elements"}
WIDTH_SKIP_ROWS = {1, 2}

def export_ods_project(glider: GliderProject, filename: str) -> None:
    document = Table.build_ods_document(
        get_project_tables(glider),
        skip_width_rows=WIDTH_SKIP_ROWS,
        skip_width_rows_for_tables=WIDTH_SKIP_TABLES,
    )
    glider.glider.texture.embed_svg_in_document(document.document)
    document.saveas(filename)


def get_split_tables(project: GliderProject) -> list[Table]:
    tables = []
    tables.append(get_changelog_table(project))
    tables.append(get_geom_sheet(project.glider))
    tables.append(get_parametric_sheet(project.glider))
    if project.glider.texture.has_texture():
        tables.append(project.glider.texture.get_table())
    tables.append(get_airfoil_sheet(project.glider))
    tables.append(BallooningTable.from_list(project.glider.balloonings).table)
    
    tables += project.glider.tables.get_all_tables()

    tables.append(project.glider.config.get_table())
    tables.append(project.glider.allowances.get_table())

    return tables


def get_project_tables(project: GliderProject) -> list[Table]:
    tables = get_glider_tables(project.glider)
    changelog_table = get_changelog_table(project)

    tables.append(changelog_table)

    return tables

def get_changelog_table(project: GliderProject) -> Table:
    changelog_table = Table(name="Changelog")
    changelog_table["A1"] = "Date/Time"
    changelog_table["B1"] = "Modification"
    changelog_table["C1"] = "Description"

    for i, change in enumerate(project.changelog):
        dt, name, description = change
        
        changelog_table[i+1, 0] = dt.isoformat()
        changelog_table[i+1, 1] = name
        changelog_table[i+1, 2] = description
    
    return changelog_table



def get_glider_tables(glider: ParametricGlider) -> list[Table]:
    tables = []

    tables.append(get_geom_sheet(glider))

    cell_sheet = glider.tables.get_cell_sheet()
    rib_sheet = glider.tables.get_rib_sheet()

    tables.append(cell_sheet)
    tables.append(rib_sheet)
    tables.append(get_airfoil_sheet(glider))
    tables.append(BallooningTable.from_list(glider.balloonings).table)
    tables.append(get_parametric_sheet(glider))
    if glider.texture.has_texture():
        tables.append(glider.texture.get_table())
    tables.append(get_lines_sheet(glider))
    tables.append(glider.config.get_table())
    tables.append(glider.allowances.get_table())

    tables.append(glider.tables.curves.table)

    # the winglet goes in the same file, in one sheet
    if glider.winglet is not None:
        tables.append(get_winglet_sheet(glider.winglet))

    return tables


def export_ods_2d(glider: ParametricGlider, filename: str) -> None:
    # airfoil sheet
    tables = get_glider_tables(glider)
    document = Table.build_ods_document(
        tables,
        skip_width_rows=WIDTH_SKIP_ROWS,
        skip_width_rows_for_tables=WIDTH_SKIP_TABLES,
    )
    glider.texture.embed_svg_in_document(document.document)
    document.saveas(filename)


def get_airfoil_sheet(glider_2d: ParametricGlider) -> Table:
    profiles = glider_2d.profiles
    table = Table(name="Airfoils")

    for i, profile in enumerate(profiles):
        col = 2 * i
        name = profile.name or "unnamed"
        parsec_model = profile.parsec_data
        is_parsec = parsec_model is not None

        row = 0
        table[row, col] = "name"
        table[row, col + 1] = name
        row += 1

        table[row, col] = "airfoil_typ"
        table[row, col + 1] = "parsec" if is_parsec else "points"
        row += 1

        if is_parsec:
            table[row, col] = "numpoints"
            table[row, col + 1] = int(parsec_model.numpoints)
            row += 1

            parameters = parsec_model.get_parameters()
            for key, value in parameters.items():
                table[row, col] = key
                table[row, col + 1] = float(value)
                row += 1

        table[row, col] = "x"
        table[row, col + 1] = "y"
        row += 1

        for p in profile.curve:
            table[row, col] = p[0]
            table[row, col + 1] = p[1]
            row += 1

    return table


def get_geom_sheet(glider_2d: ParametricGlider) -> Table:
    table = Table(name="geometry")

    # rib_nos
    table[0, 0] = "Ribs"
  
    center_cell = glider_2d.shape.has_center_cell

    ribs = glider_2d.shape.ribs
    chords = glider_2d.shape.chords
    rib_x_values = glider_2d.shape.rib_x_values

    table[0, 1] = "Chord"
    for i, chord in enumerate(chords[center_cell:]):
        table[i+1, 1] = chord

    table[0, 2] = "Le x (m)"
    table[0, 3] = "Le y (m)"
    for i, (front, back) in enumerate(ribs[center_cell:]):
        table[i+1, 2] = front[0]
        table[i+1, 3] = -front[1]

    # set arc values
    table[0, 4] = "Arc"
    last_angle = 0.
    cell_angles = glider_2d.arc.get_cell_angles(rib_x_values)
    if center_cell:
        cell_angles = cell_angles[1:]
    for i, angle in enumerate(cell_angles + [cell_angles[-1]]):
        this_angle = angle * 180/math.pi

        table[i+1, 4] = this_angle-last_angle
        last_angle = this_angle

    table[0, 5] = "AOA"
    table[0, 6] = "Z-rotation"
    table[0, 7] = "Y-rotation"
    table[0, 8] = "profile-merge"
    table[0, 9] = "ballooning-merge"

    def interpolation(curve: CurveType) -> openglider.rs.vector.Interpolation:
        return openglider.rs.vector.Interpolation(curve.get_sequence(100).nodes)

    aoa_int = interpolation(glider_2d.aoa)
    profile_int = interpolation(glider_2d.profile_merge_curve)
    ballooning_int = interpolation(glider_2d.ballooning_merge_curve)

    for rib_no, x in enumerate(glider_2d.shape.rib_x_values[center_cell:]):
        table[rib_no+1, 0] = rib_no+1
        table[rib_no+1, 5] = aoa_int.get_value(x)*180/math.pi
        table[rib_no+1, 6] = 0
        table[rib_no+1, 7] = 0
        table[rib_no+1, 8] = profile_int.get_value(x)
        table[rib_no+1, 9] = ballooning_int.get_value(x)
    
    if not isinstance(glider_2d.shape, Shape) and glider_2d.shape.config.has_stabicell:
        table = table.get_rows(0, table.num_rows-1)

    return table


def _shape_param_rows(params: dict) -> list[tuple[str, object]]:
    """Flatten leparagliding shape params into readable key/value rows.

    No ``mode`` row: the column's "leparagliding" type already implies it (there
    is only one shape mode), unlike the arc column which needs it to distinguish
    vault_ellipse from vault_circles.
    """
    le = params.get("leading_edge", {})
    te = params.get("trailing_edge", {})
    rows: list[tuple[str, object]] = []
    for k in ("a1", "b1", "x1", "x2", "xm", "c01", "ex1", "c02", "ex2"):
        rows.append((f"le_{k}", le.get(k, 0.0)))
    for k in ("a1", "b1", "x1", "c0", "y0", "exp"):
        rows.append((f"te_{k}", te.get(k, 0.0)))
    return rows


def _arc_param_rows(params: dict) -> list[tuple[str, object]]:
    """Flatten arc generator params into key/value rows (lists -> csv)."""
    rows: list[tuple[str, object]] = [("mode", params.get("mode", ""))]
    for key, value in params.items():
        if key == "mode":
            continue
        if isinstance(value, list):
            rows.append((key, ",".join(str(v) for v in value)))
        else:
            rows.append((key, value))
    return rows


def get_parametric_sheet(glider : ParametricGlider) -> Table:
    table = Table(name="Parametric")
    shape = glider.shape
    arc = glider.arc

    def add_curve(name: str, curve: CurveType, column_no: int) -> None:
        #sheet.append_columns(2)
        table[0, column_no] = name
        table[0, column_no+1] = type(curve).__name__
        for i, p in enumerate(curve.controlpoints):
            table[i+1, column_no] = p[0]
            table[i+1, column_no+1] = p[1]

    def add_leparagliding(name: str, rows: list[tuple[str, object]], column_no: int) -> None:
        # A "leparagliding" column stores parameter key/value rows instead of
        # control points; the curve is regenerated from these on import.
        table[0, column_no] = name
        table[0, column_no+1] = "leparagliding"
        for i, (key, value) in enumerate(rows):
            table[i+1, column_no] = key
            table[i+1, column_no+1] = value

    def add_explicit_points(name: str, points: list[list[float]], column_no: int) -> None:
        # "explicit" column with raw [x, y] rows.
        table[0, column_no] = name
        table[0, column_no+1] = "explicit"
        for i, p in enumerate(points):
            table[i+1, column_no] = p[0]
            table[i+1, column_no+1] = p[1]

    def add_explicit_values(name: str, values: list[float], column_no: int) -> None:
        # "explicit" column with a single value per row (col+1 empty).
        table[0, column_no] = name
        table[0, column_no+1] = "explicit"
        for i, v in enumerate(values):
            table[i+1, column_no] = v

    # ── planform (front/back) ──
    if isinstance(shape, LeparaglidingShape):
        # front carries all the planform params; back is an empty marker.
        add_leparagliding("front", _shape_param_rows(shape.params.to_dict()), 0)
        table[0, 2] = "back"
        table[0, 3] = "leparagliding"
    elif isinstance(shape, ParametricShape):
        add_curve("front", shape.front_curve, 0)
        add_curve("back", shape.back_curve, 2)
    else:
        raise ValueError(f"Unknown shape type: {type(shape)}")

    # ── rib distribution ──
    # Cell distribution is independent from spline/Leparagliding planform mode.
    if shape.cell_widths is not None:
        add_explicit_values("rib_distribution", list(shape.cell_widths), 4)
    else:
        add_curve("rib_distribution", shape.rib_distribution, 4)

    # ── arc ──
    if isinstance(arc, LeparaglidingArc):
        add_leparagliding("arc", _arc_param_rows({"mode": arc.mode, **arc.params}), 6)
    elif isinstance(arc, ExplicitArc):
        add_explicit_values("arc", list(arc.cell_angles), 6)
    else:
        add_curve("arc", arc.curve, 6)

    add_curve("aoa", glider.aoa, 8)
    add_curve("ballooning_merge_curve", glider.ballooning_merge_curve, 10)
    add_curve("profile_merge_curve", glider.profile_merge_curve, 12)

    return table


def get_lines_sheet(glider: ParametricGlider, places: int=3) -> Table:
    table = glider.tables.lines.table
    table.name = "Lines"
    
    return table

# for i, value in enumerate(("Ribs", "Chord", "x: (m)", "y LE (m)", "kruemmung", "aoa", "Z-rotation",
#                      "Y-Rotation-Offset", "merge", "balooning")):
#         geom_page.get_cell((0, i)).value = value
#
#     ribs = glider.ribs()
#     x = [rib[0][0] for rib in ribs]
#     y = [rib[0][1] for rib in ribs]
#     chord = [rib[0][1] - rib[1][1] for rib in ribs]
