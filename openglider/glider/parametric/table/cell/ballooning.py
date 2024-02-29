import logging

from openglider.glider.parametric.table.base import CellTable, Keyword
from openglider.glider.parametric.table.base.dto import DTO
from openglider.glider.parametric.table.base.parser import Parser
from openglider.glider.cell.ballooning_modifier import BallooningModifier, EntryRamp
from openglider.vector.unit import Percentage

logger = logging.getLogger(__name__)


class BallooningRampDTO(DTO):
    ramp_distance: Percentage

    def get_object(self) -> EntryRamp:
        return EntryRamp(ramp_distance=self.ramp_distance)


class BallooningModifierTable(CellTable):
    keywords: dict[str, Keyword] = {
        "BallooningFactor": Keyword(attributes=["amount_factor"]),
        "BallooningMerge": Keyword(attributes=["merge_factor"]),
    }
    dtos = {
        "BallooningRamp": BallooningRampDTO,
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
    
    def get_modifiers(self, row: int, resolvers: list[Parser]) -> list[BallooningModifier]:
        return self.get(row_no=row, keywords=["BallooningRamp"], resolvers=resolvers)




