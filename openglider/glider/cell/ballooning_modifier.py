from __future__ import annotations

from abc import ABC
import math
from typing import TYPE_CHECKING

import euklid

from openglider.glider.ballooning.base import BallooningBase
from openglider.glider.ballooning.new import BallooningNew
from openglider.utils.dataclass import BaseModel
from openglider.vector.unit import Length, Percentage

if TYPE_CHECKING:
    from openglider.glider.cell.cell import Cell

class BallooningModifier(BaseModel, ABC):
    def apply(self, ballooning: BallooningBase, cell: Cell) -> BallooningBase:
        raise NotImplementedError()


class BallooningRamp(BallooningModifier):
    position: Percentage
    distance: Percentage | Length

    def apply(self, ballooning: BallooningBase, cell: Cell) -> BallooningBase:
        def y(x: euklid.vector.Vector2D) -> euklid.vector.Vector2D:
            distance = abs(x[0]-self.position.si)
            y_new = x[1]

            if distance <= self.distance.si:
                y_new *= -(math.cos(distance / self.distance.si * math.pi) - 1) / 2
            
                return euklid.vector.Vector2D([x[0], y_new])
            
            return x

        return BallooningNew(euklid.vector.Interpolation([y(x) for x in ballooning]), ballooning.name)
    
class EntryRamp(BallooningModifier):
    ramp_distance: Percentage | Length

    def apply(self, ballooning: BallooningBase, cell: Cell) -> BallooningBase:
        panels = cell.get_connected_panels()

        cuts = set[float]()
        for panel_no, panel in enumerate(panels):
            x1 = max([panel.cut_front.x_left.si, panel.cut_front.x_right.si])
            x2 = min([panel.cut_back.x_left.si, panel.cut_back.x_right.si])

            if panel_no > 0:
                cuts.add(x1)
            if panel_no < len(panels) - 1:
                cuts.add(x2)

        all_cuts = list(cuts)
        
        for start, end in zip(all_cuts[::2], all_cuts[1::2]):
            ballooning = BallooningFixed(start=Percentage(start), end=Percentage(end), ramp_distance=self.ramp_distance).apply(ballooning, cell)
        
        return ballooning

class BallooningFixed(BallooningModifier):
    start: Percentage
    end: Percentage
    ramp_distance: Percentage | Length
    amount: float = 0
    
    def apply(self, ballooning: BallooningBase, cell: Cell) -> BallooningBase:
        def scale(distance: float, vector: euklid.vector.Vector2D) -> euklid.vector.Vector2D:
            factor = -0.5 * (math.cos(distance / self.ramp_distance.si * math.pi) - 1)
            return euklid.vector.Vector2D((
                vector[0],
                vector[1] * factor + (1-factor) * self.amount
            ))
        
        def y(vec: euklid.vector.Vector2D) -> euklid.vector.Vector2D:
            x = vec[0]
            if x > self.start - self.ramp_distance and x < self.start:
                return scale(self.start.si - x, vec)
            elif x < self.end + self.ramp_distance and x > self.end:
                return scale(x - self.end.si, vec)
            elif x < self.end and x > self.start:
                return euklid.vector.Vector2D([x, self.amount])
            return vec

        return BallooningNew(euklid.vector.Interpolation([y(x) for x in ballooning]), ballooning.name)
