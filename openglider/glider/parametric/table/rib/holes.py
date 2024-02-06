from openglider.glider.parametric.table.base import RibTable
from openglider.glider.parametric.table.base.dto import DTO

from openglider.glider.rib.crossports import RibHole, RibSquareHole, MultiSquareHole, AttachmentPointHole
import logging

from openglider.vector.unit import Angle, Length, Percentage

logger = logging.getLogger(__name__)

class HoleDTO(DTO):
    pos: Percentage
    size: Percentage

    def get_object(self) -> RibHole:
        return RibHole(
            pos=self.pos,
            size=self.size
        )

class HoleSQDTO(DTO):
    x: Percentage
    width: Percentage
    height: Percentage

    def get_object(self) -> RibSquareHole:
        return RibSquareHole(
            x=self.x,
            width=self.width,
            height=self.height
        )

class Hole5DTO(HoleDTO):
    width: Percentage
    vertical_shift: Percentage
    rotation: Angle

    def get_object(self) -> RibHole:
        hole = super().get_object()
        hole.vertical_shift = self.vertical_shift
        hole.rotation = self.rotation
        hole.width = self.width

        return hole
    
class HoleSqMultiDTO(DTO):
    start: Percentage
    end: Percentage
    height: Percentage
    num_holes: int
    border_width: Percentage | Length

    def get_object(self) -> MultiSquareHole:
        return MultiSquareHole(
            start=self.start, end=self.end, height=self.height,
            num_holes=self.num_holes, border_width=self.border_width
        )

class HoleSqMulti6(HoleSqMultiDTO):
    margin: Percentage | Length

    def get_object(self) -> MultiSquareHole:
        hole = super().get_object()
        hole.margin = self.margin

        return hole

class HoleATP(DTO):
    start: Percentage
    end: Percentage
    num_holes: int

    def get_object(self) -> AttachmentPointHole:
        return AttachmentPointHole(
            **self.dict()
        )

class HOLEATP5(HoleATP):
    border: Length | Percentage
    border_side: Length | Percentage

class HOLEATP6(HOLEATP5):
    corner_size: Percentage

class HOLEATP7(HOLEATP5):
    border_diagonal: Length | Percentage
    corner_size: Percentage

class HOLEATP8(HOLEATP5):
    border_diagonal: Length | Percentage
    margin: Length | Percentage
    corner_size: Percentage

    def get_object(self) -> AttachmentPointHole:
        result = super().get_object()
        return result

class HOLEATP9(HOLEATP5):
    border_top: Length | Percentage
    border_diagonal: Length | Percentage
    margin: Length | Percentage
    corner_size: Percentage

    def get_object(self) -> AttachmentPointHole:
        result = super().get_object()
        return result

class HOLEATP10(HOLEATP9):
    top_triangle_factor: Percentage


class HolesTable(RibTable):
    dtos = {
        "HOLE": HoleDTO,
        "QUERLOCH": HoleDTO,
        "HOLESQ": HoleSQDTO,
        "HOLE5": Hole5DTO,
        "HOLESQMULTI": HoleSqMultiDTO,
        "HOLESQMULTI6": HoleSqMulti6,
        "HOLEATP": HoleATP,
        "HOLEATP5": HOLEATP5,
        "HOLEATP6": HOLEATP6,
        "HOLEATP7": HOLEATP7,
        "HOLEATP8": HOLEATP8,
        "HOLEATP9": HOLEATP9,
        "HOLEATP10": HOLEATP10
    }
