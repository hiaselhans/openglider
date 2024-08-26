import datetime
import logging
import euklid
import string
import subprocess
from typing import Any
from pathlib import Path

import openglider.glider
from openglider.glider.cell.diagonals import DiagonalRib, DiagonalSide
from openglider.glider.cell.panel import Panel
from openglider.glider.rib.rib import Rib
import openglider.plots.cuts
import openglider.plots.marks
import openglider.plots.spreadsheets
import openglider.plots.sketches
from openglider.glider.glider import Glider
from openglider.glider.project import GliderProject
from openglider.plots.config import PatternConfigOld
from openglider.plots.glider import PlotMaker
from openglider.plots.spreadsheets import get_glider_data
from openglider.plots.usage_stats import MaterialUsage
from openglider.utils.config import Config
from openglider.vector.drawing import Layout
from openglider.vector.text import Text

#import openglider.plots.sketches

logger = logging.getLogger(__name__)

class PatternsNew:
    plotmaker = PlotMaker
    config: PatternConfigOld

    DefaultConf = PlotMaker.DefaultConf

    def __init__(self, project: GliderProject, config: Config | None=None):
        self.project = self.prepare_glider_project(project)
        self.config = self.DefaultConf(config)


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
        return project

    def _get_sketches(self) -> list[Layout]:
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

        drawings: list[Layout] = [design_upper.drawing, design_lower.drawing, lineplan.drawing, diagonals.drawing, straps.drawing]

        drawings_width = max([dwg.width for dwg in drawings])

        # put name and date inside the patterns
        p1 = euklid.vector.Vector2D([0., 0.])
        p2 = euklid.vector.Vector2D([drawings_width, 0.])
        text_name = Text(self.project.name or "unnamed", p1, p2, valign=1)
        date_str = datetime.datetime.now().strftime("%d.%m.%Y")
        text_date = Text(date_str, p1, p2, valign=0)
        drawings += [Layout([x]) for x in [text_date.get_plotpart(), text_name.get_plotpart()]]

        return drawings
    
    def _get_plotfile(self) -> Layout:
        if self.config.complete_glider:
            glider = self.project.get_glider_3d().copy_complete()
            glider.rename_parts()
        else:
            glider = self.project.get_glider_3d()
        

        plots = self.plotmaker(glider, config=self.config)
        glider.lineset.iterate_target_length()
            
        plots.unwrap()
        self.weight = plots.weight
        all_patterns = plots.get_all_grouped()

        return all_patterns

    def unwrap(self, outdir: Path | str) -> None:
        if not isinstance(outdir, Path):
            outdir = Path(outdir)
        if self.config.profile_numpoints is not None:
            self.project.glider.num_profile = self.config.profile_numpoints
            self.project.glider_3d = self.project.glider.get_glider_3d()
            self.project = self.prepare_glider_project(self.project)

        subprocess.call(f"mkdir -p {outdir}", shell=True)

        self.logger.info("create sketches")
        drawings = self._get_sketches()
        designs = Layout.stack_column(drawings, self.config.patterns_align_dist_y)

        self.logger.info("create plots")
        all_patterns = self._get_plotfile()
        all_patterns.append_left(designs, distance=self.config.patterns_align_dist_x*2)

        all_patterns.scale(1000)
        all_patterns.export_dxf(outdir / "plots_all.dxf")

        sketches = openglider.plots.sketches.get_all_plots(self.project)

        for sketch_name, sketch in sketches.items():
            fill = False
            if sketch_name in ("design_upper", "design_lower"):
                fill=True

            sketch.export_a4(outdir / f"{sketch_name}.pdf", fill=fill)

        self.logger.info("create spreadsheets")
        self.project.get_glider_3d().lineset.rename_lines()
        excel = get_glider_data(self.project, consumption=self.weight)
        excel.saveas(outdir / f"{self.project.name}.ods")

        openglider.save(self.project, outdir / "project.json")


class Patterns(PatternsNew):
    """
    Patterns suitable for manual cutting
    """
    
    def prepare_glider_project(self, project: GliderProject) -> GliderProject:
        new_project: GliderProject = project.copy()
        glider = new_project.get_glider_3d()

        self.set_names_straps(glider)
        self.set_names_panels(glider)

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
            
            def rename_straps(straps: list[DiagonalRib], prefix: str = ""):
                straps = list(straps)
                straps.sort(key=lambda strap: abs(strap.get_average_x()))
                for strap in straps:
                    strap.name = f"{prefix}{cell_no+1}{get_name(strap.side1, cell.rib1)}"

            rename_straps(filter(lambda strap: strap.is_lower, cell.straps), "B")
            rename_straps(filter(lambda strap: not strap.is_lower, cell.straps), "T")
            rename_straps(cell.diagonals[:], "D")
