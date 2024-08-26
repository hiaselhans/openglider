from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import ezodf

from openglider.utils.table import Table
from openglider.lines.line_types.linetype import LineType
from openglider.plots.spreadsheets.rigidfoils import get_length_table as get_rigidfoils
from openglider.plots.spreadsheets.straps import get_length_table as get_straps
from openglider.plots.spreadsheets.material_list import get_material_sheets
from openglider.plots.usage_stats import MaterialUsage

if TYPE_CHECKING:
    from openglider.glider import GliderProject

def get_glider_data(project: GliderProject, consumption: dict[str, MaterialUsage]=None) -> ezodf.document.PackagedDocument:
    specsheet = project.get_data_table()
    glider = project.get_glider_3d()
    #specsheet = get_specs(glider)
    glider.lineset.recalc(glider=glider, iterations=30)
    linesheet = glider.lineset.get_table()
    linesheet2 = glider.lineset.get_table_2()
    
    checksheet = glider.lineset.get_checksheet()
    rigidfoils = get_rigidfoils(glider)
    straps = get_straps(glider)
    material_sheets = get_material_sheets(glider)

    consumption_table = Table(name="Material Consumption")
    consumption_table["B1"] = "Consumption"
    consumption_table["C1"] = "Weight"

    if consumption:
        for name, usage in consumption.items():
            header = Table()
            header[0, 0] = name
            consumption_table.append_bottom(header, space=1)
            consumption_table.append_bottom(usage.get_table())
    
    line_consumption_table = Table()
    line_consumption = glider.lineset.get_consumption()

    linetype: LineType
    row = 0
    for linetype in line_consumption:
        line_consumption_table[row, 0] = linetype.name
        line_consumption_table[row, 1] = round(line_consumption[linetype], 1)
        line_consumption_table[row, 2] = round(linetype.weight * line_consumption[linetype])
        
        row += 1
    
    consumption_table.append_bottom(line_consumption_table, space=1)

    out_ods = ezodf.newdoc(doctype="ods")
    def append_sheet(table: Table) -> None:
        now = datetime.now()
        header = Table(name=table.name)
        header["A1"] = table.name or "-"
        header["B1"] = "Plotfiles date"
        header["C1"] = now.strftime("%d.%m.%Y")
        header["D1"] = now.strftime("%H:%M")
        header["A2"] = project.name or "-"
        header["B2"] = "Modification date"
        header["C2"] = project.modified.strftime("%d.%m.%Y")
        header["D2"] = project.modified.strftime("%H:%M")
#
        header.append_bottom(table, space=1)
        out_ods.sheets.append(header.get_ods_sheet())

    sheets = (
        specsheet,
        linesheet,
        linesheet2,
        checksheet,
        rigidfoils,
        straps,
        consumption_table
    ) + material_sheets
    
    for sheet in sheets:
        append_sheet(sheet)

    return out_ods
