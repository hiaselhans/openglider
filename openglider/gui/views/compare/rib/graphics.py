import logging

from openglider.utils.colors import Color
from openglider.glider.project import GliderProject
from openglider.gui.views_2d.canvas import LayoutGraphics
from openglider.gui.views.compare.rib.settings import RibPlotLayers
from openglider.plots.glider.ribs import RibPlot
from openglider.vector.drawing import Layout


logger = logging.getLogger(__name__)



class RibPlotWithLayers(RibPlot):
    layer_name_outline = "outline"
    layer_name_crossports = "crossports"
    layer_name_marks = "marks"
    layer_name_rigidfoils = "rigidfoils"
    layer_name_sewing = "sewing"
    layer_name_text = "text"
    layer_name_laser_dots = "laser"


class GliderRibPlots:
    project: GliderProject
    config: RibPlotLayers
    color: Color
    cache: dict[int, Layout]

    def __init__(self, project: GliderProject, color: Color) -> None:
        self.project = project
        self.color = color
        self.cache = {}
        self.config = RibPlotLayers()
        
    def get(self, rib_no: int, config: RibPlotLayers) -> LayoutGraphics:
        if config != self.config:
            self.cache = {}
            self.config = config.copy()

        if rib_no not in self.cache:
            glider = self.project.get_glider_3d()
            if rib_no < len(glider.ribs):
                rib = glider.ribs[rib_no]
                plot = RibPlotWithLayers(rib)
                plot.flatten(glider, add_rigidfoils_to_plot=False)
                for layer_name in config.__annotations__.keys():
                    if not getattr(config, layer_name) and layer_name in plot.plotpart.layers:
                        plot.plotpart.layers.pop(layer_name)
                
                plot.plotpart.scale(1/rib.chord)
                dwg = Layout([plot.plotpart])
                dwg.layer_config = {
                    "*":  {
                        "id": 'outer',
                        "stroke-width": "0.25",
                        "stroke": "red",
                        "stroke-color": f"#{self.color.hex()}",
                        "fill": "none"
                        }
                }
            else:
                dwg = Layout()
            
            self.cache[rib_no] = dwg
        
        return LayoutGraphics(self.cache[rib_no])

