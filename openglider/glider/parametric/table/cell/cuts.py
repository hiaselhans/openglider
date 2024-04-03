import logging
from typing import Any
import typing

from openglider.glider.cell.panel import PANELCUT_TYPES, PanelCut
from openglider.glider.parametric.table.base import CellTable
from openglider.glider.parametric.table.base.dto import DTO, CellTuple
from openglider.vector.unit import Length, Percentage

logger = logging.getLogger(__name__)

class DesignCut(DTO):
    x: CellTuple[Percentage]
    _cut_type = PANELCUT_TYPES.orthogonal

    def get_object(self, seam_allowance: Length = Length(0)) -> PanelCut:
        return PanelCut(
            x_left=self.x.first,
            x_right=self.x.second,
            cut_type=self._cut_type,
            seam_allowance=seam_allowance
        )

class FoldedCut(DesignCut):
    _cut_type = PANELCUT_TYPES.folded

class Cut3D(DesignCut):
    _cut_type = PANELCUT_TYPES.cut_3d

class SingleSkinCut(DesignCut):
    _cut_type = PANELCUT_TYPES.singleskin

class CutRound(DesignCut):
    center: Percentage
    amount: Length
    _cut_type = PANELCUT_TYPES.round

    def get_object(self, seam_allowance: Length = Length(0)) -> PanelCut:
        cut = super().get_object()
        cut.x_center = self.center
        cut.seam_allowance = self.amount

        return cut

class CutTable(CellTable):
    dtos = {
        "DESIGNM": DesignCut,
        "DESIGNO": DesignCut,
        "orthogonal": DesignCut,

        "EKV": FoldedCut,
        "EKH": FoldedCut,
        "folded": FoldedCut,

        "CUT3D": Cut3D,
        "cut_3d": Cut3D,

        "singleskin": SingleSkinCut,
    }
    
    def get_element(self, row: int, keyword: str, data: list[typing.Any], allowance: Length | None = None, **kwargs: Any) -> PanelCut:
        if allowance is None:
            raise ValueError()
        
        if keyword in self.dtos:
            dto = self.dtos[keyword]

            assert issubclass(dto, DesignCut)

            dct = self._prepare_dto_data(row, dto, data, kwargs["resolvers"])
                
            return dto(**dct).get_object(seam_allowance=allowance)
        
        return super().get_element(row, keyword, data, **kwargs)
