import numbers
from typing import Any, ClassVar, Self
import euklid

from openglider.glider.ballooning.base import BallooningBase
from openglider.glider.ballooning.new import BallooningBezierNeu
from openglider.glider.ballooning.old import BallooningBezier
from openglider.utils.dataclass import BaseModel
from openglider.utils.table import Table

def transpose_columns(sheet: Table, columnswidth: int=2) -> list[tuple[str, Any]]:
    num_columns = sheet.num_columns
    num_elems = num_columns // columnswidth
    # if num % columnswidth > 0:
    #    raise ValueError("irregular columnswidth")
    result = []
    for col in range(num_elems):
        first_column = col * columnswidth
        last_column = (col + 1) * columnswidth
        columns = range(first_column, last_column)
        name = sheet[0, first_column]
        if not isinstance(name, numbers.Number):  # py2/3: str!=unicode
            start = 1
        else:
            name = "unnamed"
            start = 0

        element = []

        for i in range(start, sheet.num_rows):
            row = [sheet[i, j] for j in columns]
            if all([j is None for j in row]):  # Break at empty line
                break
            if not all([isinstance(j, numbers.Number) for j in row]):
                raise ValueError(f"Invalid value at row {i}: {row}")
            element.append(row)
        result.append((name, element))
    return result


class BallooningTable(BaseModel):
    table_name: ClassVar[str] = "Balloonings"
    table: Table

    def get(self) -> list[BallooningBase]:
        balloonings: list[BallooningBase] = []
        for i, (name, baloon) in enumerate(transpose_columns(self.table)):
            ballooning_type = (self.table[0, 2*i+1] or "").upper()
            if baloon:
                if ballooning_type == "V1":
                    i = 0
                    while baloon[i + 1][0] > baloon[i][0]:
                        i += 1

                    upper = [euklid.vector.Vector2D(p) for p in baloon[:i + 1]]
                    lower = [euklid.vector.Vector2D([x, -y]) for x, y in baloon[i + 1:]]

                    ballooning = BallooningBezier(upper, lower, name=name)
                    balloonings.append(BallooningBezierNeu.from_classic(ballooning))

                elif ballooning_type == "V2":
                    i = 0
                    while baloon[i + 1][0] > baloon[i][0]:
                        i += 1

                    upper = baloon[:i + 1]
                    lower = baloon[i + 1:]

                    ballooning = BallooningBezier(upper, lower, name=name)
                    balloonings.append(BallooningBezierNeu.from_classic(ballooning))

                elif ballooning_type == "V3":
                    balloonings.append(BallooningBezierNeu(baloon))

                else:
                    raise ValueError("No ballooning type specified")
        
        return balloonings
    
    @classmethod
    def from_list(cls, balloonings: list[BallooningBase]) -> Self:
        table = Table(name=cls.table_name)
        #row_num = max([len(b.upper_spline.controlpoints)+len(b.lower_spline.controlpoints) for b in balloonings])+1
        #sheet = ezodf.Sheet(name="Balloonings", size=(row_num, 2*len(balloonings)))

        for ballooning_no, ballooning in enumerate(balloonings):
            
            #sheet.append_columns(2)
            table[0, 2*ballooning_no] = f"ballooning_{ballooning_no}"
            if isinstance(ballooning, BallooningBezierNeu):
                table[0, 2*ballooning_no+1] = "V3"
                pts = list(ballooning.controlpoints)
            elif isinstance(ballooning, BallooningBezier):
                table[0, 2*ballooning_no+1] = "V2"
                pts = list(ballooning.upper_spline.controlpoints) + list(ballooning.lower_spline.controlpoints)
            else:
                raise ValueError("Wrong ballooning type")

            for i, point in enumerate(pts):
                table[i+1, 2*ballooning_no] = point[0]
                table[i+1, 2*ballooning_no+1] = point[1]

        return cls(table=table)