import re
from typing import Any

from openglider.glider.parametric.table.base import ElementTable, Keyword, TableType
from openglider.materials import cloth, Material

import logging

logger = logging.getLogger(__name__)

re_variable = re.compile(r".*(\$\w+)")


class CellClothTable(ElementTable):
    table_type = TableType.cell
    keywords = {
        "MATERIAL": Keyword([("Name", str)], target_cls=Material)
    }

    def get_element(self, row: int, keyword: str, data: list[Any], **kwargs: Any) -> tuple[Material, str | None] | None:
        try:
            color_groups = kwargs["color_groups"]
        except KeyError:
            logger.error(f"Missing 'color_groups' in kwargs (available keys: {list(kwargs.keys())})")
            color_groups = {}

        name = data[0]

        if name == "empty":
            return None
        else:
            cloth_name = data[0]
            color_group: str | None = None

            if match := re_variable.match(cloth_name):
                color_group = match.group(1)[1:]  # remove the '$' character
                try:
                    replacement = color_groups[color_group]
                except KeyError:
                    raise ValueError(f"color group '{color_group}' not found")
                cloth_name = cloth_name.replace(match.group(1), replacement)
                
            return cloth.get(cloth_name), color_group


class RibClothTable(CellClothTable):
    table_type = TableType.rib
