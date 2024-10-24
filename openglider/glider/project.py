from __future__ import annotations

import euklid
import os
import re
import datetime
import logging
from typing import Any

from openglider.glider.glider import Glider
from openglider.glider.parametric import ParametricGlider
from openglider.glider.parametric.import_ods import import_ods_glider
from openglider.glider.parametric.import_freecad import import_freecad
from openglider.glider.parametric.export_ods import export_ods_project, get_split_tables
from openglider.utils.dataclass import dataclass, Field
import openglider.utils.table

logger = logging.getLogger(__name__)


@dataclass
class GliderProject:
    glider: ParametricGlider
    glider_3d: Glider | None = Field(default=None)
    filename: str | None=None
    name: str=""
    changelog: list[tuple[datetime.datetime, str, str]] = Field(default_factory=lambda: [])

    _regex_revision_no = re.compile(r"(.*)_rev([0-9]*)$")

    def __post_init__(self) -> None:
        if not self.name:
            if self.filename is not None:
                self.name = os.path.split(self.filename)[1]
            else:
                self.name = "unnamed_project"

        if self.glider_3d is None:
            logger.info(f"get glider 3d:  {self.name}")
            self.glider_3d = self.glider.get_glider_3d()

        if len(self.changelog) < 1:
            self.changelog.append((
                datetime.datetime.now(), "loaded", "no changelog data available"
            ))
    
    @classmethod
    def __from_json__(cls, **kwargs: Any) -> GliderProject:
        changelog = kwargs.get("changelog", [])
        changelog_new = []
        for dt_str, value1, value2 in changelog:
            dt = datetime.datetime.fromisoformat(dt_str)

            changelog_new.append((dt, value1, value2))

        kwargs["changelog"] = changelog_new

        return cls(**kwargs)
    
    def __hash__(self) -> int:
        return hash(self.modified.timestamp)

    @property
    def modified(self) -> datetime.datetime:
        return self.changelog[-1][0]

    def increase_revision_nr(self) -> str:
        match = self._regex_revision_no.match(self.name)

        if match:
            name = match.group(1)
            revision_nr = int(match.group(2))
        else:
            name = self.name
            revision_nr = 0

        revision_nr += 1

        self.name = f"{name}_rev{revision_nr:03d}"

        return self.name

    def get_data_table(self) -> openglider.utils.table.Table:
        assert self.glider_3d is not None

        table = openglider.utils.table.Table(name="glider specs")
        table["A1"] = "Name"
        table["B1"] = f"{self.name}"
        table["A2"] = "Modified"
        table["B2"] = self.modified.strftime("%d.%m.%Y")
        table["A3"] = "Time"
        table["B3"] = self.modified.strftime("%H:%M")
        table["A4"] = "Area"
        table["B4"] = f"{self.glider_3d.area:.02f} m²"
        table["A5"] = "Area projected"
        table["B5"] = f"{self.glider_3d.projected_area:.02f} m²"
        table["A6"] = "Aspect Ratio"
        table["B6"] = f"{self.glider_3d.aspect_ratio:.02f}"

        flattening = 100 * (1 - self.glider_3d.projected_area / self.glider_3d.area)
        table["A7"] = "Flattening"
        table["B7"] = f"{flattening:.01f} %"
        table["A8"] = "Cells"
        table["B8"] = str(self.glider.shape.cell_num)

        table["A9"] = "Attachment point x"
        table["A10"] = "Attachment point z"

        attachment_point = self.glider_3d.lineset.get_main_attachment_point().position
        table["B9"] = f"{attachment_point[0]:.03f}"
        table["B10"] = f"{attachment_point[2]:.03f}"

        table["A11"] = "Att. z (relative to span)"
        z_rel = attachment_point[2] / self.glider.shape.span * 100
        table["B11"] = f"{z_rel:.01f} %"

        rib = self.glider_3d.ribs[0]
        p0 = rib.align(euklid.vector.Vector2D([0, 0]))
        
        diff = attachment_point - p0
        rib_diff = rib.align(euklid.vector.Vector2D([1, 0]))-p0

        x_rel = diff.dot(rib_diff) / rib_diff.dot(rib_diff) * 100

        table["A12"] = "Att. x (relative to chord)"
        table["B12"] = f"{x_rel:.01f} %"

        table["A13"] = "Trailing edge Length"
        table["B13"] = f"{self.glider_3d.trailing_edge_length:.03f}"

        return table

    def as_markdown(self) -> str:
        tables = get_split_tables(self)
        data = f"# {self.name}"

        for table in tables:
            data += f"\n\n## {table.name}\n\n"

            data += table.get_markdown_table()

            data += "\n"
        
        return data


    def save(self, filename: str, keep_filename: bool=False) -> None:
        if filename.endswith(".ods"):
            export_ods_project(self, filename)
        elif filename.endswith(".json"):
            openglider.save(self, filename)
        elif filename.endswith(".og.md"):
            with open(filename, "w") as outfile:
                outfile.write(self.as_markdown())
        else:
            raise ValueError(f"Invalid Extension ({filename})")
        
        if not self.filename or not keep_filename:
            self.filename = filename

    def copy(self) -> GliderProject:
        new_glider = self.glider.copy()
        new_glider_3d = self.glider_3d and self.glider_3d.copy()
        new = GliderProject(new_glider, new_glider_3d, changelog=self.changelog[:])
        new.name = self.name

        return new

    @classmethod
    def import_ods(cls, path: str) -> GliderProject:
        tables = openglider.utils.table.Table.load(path)
        table_dct = {t.name: t for t in tables}
        changelog = []
        
        if "Changelog" in table_dct:
            changelog_table = table_dct["Changelog"]

            for row in range(1, changelog_table.num_rows):
                if changelog_table[row, 0]:
                    dt = datetime.datetime.fromisoformat(changelog_table[row, 0])

                    changelog.append((
                        dt, changelog_table[row, 1], changelog_table[row, 2]
                    ))

        glider_2d = import_ods_glider(ParametricGlider, tables)

        filename = os.path.split(path)[-1]
        name, ext = os.path.splitext(filename)
        return cls(glider_2d, name=name, changelog=changelog)
    
    @classmethod
    def import_freecad(cls, path: str) -> GliderProject:
        glider_2d = import_freecad(path)
        filename = os.path.split(path)[-1]
        name, ext = os.path.splitext(filename)
        return cls(glider_2d, name=name)

    def get_glider_3d(self) -> Glider:
        if self.glider_3d is None:
            self.glider_3d = self.glider.get_glider_3d()
        
        return self.glider_3d

    def update_all(self) -> None:
        self.glider.get_glider_3d(self.glider_3d)

    def get_data(self) -> dict[str, float]:
        area = self.get_glider_3d().area
        area_projected = self.get_glider_3d().projected_area
        return {
            "area": area,
            "area_projected": area_projected,
            "flattening": (1.-area_projected/area) * 100,
            "aspect_ratio": self.get_glider_3d().aspect_ratio
        }
