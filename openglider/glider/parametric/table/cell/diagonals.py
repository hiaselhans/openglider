from typing import Any
from openglider.glider.cell.diagonals import DiagonalRib, DiagonalSide, TensionLine, TensionStrap
from openglider.glider.parametric.table.base import CellTable
from openglider.glider.parametric.table.base.dto import DTO, CellTuple, SingleCellTuple

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

        return DiagonalRib(side1=left_side, side2=right_side)
    
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
    lower_position: SingleCellTuple[Percentage]
    lower_width: SingleCellTuple[Percentage | Length]

    upper_start: SingleCellTuple[Percentage]
    upper_end: SingleCellTuple[Percentage]

    fingers: int
    direction_up: bool
    material_code: str
    curve_factor: Percentage

    def get_object(self) -> list[DiagonalRib]:
        assert self.fingers > 0

        if self.direction_up:
            lower_index = 0
            upper_index = 1
        else:
            lower_index = 1
            upper_index = 0

        lower_side = DiagonalSide(center=self.lower_position[lower_index], width=self.lower_width[lower_index], height=-1)
        upper_width = (self.upper_end[upper_index] - self.upper_start[upper_index]) / self.fingers

        upper_sides = [
            DiagonalSide(
                center=self.upper_start[upper_index] + (i+0.5) * upper_width,
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
                        side1=lower_side,
                        side2=upper,
                        material_code=self.material_code,
                        num_folds=0,
                        curve_factor=self.curve_factor
                    )
                )
            else:
                ribs.append(
                    DiagonalRib(
                        side1=upper,
                        side2=lower_side,
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
        height = -1
        if (self.position.first + self.position.second).si < 0:
            self.position.first = -self.position.first
            self.position.second = -self.position.second
            height = 1
        return TensionStrap(self.position.first, self.position.second, self.width, height)
    
class Strap3DTO(StrapDTO):
    num_folds: int

    def get_object(self) -> TensionStrap:
        result = super().get_object()
        result.num_folds = self.num_folds

        return result

class Strap4DTO(Strap3DTO):
    material_code: str

    def get_object(self) -> TensionStrap:
        result = super().get_object()
        result.material_code = self.material_code

        return result

class CurvedStrap(StrapDTO):
    curve_factor: Percentage
    material_code: str

    def get_object(self) -> TensionStrap:
        result = super().get_object()
        result.curve_factor = self.curve_factor
        result.num_folds = 0
        result.material_code = self.material_code
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
        "STRAP4": Strap4DTO,
        "VEKTLAENGE": TensionLineDTO,
        "CurvedStrap": CurvedStrap
    }
