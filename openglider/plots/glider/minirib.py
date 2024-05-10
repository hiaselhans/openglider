from __future__ import annotations

from typing import TYPE_CHECKING

import euklid
from openglider import logging
from openglider.plots.config import PatternConfig
from openglider.utils.config import Config
from openglider.vector.drawing import PlotPart
from openglider.vector.text import Text
from openglider.vector.unit import Percentage
from openglider.glider.rib import MiniRib
from openglider.plots.usage_stats import MaterialUsage
from openglider.materials import cloth



if TYPE_CHECKING:
    from openglider.glider.cell import Cell


Vector2D = euklid.vector.Vector2D

logger = logging.getLogger(__name__)


class MiniRibPlot:
    minirib: MiniRib
    cell: Cell

    config: PatternConfig
    DefaultConf = PatternConfig

    layer_name_outline = "cuts"
    layer_name_sewing = "sewing"
    layer_name_rigidfoils = "marks"
    layer_name_text = "text"
    layer_name_marks = "marks"
    layer_name_laser_dots = "L0"
    layer_name_crossports = "cuts"


    outer_curve: euklid.vector.PolyLine2D | None = None
    

    def __init__(self, minirib: MiniRib, cell :Cell, config: Config | None=None) -> None:
        self.minirib = minirib
        #self.ribplot = ribplot
        self.cell = cell
        self.config = self.DefaultConf(config)


    def get_point(self, x: float | Percentage, y: float=-1.) -> euklid.vector.Vector2D:
        x = float(x)
        assert x >= 0

        profile = self.minirib.get_profile_3d(self.cell).flatten()

        p = profile.profilepoint(x, y)


        print("...")
        print(p)
        print("...")

        p_temp = list(p)

        p_temp[0] = p_temp[0] * profile.curve.nodes[0][0]

        return euklid.vector.Vector2D(p_temp)


    def add_text(self, plotpart: PlotPart) -> None:
        
        posX = self.minirib.front_cut

        p1 = self.get_point(posX, 1)
        p2 = self.get_point(posX, -1)

        p1 = (p1+p2)/2
        p2 = p1 +euklid.vector.Vector2D([0.02,-0.005])

        print(p1)
        print(p2)

        _text = Text(self.minirib.name, p1, p2, size=0.01, align="center", valign=0)


        plotpart.layers[self.layer_name_text] += _text.get_vectors()

    
    def draw_outline(self) -> euklid.vector.PolyLine2D:
        """
        get 2d line
        """
        outer_minirib = self.outer.fix_errors()
        inner_minirib = self.inner
        t_e_allowance = self.cell.panels[-1].cut_back.seam_allowance.si
        p1 = inner_minirib.nodes[0] + euklid.vector.Vector2D([0, 1])
        p2 = inner_minirib.nodes[0] + euklid.vector.Vector2D([0, -1])


        p3 = euklid.vector.Vector2D([min(x[0] for x in inner_minirib.tolist()), max(x[1] for x in inner_minirib.tolist())]) # probably there is a euklid function for that,... 
        p4 = euklid.vector.Vector2D([min(x[0] for x in inner_minirib.tolist()), min(x[1] for x in inner_minirib.tolist())])

        cuts = outer_minirib.cut(p1, p2)

        front_cuts = outer_minirib.cut(p3, p4)

        if len(cuts) != 2:
            raise Exception("could not cut minirib airfoil TE")

        start = cuts[0][0]
        stop = cuts[1][0]

        middle_top = front_cuts[0][0]
        middle_bot = front_cuts[1][0]

        buerzl = [
            outer_minirib.get(stop),
            outer_minirib.get(stop) + euklid.vector.Vector2D([t_e_allowance, 0]),
            outer_minirib.get(start) + euklid.vector.Vector2D([t_e_allowance, 0]),
            outer_minirib.get(start)
            ]

        #no sewing allowance front
        nosew = [
            outer_minirib.get(middle_top),
            outer_minirib.get(middle_bot)
            ]

        contour = euklid.vector.PolyLine2D(
             outer_minirib.get(start, middle_top).nodes + nosew + outer_minirib.get(middle_bot, stop).nodes + buerzl
        )

        return contour
    
    def get_material_usage(self) -> MaterialUsage:
        dwg = self.plotpart

        curves = dwg.layers["cuts"].polylines
        usage = MaterialUsage()
        material = cloth.get(dwg.material_code)

        if curves:
            area = curves[0].get_area()

        #to do implement holes for miniribs--> check if its working!!
            for curve in self.minirib.get_holes(self.cell)[0]:
                area -= curve.get_area()      
            usage.consume(material, area)

        return usage
    
    def flatten(self) -> PlotPart:
        plotpart = PlotPart(material_code=self.minirib.material_code, name=self.minirib.name)

        nodes_top, nodes_bottom = self.minirib.get_nodes(self.cell)

        self.cell.get_flattened_cell()

        lengths = self.minirib._get_lengths(self.cell)
        nodes_top.scale(lengths[0] / nodes_top.get_length())
        nodes_bottom.scale(lengths[1] / nodes_bottom.get_length())
        
        self.inner = nodes_top + nodes_bottom
        self.outer = self.inner.offset(self.minirib.seam_allowance.si, simple=False)

        envelope = self.draw_outline()

        plotpart.layers[self.layer_name_sewing].append(self.inner)
                
        plotpart.layers[self.layer_name_outline].append(envelope)

        for curve in self.minirib.get_holes(self.cell)[0]:
            plotpart.layers["cuts"].append(curve)

        self.add_text(plotpart)

        self.plotpart = plotpart

        return plotpart