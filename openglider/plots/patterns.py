import datetime
import logging
import openglider.rs
import string
import subprocess
from typing import Any, Iterable
from pathlib import Path

from openglider.glider.cell.diagonals import DiagonalRib, DiagonalSide
from openglider.glider.cell.panel import Panel
from openglider.glider.rib.rib import Rib
import openglider.plots.sketches
from openglider.glider.glider import Glider
from openglider.glider.project import GliderProject
from openglider.plots.config import PatternConfigOld
from openglider.plots.glider import PlotMaker
from openglider.plots.spreadsheets import get_glider_data, get_glider_data_internal
from openglider.plots.usage_stats import MaterialUsage
from openglider.utils.config import Config
from openglider.vector.text import Text
from openglider.rs import drawing

#import openglider.plots.sketches

logger = logging.getLogger(__name__)

class PatternsNew:
    plotmaker = PlotMaker
    config: PatternConfigOld

    DefaultConf = PlotMaker.DefaultConf

    def __init__(self, project: GliderProject, config: Config | None=None):
        self.config = self.DefaultConf(config)
        self.project = self.prepare_glider_project(project)


        self.glider_2d = self.project.glider
        self.logger = logging.getLogger(f"{self.__class__.__module__}.{self.__class__.__name__}")
        self.weight: dict[str, MaterialUsage] = {}

    def __json__(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "config": self.config
        }
    
    def prepare_glider_project(self, project: GliderProject) -> GliderProject:
        project = project.copy()
        if self.config.profile_numpoints is not None:
            project.glider.num_profile = self.config.profile_numpoints
        project.get_glider_3d(force=True)
        return project

    def _get_sketches(self) -> list[drawing.Layout]:
        import openglider.plots.sketches as sketch
        shapeplot = sketch.ShapePlot(self.project)
        design_upper = shapeplot.copy().draw_design(lower=True)
        design_upper.draw_cell_names()
        design_lower = shapeplot.copy().draw_design(lower=False)

        lineplan = shapeplot.copy()
        lineplan.draw_design(lower=True)
        lineplan.draw_attachment_points()
        lineplan.draw_rib_names()

        diagonals = sketch.ShapePlot(self.project)
        diagonals.draw_cells()
        diagonals.draw_attachment_points(add_text=False)
        diagonals.draw_diagonals()

        straps = sketch.ShapePlot(self.project)
        straps.draw_cells()
        straps.draw_attachment_points(add_text=False)
        straps.draw_straps()

        drawings: list[drawing.Layout] = [design_upper.drawing, design_lower.drawing, lineplan.drawing, diagonals.drawing, straps.drawing]

        def _layout_width(layout: drawing.Layout) -> float:
            bbox = layout.bbox()
            if bbox is None:
                return 0.0
            min_x, _, max_x, _ = bbox
            return max_x - min_x

        drawings_width = max([_layout_width(dwg) for dwg in drawings], default=0.0)

        # put name and date inside the patterns
        p1 = openglider.rs.vector.Vector2D([0., 0.])
        p2 = openglider.rs.vector.Vector2D([drawings_width, 0.])

        def get_text(content: str, valign: int) -> drawing.Part:
            text = drawing.Text(content, p1, p2, valign=valign)
            plotpart = drawing.Part()
            plotpart.add_text("text", text)
            return plotpart

        text_name = get_text(self.project.name or "unnamed", valign=1)
        date_str = datetime.datetime.now().strftime("%d.%m.%Y")
        text_date = get_text(date_str, valign=0)

        drawings += [
            drawing.Layout([p]) for p in [text_date, text_name]
        ]

        return drawings
    
    def _get_plotfile(self) -> drawing.Layout:
        if self.config.complete_glider:
            glider = self.project.get_glider_3d().copy_complete()
            glider.rename_parts()
        else:
            glider = self.project.get_glider_3d()
        

        plots = self.plotmaker(glider, config=self.config)
        glider.lineset.iterate_target_length()
            
        plots.unwrap()
        self.weight = plots.weight
        all_patterns = self._legacy_to_rs_layout(plots.get_all_grouped())

        return all_patterns

    @staticmethod
    def _legacy_to_rs_layout(layout: Any) -> drawing.Layout:
        if isinstance(layout, drawing.Layout):
            return layout

        rs_parts: list[drawing.Part] = []

        for legacy_part in layout.parts:
            rs_layers: dict[str, drawing.Layer] = {}
            for layer_name, legacy_layer in legacy_part.layers.items():
                style = drawing.LayerStyle(
                    stroke=legacy_layer.stroke,
                    stroke_width=legacy_layer.stroke_width,
                    visible=legacy_layer.visible,
                )
                rs_layers[layer_name] = drawing.Layer(lines=list(legacy_layer), style=style)

            rs_parts.append(
                drawing.Part(
                    layers=rs_layers,
                    name=legacy_part.name,
                    material_code=legacy_part.material_code,
                )
            )

        return drawing.Layout(rs_parts)

    def unwrap(self, outdir: Path | str) -> None:
        if not isinstance(outdir, Path):
            outdir = Path(outdir)

        subprocess.call(f"mkdir -p {outdir}", shell=True)

        self.logger.info("create sketches")
        drawings = self._get_sketches()
        designs = drawing.Layout.stack_column(drawings, self.config.patterns_align_dist_y)

        self.logger.info("create plots")
        all_patterns = self._get_plotfile()
        all_patterns.append_left(designs, distance=self.config.patterns_align_dist_x*2)

        all_patterns = all_patterns.scale(1000)
        all_patterns.export_dxf(str(outdir / "plots_all.dxf"))

        sketches = openglider.plots.sketches.get_all_plots(self.project)

        for sketch_name, sketch in sketches.items():
            sketch.export_a4(outdir / f"{sketch_name}.pdf")

        self.logger.info("create spreadsheets")
        self.project.get_glider_3d().lineset.rename_lines()
        excel = get_glider_data(self.project, consumption=self.weight)
        excel_internal = get_glider_data_internal(self.project)
        excel.saveas(str(outdir / f"{self.project.name}_production.ods"))
        excel_internal.saveas(str(outdir / f"{self.project.name}_internal.ods"))


class Patterns(PatternsNew):
    """
    Patterns suitable for manual cutting
    """
    
    def prepare_glider_project(self, project: GliderProject) -> GliderProject:
        new_project = super().prepare_glider_project(project)

        glider_3d = new_project.get_glider_3d()
        self.set_names_straps(glider_3d)
        self.set_names_panels(glider_3d)

        return new_project

    @staticmethod
    def set_names_panels(glider: Glider) -> None:
        for cell_no, cell in enumerate(glider.cells):
            upper = [panel for panel in cell.panels if not panel.is_lower()]
            lower = [panel for panel in cell.panels if panel.is_lower()]

            def sort_func(panel: Panel) -> float:
                return abs(panel.mean_x())

            upper.sort(key=sort_func)
            lower.sort(key=sort_func)

            def panel_char(index: int) -> str:
                return string.ascii_uppercase[index]

            for panel_no, panel in enumerate(upper):
                panel.name = f"T-{cell_no+1}{panel_char(panel_no)}R"
            for panel_no, panel in enumerate(lower):
                panel.name = f"B-{cell_no+1}{panel_char(panel_no)}L"

    @staticmethod
    def set_names_straps(glider: Glider) -> None:
        logger.warn("rename")
        curves = glider.get_attachment_point_layers()

        for cell_no, cell in enumerate(glider.cells):
            cell_layers: list[tuple[str, float]] = []
            for curve_name, curve in curves.items():
                if curve.nodes[-1][0] > cell_no:
                    cell_layers.append((curve_name, curve.get_value(cell_no)))


            cell_layers.sort(key=lambda el: el[1])
            
            layers_between: dict[str, int] = {}
            
            def get_name(position: DiagonalSide, rib: Rib) -> str:
                name = "-"
                
                for layer_name, pct in cell_layers:
                    if abs(position.end_x(rib).si) >= pct:
                        name = layer_name
                    
                layers_between.setdefault(name, 0)
                layers_between[name] += 1

                return f"{name}{layers_between[name]}"
            
            def rename_straps(straps: Iterable[DiagonalRib], prefix: str = "") -> None:
                straps = list(straps)
                straps.sort(key=lambda strap: abs(strap.get_average_x()))
                for strap in straps:
                    strap_side = strap.side1
                    rib = cell.rib1
                    if (not strap.is_lower or not strap.is_upper) and strap.side2.is_lower:
                            strap_side = strap.side2
                            rib = cell.rib2

                    strap.name = f"{prefix}{cell_no+1}{get_name(strap_side, rib)}"

            rename_straps(filter(lambda strap: strap.is_lower, cell.straps), "B")
            layers_between = {}
            rename_straps(filter(lambda strap: not strap.is_lower, cell.straps), "T")
            layers_between = {}
            rename_straps(cell.diagonals[:], "D")
