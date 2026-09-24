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

    @staticmethod
    def _layout_bbox(layout: drawing.Layout) -> tuple[float, float, float, float]:
        return layout.bbox() or (0.0, 1.0, 0.0, 1.0)

    @classmethod
    def _layout_width_height(cls, layout: drawing.Layout) -> tuple[float, float]:
        min_x, max_x, min_y, max_y = cls._layout_bbox(layout)
        return max(max_x - min_x, 0.0), max(max_y - min_y, 0.0)

    @classmethod
    def _stack_column_rs(cls, layouts: list[drawing.Layout], distance: float) -> drawing.Layout:
        if not layouts:
            return drawing.Layout()

        widths = [cls._layout_width_height(layout)[0] for layout in layouts]
        max_width = max(widths) if widths else 0.0
        result = drawing.Layout()
        y = 0.0
        direction = (distance >= 0) - (distance < 0)

        for layout, width in zip(layouts, widths):
            moved = layout.copy()
            min_x, max_x, min_y, max_y = cls._layout_bbox(moved)
            x_offset = (max_width - width) / 2.0 - min_x
            y_offset = y - min_y
            moved = moved.move(openglider.rs.vector.Vector2D([x_offset, y_offset]))

            for part in moved.parts:
                result.add_part(part)

            _, height = cls._layout_width_height(moved)
            y += direction * height
            y += distance

        return result

    @classmethod
    def _append_left_rs(cls, base: drawing.Layout, left: drawing.Layout, distance: float) -> drawing.Layout:
        base_bbox = cls._layout_bbox(base)
        left_bbox = cls._layout_bbox(left)

        left_width = max(left_bbox[1] - left_bbox[0], 0.0)
        x_offset = base_bbox[0] - left_bbox[0] - left_width - distance
        y_offset = base_bbox[2] - left_bbox[2]

        moved_left = left.move(openglider.rs.vector.Vector2D([x_offset, y_offset]))
        combined = base.copy()
        for part in moved_left.parts:
            combined.add_part(part)

        return combined

    @staticmethod
    def _legacy_to_rs_layout(legacy_layout: Any) -> drawing.Layout:
        rs_layout = drawing.Layout()
        default_config = getattr(legacy_layout, "layer_config", {}).get("*", {})

        for legacy_part in legacy_layout.parts:
            rs_part = drawing.Part(name=getattr(legacy_part, "name", None), material_code=getattr(legacy_part, "material_code", ""))

            for layer_name, legacy_layer in legacy_part.layers.items():
                layer_config = getattr(legacy_layout, "layer_config", {}).get(layer_name, default_config)

                with rs_part.layer(layer_name) as rs_layer:
                    stroke = layer_config.get("stroke-color") or getattr(legacy_layer, "stroke", None)
                    rs_layer.style.stroke = stroke if isinstance(stroke, str) else None

                    stroke_width = layer_config.get("stroke-width", getattr(legacy_layer, "stroke_width", 0.25))
                    try:
                        rs_layer.style.stroke_width = float(stroke_width)
                    except (TypeError, ValueError):
                        rs_layer.style.stroke_width = 0.25

                    fill = layer_config.get("fill")
                    if isinstance(fill, str) and fill.lower() != "none":
                        rs_layer.style.fill = fill
                    else:
                        rs_layer.style.fill = None

                    visible = layer_config.get("visible", getattr(legacy_layer, "visible", True))
                    rs_layer.style.visible = bool(visible)

                    for polyline in legacy_layer:
                        rs_layer.add_line(polyline)

            rs_layout.add_part(rs_part)

        return rs_layout

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

        drawings_width = max([self._layout_width_height(dwg)[0] for dwg in drawings] + [1.0])

        # put name and date inside the patterns
        p1 = openglider.rs.vector.Vector2D([0., 0.])
        p2 = openglider.rs.vector.Vector2D([drawings_width, 0.])
        text_name = drawing.Text(self.project.name or "unnamed", p1, p2, valign=1)
        date_str = datetime.datetime.now().strftime("%d.%m.%Y")
        text_date = drawing.Text(date_str, p1, p2, valign=0)

        for text in (text_date, text_name):
            text_layout = drawing.Layout()
            text_part = drawing.Part()
            with text_part.layer("text") as layer:
                layer.add_text(text)
            text_layout.add_part(text_part)
            drawings.append(text_layout)

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
        grouped = plots.get_all_grouped()
        if isinstance(grouped, drawing.Layout):
            return grouped
        return self._legacy_to_rs_layout(grouped)

    def unwrap(self, outdir: Path | str) -> None:
        if not isinstance(outdir, Path):
            outdir = Path(outdir)

        subprocess.call(f"mkdir -p {outdir}", shell=True)

        self.logger.info("create sketches")
        drawings = self._get_sketches()
        designs = self._stack_column_rs(drawings, self.config.patterns_align_dist_y)

        self.logger.info("create plots")
        all_patterns = self._get_plotfile()
        all_patterns = self._append_left_rs(all_patterns, designs, distance=self.config.patterns_align_dist_x*2)

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
