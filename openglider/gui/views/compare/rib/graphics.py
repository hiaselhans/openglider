import logging

from openglider.utils.colors import Color
from openglider.glider.project import GliderProject
from openglider.gui.views_2d.canvas import RsLayoutGraphics
from openglider.gui.views.compare.rib.settings import RibPlotLayers
from openglider.plots.glider.ribs import RibPlot
from openglider.rs import drawing


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
    cache: dict[int, drawing.Layout]

    def __init__(self, project: GliderProject, color: Color) -> None:
        self.project = project
        self.color = color
        self.cache = {}
        self.config = RibPlotLayers()
        
    def get(self, rib_no: int, config: RibPlotLayers) -> RsLayoutGraphics:
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
                dwg = drawing.Layout()
                part = drawing.Part()

                for layer_name in plot.plotpart.layers.keys():
                    layer_src = plot.plotpart.layers[layer_name]
                    with part.layer(layer_name) as layer_dst:
                        layer_dst.style.stroke = f"#{self.color.hex()}"
                        layer_dst.style.visible = layer_src.visible
                        layer_dst.style.stroke_width = layer_src.stroke_width
                        if layer_src.stroke:
                            layer_dst.style.stroke = layer_src.stroke
                        for polyline in layer_src:
                            layer_dst.add_line(polyline)

                dwg.add_part(part)
            else:
                dwg = drawing.Layout()
            
            self.cache[rib_no] = dwg
        
        return RsLayoutGraphics(self.cache[rib_no])

