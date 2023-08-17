from typing import Any
from openglider.glider.parametric.table.base import CellTable, Keyword

import logging

from openglider.glider.parametric.table.base.dto import DTO

from openglider.vector.unit import Percentage

logger = logging.getLogger(__name__)

class BallooningRamp(DTO):
    x: Percentage

    def get_object(self) -> float:
        return self.x.si

class BallooningTable(CellTable):
    keywords: dict[str, Keyword] = {
        "BallooningFactor": Keyword(attributes=["amount_factor"]),
        "BallooningMerge": Keyword(attributes=["merge_factor"])
    }
    dtos = {
        "BallooningRamp": BallooningRamp,
    }

    def get_merge_factors(self, factor_list: list[float]) -> list[tuple[float, float]]:

        merge_factors = factor_list[:]

        columns = self.get_columns(self.table, "BallooningMerge", 1)
        if len(columns):
            for i in range(len(merge_factors)):
                for column in columns:
                    value = column[i+2, 0]
                    if value is not None:
                        merge_factors[i] = value

        multipliers = [1] * len(merge_factors)
        columns = self.get_columns(self.table, "BallooningFactor", 1)

        for i in range(len(merge_factors)):
            for column in columns:
                value = column[i+2, 0]
                if value is not None:
                    multipliers[i] = value
        
        return list(zip(merge_factors, multipliers))
    
    def get_ballooning_ramp(self, row: int, **kwargs: Any) -> float | None:
        return self.get_one(row_no=row, keywords=["BallooningRamp"], **kwargs)
