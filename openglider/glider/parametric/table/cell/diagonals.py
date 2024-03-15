from typing import Any
from openglider.glider.cell.diagonals import DiagonalRib, DiagonalSide, TensionLine, TensionStrap
from openglider.glider.parametric.table.base import CellTable
from openglider.glider.parametric.table.base.dto import DTO, CellTuple

import logging

from openglider.vector.unit import Length, Percentage

logger = logging.getLogger(__name__)

class QRDTO(DTO):
    position: CellTuple[Percentage]
    width: CellTuple[Percentage | Length]
    height: CellTuple[Percentage]

    def get_object(self) -> DiagonalRib:
        left_side = DiagonalSide(center=self.position.first, width=self.width.first, height=self.height.first.si)
        right_side = DiagonalSide(center=self.position.second, width=self.width.second, height=self.height.second.si)

        return DiagonalRib(left=left_side, right=right_side)
    
class DiagonalDTO(QRDTO):
    material_code: str

    def get_object(self) -> DiagonalRib:
        diagonal = super().get_object()
        diagonal.material_code = self.material_code

        return diagonal
    
class DiagonalWithHolesDTO(DiagonalDTO):

    num_folds: int
    num_holes: int
    hole_border_side: float
    hole_border_front_back: float

    def get_object(self) -> DiagonalRib:
        diagonal = super().get_object()
        diagonal.num_folds = self.num_folds
        diagonal.hole_num = self.num_holes
        diagonal.hole_border_side = self.hole_border_side
        diagonal.hole_border_front_back= self.hole_border_front_back

        return diagonal

class FingerDiagonal(DTO):
    lower_position: Percentage
    lower_width: Percentage | Length

    upper_start: Percentage
    upper_end: Percentage

    fingers: int
    direction_up: bool
    material_code: str
    curve_factor: Percentage

    def get_object(self) -> list[DiagonalRib]:
        assert self.fingers > 0

        lower_side = DiagonalSide(center=self.lower_position, width=self.lower_width, height=-1)
        upper_width = (self.upper_end - self.upper_start) / self.fingers

        upper_sides = [
            DiagonalSide(
                center=self.upper_start + (i+0.5) * upper_width,
                width=upper_width,    
                height=1.
                )
            for i in range(self.fingers)
        ]
        ribs = []

        for upper in upper_sides:
            if self.direction_up:
                ribs.append(
                    DiagonalRib(
                        left=lower_side,
                        right=upper,
                        material_code=self.material_code,
                        num_folds=0,
                        curve_factor=self.curve_factor
                    )
                )
            else:
                ribs.append(
                    DiagonalRib(
                        left=upper,
                        right=lower_side,
                        material_code=self.material_code,
                        num_folds=0,
                        curve_factor=self.curve_factor
                    )
                )
        
        return ribs

class StrapDTO(DTO):
    position: CellTuple[Percentage]
    width: Percentage | Length

    def get_object(self) -> TensionStrap:
        return TensionStrap(self.position.first, self.position.second, self.width)
    
class Strap3DTO(StrapDTO):
    num_folds: int

    def get_object(self) -> TensionStrap:
        result = super().get_object()
        result.num_folds = self.num_folds

        return result

class CurvedStrap(StrapDTO):
    curve_factor: Percentage

    def get_object(self) -> TensionStrap:
        result = super().get_object()
        result.curve_factor = self.curve_factor
        result.num_folds = 0
        return result


class TensionLineDTO(DTO):
    position: CellTuple[Percentage]

    def get_object(self) -> TensionLine:
        return TensionLine(self.position.first, self.position.second)

class DiagonalTable(CellTable):
    dtos = {
        "QR": QRDTO,
        "DIAGONAL": DiagonalDTO,
        "DiagonalWithHoles": DiagonalWithHolesDTO,
        "FingerDiagonal": FingerDiagonal
    }

    def get(self, row_no: int, keywords: list[str] | None = None, **kwargs: Any) -> list:
        result = super().get(row_no, keywords, **kwargs)
        new_result = []

        for x in result:
            if isinstance(x, list):
                new_result += x
            else:
                new_result.append(x)

        return new_result

class StrapTable(CellTable):
    dtos = {
        "STRAP": StrapDTO,
        "STRAP3": Strap3DTO,
        "VEKTLAENGE": TensionLineDTO,
        "CurvedStrap": CurvedStrap
    }
