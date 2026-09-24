from __future__ import annotations

import dataclasses
import logging
import math
from typing import TYPE_CHECKING, Any, Literal, TypeAlias
from collections.abc import Callable

import openglider.rs
from openglider.glider.parametric.shape.leparagliding_shape import (
    LeadingEdgeParams,
    LeparaglidingShape,
    LeparaglidingShapeParams,
    TrailingEdgeParams,
)
from openglider.glider.parametric.shape import ParametricShape
from openglider.glider.project import GliderProject
from openglider.gui.qt import QtWidgets, QtCore
from openglider.gui.views_2d import Canvas, DraggableLine, Line2D
from openglider.gui.views_2d.canvas import RsLayoutGraphics
from openglider.gui.widgets import NumberInput
from openglider.gui.wizzards.base import GliderSelectionWizard
from openglider.plots.sketches.shapeplot import ShapePlot, ShapePlotConfig
from openglider.utils.colors import Color
from openglider.utils.dataclass import dataclass

if TYPE_CHECKING:
    from openglider.gui.app.main_window import MainWindow

logger = logging.getLogger(__name__)

EditableShape: TypeAlias = ParametricShape | LeparaglidingShape


def as_editable_shape(shape: object) -> EditableShape:
    if isinstance(shape, (ParametricShape, LeparaglidingShape)):
        return shape
    raise TypeError(f"Shape editor requires an editable planform, got {type(shape)}")


# TODO: Show & change data: Area, Aspect ratio, Span, Tip Chord, Tip center


class ShapeInput(Canvas):
    locked_aspect_ratio = True

    glider_shape: EditableShape
    on_change: list[Callable[[EditableShape], None]]
    glider_shapes: list[RsLayoutGraphics]

    def __init__(self, project: GliderProject):
        super().__init__(parent=None)
        self.on_change = []
        self.project = project
        self.glider_shape = as_editable_shape(project.glider.shape)
        spline_shape = self._spline_shape_for_controls()

        self.front = DraggableLine(spline_shape.front_curve.controlpoints.nodes)
        self.back = DraggableLine(spline_shape.back_curve.controlpoints.nodes)

        self.front.on_node_move.append(self.on_node_move)
        self.back.on_node_move.append(self.on_node_move)

        self.front.on_node_release.append(self.on_node_release)
        self.back.on_node_release.append(self.on_node_release)

        self.addItem(self.front)
        self.addItem(self.back)
        self.config = ShapePlotConfig()

        self.shape_drawing = ShapePlot(self.project)
        dwg = self.shape_drawing.redraw(self.config)
        self.glider_shape_2d = RsLayoutGraphics(dwg)

        #self.shape_drawing.redraw(self.config)
        #self.glider_shape_2d = Shape2D(self.glider_shape, [], (255, 255, 255), 160)

        self.glider_shapes = []
        self.addItem(self.glider_shape_2d)

        self._update_curves()
        self.redraw()

    def draw_shapes(self, shapes: list[tuple[GliderProject, Color]], clear: bool=True, normalize_area: bool=False, normalize_span: bool=False) -> None:
        # list of glider projects
        if clear:
            for shape in self.glider_shapes:
                self.removeItem(shape)
            self.glider_shapes = []

        area = self.glider_shape.area
        span = self.glider_shape.span


        if normalize_area:
            self.config.scale_area = area
        elif normalize_span:
            self.config.scale_span = span

        for project, color in shapes:
            drawing = ShapePlot(project).redraw(self.config)

            dwg_pyqt = RsLayoutGraphics(drawing, color=Color(*color))  #, color=color

            self.addItem(dwg_pyqt)
            self.glider_shapes.append(dwg_pyqt)

        self.update()

    def on_node_move(self, curve: DraggableLine, event: Any) -> None:
        node_index = curve.drag_node_index
        if node_index is None:
            return

        curve.data["pos"][node_index][0] = max(0, curve.data["pos"][node_index][0])

        if node_index + 1 == len(curve.controlpoints):
            source = curve
            if curve is self.front:
                target = self.back
            else:
                target = self.front

            target.data["pos"][-1][0] = source.data["pos"][node_index][0]
            target.updateGraph()

        self.redraw()

        for f in self.on_change:
            f(self.glider_shape)
        self.update()
    
    def redraw(self) -> None:
        if isinstance(self.glider_shape, ParametricShape):
            self.glider_shape.front_curve.controlpoints = self.front.controlpoints
            self.glider_shape.back_curve.controlpoints = self.back.controlpoints
            self.glider_shape.rescale_curves()

        self.removeItem(self.glider_shape_2d)
        self.glider_shape_2d = RsLayoutGraphics(self.shape_drawing.redraw(self.config, force=True))
        self.addItem(self.glider_shape_2d)


    def on_node_release(self, curve: DraggableLine, event: Any) -> None:
        self._update_curves()
        self.redraw()
        for f in self.on_change:
            f(self.glider_shape)
        self.update()
    
    def _spline_shape_for_controls(self) -> ParametricShape:
        if isinstance(self.glider_shape, ParametricShape):
            return self.glider_shape
        if isinstance(self.glider_shape, LeparaglidingShape):
            return ParametricShape.from_shape(self.glider_shape)
        raise TypeError(f"Shape editor requires a planform shape, got {type(self.glider_shape)}")

    def refresh_from_shape(self) -> None:
        spline_shape = self._spline_shape_for_controls()
        self.front.set_controlpoints(spline_shape.front_curve.controlpoints.nodes)
        self.back.set_controlpoints(spline_shape.back_curve.controlpoints.nodes)

    def _update_curves(self) -> None:
        if isinstance(self.glider_shape, ParametricShape):
            self.glider_shape._clean()
            self.refresh_from_shape()
        #self.update()
            

class RibDistInput(Canvas):
    shapes: list[Line2D]
    on_change: list[Callable]

    def __init__(self, shape: EditableShape):
        super().__init__()
        self.glider_shape = shape
        
        data = self.glider_shape.rib_distribution.get_sequence(100).nodes
        self.spline_curve = Line2D(data)
        self.addItem(self.spline_curve)

        self.curve = DraggableLine(self.glider_shape.rib_distribution.controlpoints.nodes)
        self.curve.on_node_move.append(self.on_node_move)
        self.curve.on_node_release.append(self.on_node_release)
        self.addItem(self.curve)

        self.linear = Line2D([
            openglider.rs.vector.Vector2D([0,0]),
            openglider.rs.vector.Vector2D([1, 1])
            ], dashed=True)
        self.addItem(self.linear)


        const_dist = openglider.rs.vector.PolyLine2D(self.glider_shape.depth_integrated)
        self.constant_ar = Line2D(const_dist.nodes, dashed=True)
        self.addItem(self.constant_ar)

        self.on_change = []
        self.shapes = []

    def draw_shapes(self, projects: list[tuple[GliderProject, Color]], clear: bool=True) -> None:
        # list of glider projects
        if clear:
            for shape in self.shapes:
                self.removeItem(shape)
            self.shapes = []

        for project, color in projects:
            if isinstance(project.glider.shape, ParametricShape):
                distribution = project.glider.shape.rib_distribution
                curve = Line2D(distribution.get_sequence(100).nodes, color=color)
                self.addItem(curve)
                self.shapes.append(curve)
            else:
                raise NotImplementedError("Rib distribution only implemented for parametric shapes (TODO!)")

        self.update()
    
    def on_node_move(self, curve: DraggableLine, event: Any) -> None:
        node_index = curve.drag_node_index

        curve.data["pos"][node_index][0] = max(0, curve.data["pos"][node_index][0])

        if node_index == len(curve.controlpoints) - 1:
            curve.data["pos"][node_index][0] = self.glider_shape.span / 2
            curve.data["pos"][node_index][1] = 1
        elif node_index == 0:
            curve.data["pos"][0] = [0, 0]
        
        self.glider_shape.rib_distribution.controlpoints = self.curve.controlpoints
        self.spline_curve.curve_data = self.glider_shape.rib_distribution.get_sequence(100).nodes

        for f in self.on_change:
            f(curve, event)

    def on_node_release(self, curve: DraggableLine, event: Any) -> None:
        pass

    def refresh_from_shape(self) -> None:
        """Refresh the distribution display after rib_distribution was replaced
        externally (e.g. by the parametric generator)."""
        self.curve.set_controlpoints(self.glider_shape.rib_distribution.controlpoints.nodes)
        self.spline_curve.curve_data = self.glider_shape.rib_distribution.get_sequence(100).nodes
        self.update()

    def set_handle_visible(self, visible: bool) -> None:
        self.curve.setVisible(visible)


@dataclass
class ShapeSettings:
    area: float
    aspect_ratio: float
    sweep: float
    cell_count: int
    scale: Literal["Area"] | Literal["Span"] | None = None
    zrot: bool = False
    scale_lines: bool = True

class ShapeSettingsWidget(QtWidgets.QWidget):
    changed = QtCore.Signal()
    def __init__(self, shape: EditableShape):
        super().__init__()
        layout = QtWidgets.QVBoxLayout()

        self.settings = ShapeSettings(
            area=shape.area,
            aspect_ratio=shape.aspect_ratio,
            sweep=shape.get_sweep(),
            cell_count=shape.cell_num
        )

        self.setLayout(layout)

        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)

        self.input_area = NumberInput(self, "Area", default=shape.area, places=2)
        self.input_aspect_ratio = NumberInput(self, "Aspect Ratio", default=shape.aspect_ratio, places=2)
        self.input_sweep = NumberInput(self, "Sweep", default=shape.get_sweep(), places=3)
        self.input_cell_count = NumberInput(self, "Cell Count", default=shape.cell_num, places=0)

        self.input_scale = QtWidgets.QComboBox(self)

        self.input_scale.insertItem(0, "No Scale")
        self.input_scale.insertItem(1, "Scale Area")
        self.input_scale.insertItem(2, "Scale Span")

        self.input_zrot = QtWidgets.QCheckBox()
        self.input_zrot.setText("Apply ZRot")
        self.input_zrot.setChecked(False)

        self.input_scale_lines = QtWidgets.QCheckBox()
        self.input_scale_lines.setText("Scale Lines")
        self.input_scale_lines.setChecked(self.settings.scale_lines)

        self.input_scale_lines.clicked.connect(self._update_settings)
        self.input_zrot.clicked.connect(self._update_settings)
        self.input_area.on_changed.append(self._update_settings)
        self.input_aspect_ratio.on_changed.append(self._update_settings)
        self.input_sweep.on_changed.append(self._update_settings)
        self.input_cell_count.on_changed.append(self._update_settings)

        layout.addWidget(self.input_area)
        layout.addWidget(self.input_aspect_ratio)
        layout.addWidget(self.input_sweep)
        layout.addWidget(self.input_cell_count)
        layout.addWidget(self.input_scale)
        layout.addWidget(self.input_zrot)
        layout.addWidget(self.input_scale_lines)

    def _update_settings(self, value: Any=None) -> None:
        self.settings.area = self.input_area.value
        self.settings.aspect_ratio = self.input_aspect_ratio.value
        self.settings.sweep = self.input_sweep.value
        self.settings.cell_count = int(self.input_cell_count.value)
        if self.normalize_area:
            self.settings.scale = "Area"
        elif self.normalize_span:
            self.settings.scale = "Span"
        else:
            self.settings.scale = None

        self.settings.zrot = self.input_zrot.isChecked()
        self.settings.scale_lines = self.input_scale_lines.isChecked()

        self.changed.emit()
    
    @property
    def normalize_area(self) -> bool:
        return self.input_scale.currentIndex() == 1
    
    @property
    def normalize_span(self) -> bool:
        return self.input_scale.currentIndex() == 2
    
    def update_zrot(self, value: bool=False) -> None:
        self.settings.zrot = not self.settings.zrot
        self.input_zrot.setChecked(self.settings.zrot)
        self.changed.emit()
    
    def update_shape(self, shape: EditableShape) -> None:
        self.input_area.set_value(shape.area, propagate=True)
        self.input_aspect_ratio.set_value(shape.aspect_ratio, propagate=True)
        self.input_sweep.set_value(shape.get_sweep(), propagate=True)


class LeparaglidingPanel(QtWidgets.QGroupBox):
    """Leparagliding pre-processor parameters for the leading/trailing edges.

    Each value change rebuilds the front/back curves from the analytical
    formulas in ``pre-processor.f``. Inputs use the same
    parameter names and units as the FORTRAN ``pre-data.txt``, so values can be
    copied verbatim from a leparagliding design.
    """

    params_changed = QtCore.Signal()

    def __init__(self, project: GliderProject):
        super().__init__("Leparagliding parameters")
        self.project = project
        self._updating = False

        wrapper = QtWidgets.QVBoxLayout(self)
        wrapper.setContentsMargins(4, 4, 4, 4)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        wrapper.addWidget(scroll)

        content = QtWidgets.QWidget()
        scroll.setWidget(content)
        outer = QtWidgets.QVBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)

        header_row = QtWidgets.QHBoxLayout()
        info = QtWidgets.QLabel("LE/TE ellipse parameters from leparagliding pre-processor v1.6")
        info.setStyleSheet("color: gray; font-size: 10px;")
        info.setWordWrap(True)
        header_row.addWidget(info, stretch=1)
        reset_btn = QtWidgets.QPushButton("Reset to defaults")
        reset_btn.clicked.connect(self._reset_defaults)
        header_row.addWidget(reset_btn)
        outer.addLayout(header_row)

        # ── Leading edge group ──
        le_group = QtWidgets.QGroupBox("Leading edge (Type 1)")
        le_form = QtWidgets.QFormLayout(le_group)
        le_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.le_a1 = self._make_spin(710.21, 0.0, 99999.0, 4)
        self.le_b1 = self._make_spin(243.11, 0.0, 99999.0, 4)
        self.le_x1 = self._make_spin(375.0, 0.0, 99999.0, 4)
        self.le_x2 = self._make_spin(475.0, 0.0, 99999.0, 4)
        self.le_xm = self._make_spin(575.5, 0.001, 99999.0, 4)
        self.le_c01 = self._make_spin(48.30, -9999.0, 9999.0, 4)
        self.le_ex1 = self._make_spin(2.0, 0.1, 20.0, 3)
        self.le_c02 = self._make_spin(0.0, -9999.0, 9999.0, 4)
        self.le_ex2 = self._make_spin(2.0, 0.1, 20.0, 3)
        le_form.addRow("a1 (horiz semi-axis):", self.le_a1)
        le_form.addRow("b1 (vert semi-axis):", self.le_b1)
        le_form.addRow("x1 (corr 1 start):", self.le_x1)
        le_form.addRow("x2 (corr 2 start):", self.le_x2)
        le_form.addRow("xm (half span):", self.le_xm)
        le_form.addRow("c01 (corr 1 amp):", self.le_c01)
        le_form.addRow("ex1 (corr 1 exp):", self.le_ex1)
        le_form.addRow("c02 (corr 2 amp):", self.le_c02)
        le_form.addRow("ex2 (corr 2 exp):", self.le_ex2)
        outer.addWidget(le_group)

        # ── Trailing edge group ──
        te_group = QtWidgets.QGroupBox("Trailing edge (Type 1)")
        te_form = QtWidgets.QFormLayout(te_group)
        te_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.te_a1 = self._make_spin(903.01, 0.0, 99999.0, 4)
        self.te_b1 = self._make_spin(243.11, 0.0, 99999.0, 4)
        self.te_x1 = self._make_spin(372.50, 0.0, 99999.0, 4)
        self.te_c0 = self._make_spin(-2.45, -9999.0, 9999.0, 4)
        self.te_y0 = self._make_spin(215.20, -9999.0, 9999.0, 4)
        self.te_exp = self._make_spin(2.0, 0.1, 20.0, 3)
        te_form.addRow("a1 (horiz semi-axis):", self.te_a1)
        te_form.addRow("b1 (vert semi-axis):", self.te_b1)
        te_form.addRow("x1 (corr start):", self.te_x1)
        te_form.addRow("c0 (corr amp):", self.te_c0)
        te_form.addRow("y0 (vert offset):", self.te_y0)
        te_form.addRow("exp (corr exp):", self.te_exp)
        outer.addWidget(te_group)

        outer.addStretch()

        self._restore_from_shape()

    def _make_spin(self, default: float, lo: float, hi: float, decimals: int) -> QtWidgets.QDoubleSpinBox:
        sb = QtWidgets.QDoubleSpinBox()
        sb.setRange(lo, hi)
        sb.setDecimals(decimals)
        sb.setSingleStep(10 ** (-min(decimals, 3)))
        sb.setValue(default)
        sb.setMinimumWidth(90)
        sb.setMinimumHeight(22)
        sb.valueChanged.connect(self._on_value_changed)
        return sb

    def _restore_from_shape(self) -> None:
        """Populate widget values from shape's leparagliding params (if any)."""
        shape = self.project.glider.shape
        if not isinstance(shape, LeparaglidingShape):
            return
        params = shape.params
        self._updating = True
        le = params.leading_edge
        te = params.trailing_edge
        self.le_a1.setValue(le.a1)
        self.le_b1.setValue(le.b1)
        self.le_x1.setValue(le.x1)
        self.le_x2.setValue(le.x2)
        self.le_xm.setValue(le.xm)
        self.le_c01.setValue(le.c01)
        self.le_ex1.setValue(le.ex1)
        self.le_c02.setValue(le.c02)
        self.le_ex2.setValue(le.ex2)
        self.te_a1.setValue(te.a1)
        self.te_b1.setValue(te.b1)
        self.te_x1.setValue(te.x1)
        self.te_c0.setValue(te.c0)
        self.te_y0.setValue(te.y0)
        self.te_exp.setValue(te.exp)
        self._updating = False

    def _reset_defaults(self) -> None:
        self._updating = True
        defaults = LeparaglidingShapeParams()
        le = defaults.leading_edge
        te = defaults.trailing_edge
        self.le_a1.setValue(le.a1)
        self.le_b1.setValue(le.b1)
        self.le_x1.setValue(le.x1)
        self.le_x2.setValue(le.x2)
        self.le_xm.setValue(le.xm)
        self.le_c01.setValue(le.c01)
        self.le_ex1.setValue(le.ex1)
        self.le_c02.setValue(le.c02)
        self.le_ex2.setValue(le.ex2)
        self.te_a1.setValue(te.a1)
        self.te_b1.setValue(te.b1)
        self.te_x1.setValue(te.x1)
        self.te_c0.setValue(te.c0)
        self.te_y0.setValue(te.y0)
        self.te_exp.setValue(te.exp)
        self._updating = False
        self._on_value_changed()

    def collect_params(self) -> LeparaglidingShapeParams:
        return LeparaglidingShapeParams(
            leading_edge=LeadingEdgeParams(
                a1=self.le_a1.value(),
                b1=self.le_b1.value(),
                x1=self.le_x1.value(),
                x2=self.le_x2.value(),
                xm=self.le_xm.value(),
                c01=self.le_c01.value(),
                ex1=self.le_ex1.value(),
                c02=self.le_c02.value(),
                ex2=self.le_ex2.value(),
            ),
            trailing_edge=TrailingEdgeParams(
                a1=self.te_a1.value(),
                b1=self.te_b1.value(),
                x1=self.te_x1.value(),
                xm=self.le_xm.value(),
                c0=self.te_c0.value(),
                y0=self.te_y0.value(),
                exp=self.te_exp.value(),
            ),
        )

    def _on_value_changed(self) -> None:
        if self._updating:
            return
        self.params_changed.emit()


class CellWidthSlidersPanel(QtWidgets.QWidget):
    """Row of vertical sliders + spinboxes — one per half-cell, centre to tip.

    Each slider controls a cell-width coefficient (0.1–3.0); 1.0 = equal width.
    Ported from openglider_lines.
    """

    widths_changed = QtCore.Signal()
    SLIDER_SCALE = 100

    def __init__(self, project: GliderProject):
        super().__init__()
        self.project = project
        self._updating = False

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("Centre"))
        header.addStretch()
        lbl_tip = QtWidgets.QLabel("Wingtip -->")
        lbl_tip.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        header.addWidget(lbl_tip)
        outer.addLayout(header)

        self.slider_layout = QtWidgets.QHBoxLayout()
        self.slider_layout.setSpacing(2)
        outer.addLayout(self.slider_layout, stretch=1)
        self.spin_layout = QtWidgets.QHBoxLayout()
        self.spin_layout.setSpacing(2)
        outer.addLayout(self.spin_layout)

        self.sliders: list[QtWidgets.QSlider] = []
        self.spinboxes: list[QtWidgets.QDoubleSpinBox] = []
        self._build()

    def _clear(self) -> None:
        for w in self.sliders + self.spinboxes:
            w.deleteLater()
        self.sliders.clear()
        self.spinboxes.clear()
        for layout in (self.slider_layout, self.spin_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item is not None:
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()

    def _build(self) -> None:
        self._clear()
        for w in as_editable_shape(self.project.glider.shape)._get_cell_widths():
            slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Vertical)
            slider.setRange(int(0.1 * self.SLIDER_SCALE), int(3.0 * self.SLIDER_SCALE))
            slider.setValue(int(w * self.SLIDER_SCALE))
            slider.setMinimumHeight(60)
            slider.valueChanged.connect(self._on_slider_changed)
            self.slider_layout.addWidget(slider)
            self.sliders.append(slider)

            sb = QtWidgets.QDoubleSpinBox()
            sb.setRange(0.1, 3.0)
            sb.setDecimals(2)
            sb.setSingleStep(0.05)
            sb.setValue(w)
            sb.setFixedWidth(60)
            sb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            sb.valueChanged.connect(self._on_spin_changed)
            self.spin_layout.addWidget(sb)
            self.spinboxes.append(sb)

    def _on_slider_changed(self) -> None:
        if self._updating:
            return
        self._updating = True
        for slider, sb in zip(self.sliders, self.spinboxes):
            sb.setValue(slider.value() / self.SLIDER_SCALE)
        self._updating = False
        self._emit()

    def _on_spin_changed(self) -> None:
        if self._updating:
            return
        self._updating = True
        for slider, sb in zip(self.sliders, self.spinboxes):
            slider.setValue(int(sb.value() * self.SLIDER_SCALE))
        self._updating = False
        self._emit()

    def _emit(self) -> None:
        widths = [sb.value() for sb in self.spinboxes]
        as_editable_shape(self.project.glider.shape).apply_cell_widths(widths)
        self.widths_changed.emit()

    def refresh(self) -> None:
        self._updating = True
        widths = as_editable_shape(self.project.glider.shape)._get_cell_widths()
        if len(widths) != len(self.sliders):
            self._build()
        else:
            for slider, sb, w in zip(self.sliders, self.spinboxes, widths):
                sb.setValue(w)
                slider.setValue(int(w * self.SLIDER_SCALE))
        self._updating = False


class RibSpacingPanel(QtWidgets.QGroupBox):
    """Compute cell-width coefficients from spacing presets (Equal / Proportional
    to chord / Constant area). Ported from openglider_lines."""

    applied = QtCore.Signal()
    _SLIDER_SCALE = 100

    MODE_EQUAL = "Equal spacing"
    MODE_PROPORTIONAL = "Proportional to chord"
    MODE_CONST_AREA = "Constant area"

    def __init__(self, project: GliderProject):
        super().__init__("Rib spacing")
        self.project = project

        layout = QtWidgets.QVBoxLayout(self)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems([self.MODE_EQUAL, self.MODE_PROPORTIONAL, self.MODE_CONST_AREA])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(self.mode_combo)

        self.prop_widget = QtWidgets.QWidget()
        prop_layout = QtWidgets.QVBoxLayout(self.prop_widget)
        prop_layout.setContentsMargins(0, 0, 0, 0)
        self.prop_label = QtWidgets.QLabel("Factor: 0.60")
        self.prop_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        prop_layout.addWidget(self.prop_label)
        self.prop_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.prop_slider.setRange(0, self._SLIDER_SCALE)
        self.prop_slider.setValue(int(0.6 * self._SLIDER_SCALE))
        self.prop_slider.valueChanged.connect(self._on_prop_slider_changed)
        prop_layout.addWidget(self.prop_slider)
        layout.addWidget(self.prop_widget)
        self.prop_widget.setVisible(False)

        self.apply_btn = QtWidgets.QPushButton("Apply to sliders")
        self.apply_btn.clicked.connect(self._apply)
        layout.addWidget(self.apply_btn)

    def _on_mode_changed(self, _index: int) -> None:
        self.prop_widget.setVisible(self.mode_combo.currentText() == self.MODE_PROPORTIONAL)

    def _on_prop_slider_changed(self, value: int) -> None:
        self.prop_label.setText(f"Factor: {value / self._SLIDER_SCALE:.2f}")

    def _sample_cell_chords(self) -> list[float]:
        shape = as_editable_shape(self.project.glider.shape)
        span = shape.span / 2
        num = shape._num_cell_widths
        chords: list[float] = []
        for i in range(num):
            if shape.has_center_cell and i == 0:
                x = span / (2 * num) / 2
            else:
                x = ((i / num) + ((i + 1) / num)) / 2 * span
            x = min(x, span)
            chords.append(max(shape.chord_at(x), 1e-6))
        return chords

    def _compute_equal(self) -> list[float]:
        return [1.0] * as_editable_shape(self.project.glider.shape)._num_cell_widths

    def _compute_proportional(self, factor: float) -> list[float]:
        """Match LE-Paragliding's iterative chord-proportional distribution.

        ``factor`` has the pre-processor's xk semantics: 0 is fully proportional
        to chord and 1 approaches equal spacing.
        """
        shape = as_editable_shape(self.project.glider.shape)
        full_span = shape.span
        half_span = full_span / 2
        cell_num = shape.cell_num
        num_coeffs = shape._num_cell_widths
        uniform_width = full_span / cell_num
        widths = [uniform_width] * num_coeffs

        chord_max = shape.chord_at(0.0)
        for _ in range(5):
            positions = [widths[0] / 2.0]
            for width in widths[1:]:
                positions.append(positions[-1] + width)

            new_widths = []
            for x in positions:
                chord = shape.chord_at(min(x, half_span))
                coefficient = ((chord_max - chord) * factor + chord) / chord_max
                new_widths.append(max(uniform_width * coefficient, 1e-6))

            half_width_sum = sum(new_widths)
            if shape.has_center_cell:
                half_width_sum -= new_widths[0] / 2.0
            scale = half_span / half_width_sum
            widths = [width * scale for width in new_widths]

        mean = sum(widths) / len(widths)
        return [width / mean for width in widths]

    def _compute_const_area(self) -> list[float]:
        chords = self._sample_cell_chords()
        inv = [1.0 / c for c in chords]
        mean_inv = sum(inv) / len(inv)
        return [max(min(v / mean_inv, 3.0), 0.1) for v in inv]

    def _apply(self) -> None:
        mode = self.mode_combo.currentText()
        if mode == self.MODE_EQUAL:
            widths = self._compute_equal()
        elif mode == self.MODE_PROPORTIONAL:
            widths = self._compute_proportional(self.prop_slider.value() / self._SLIDER_SCALE)
        elif mode == self.MODE_CONST_AREA:
            widths = self._compute_const_area()
        else:
            return
        as_editable_shape(self.project.glider.shape).apply_cell_widths(widths)
        self.applied.emit()


class ShapeWizard(GliderSelectionWizard):
    MODE_SPLINE = "spline"
    MODE_PARAMETRIC = "parametric"

    def __init__(self, app: MainWindow, project: GliderProject):
        super().__init__(app=app, project=project)
        self.shape_backup = self.shape.copy()
        self.shape_input = ShapeInput(self.project)
        self.distribution_input = RibDistInput(self.shape)
        self.distribution_input.on_change.append(lambda x, y: self.shape_input.redraw())

        # The upper part of the editor is either the rib-distribution spline or
        # the full-width row of cell-width sliders. Keeping both in a stack makes
        # changing cell-distribution mode replace the editor instead of trying to
        # squeeze the sliders into the settings column.
        self.distribution_canvas = self.distribution_input.get_widget()
        self.cell_width_sliders = CellWidthSlidersPanel(self.project)
        self.cell_distribution_stack = QtWidgets.QStackedWidget()
        self.cell_distribution_stack.addWidget(self.distribution_canvas)
        self.cell_distribution_stack.addWidget(self.cell_width_sliders)

        #self.canvas_controls = CanvasControls(self.shape_input, vertical=True)
        self.main_widget.addWidget(self.cell_distribution_stack)
        self.main_widget.addWidget(self.shape_input.get_widget())

        self.main_widget.setSizes([300, 700])

        self.shape_settings_widget = ShapeSettingsWidget(self.shape)
        self.settings = self.shape_settings_widget.settings

        # Shape mode is independent from the cell-distribution mode below.
        self.mode_toggle = QtWidgets.QGroupBox("Shape mode")
        mode_layout = QtWidgets.QHBoxLayout(self.mode_toggle)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Spline", self.MODE_SPLINE)
        self.mode_combo.addItem("Leparagliding", self.MODE_PARAMETRIC)
        mode_layout.addWidget(QtWidgets.QLabel("Mode:"))
        mode_layout.addWidget(self.mode_combo, stretch=1)

        self.leparagliding_panel = LeparaglidingPanel(self.project)
        self.leparagliding_panel.params_changed.connect(self._on_parametric_changed)

        # Initial mode from the shape type (parametric if it's a LeparaglidingShape)
        if isinstance(self.shape, LeparaglidingShape):
            self.mode_combo.setCurrentIndex(1)
            self.leparagliding_panel.setVisible(True)
            self._set_handles_visible(False)
        else:
            self.mode_combo.setCurrentIndex(0)
            self.leparagliding_panel.setVisible(False)
            self._set_handles_visible(True)

        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        # Cell-distribution toggle: rib-distribution spline curve <-> cell-width sliders
        self.cell_dist_toggle = QtWidgets.QGroupBox("Cell distribution")
        cd_layout = QtWidgets.QVBoxLayout(self.cell_dist_toggle)
        cd_row = QtWidgets.QHBoxLayout()
        self.cell_dist_combo = QtWidgets.QComboBox()
        self.cell_dist_combo.addItem("Spline", "spline")
        self.cell_dist_combo.addItem("Sliders", "sliders")
        cd_row.addWidget(QtWidgets.QLabel("Mode:"))
        cd_row.addWidget(self.cell_dist_combo, stretch=1)
        cd_layout.addLayout(cd_row)

        self.rib_spacing_panel = RibSpacingPanel(self.project)
        cd_layout.addWidget(self.rib_spacing_panel)

        # Restore files saved with explicit cell widths directly in sliders mode,
        # independently of how the leading/trailing edges are represented.
        sliders_mode = self.shape.cell_widths is not None
        if sliders_mode:
            self.cell_dist_combo.setCurrentIndex(1)
        self._set_cell_dist_widgets_visible(sliders_mode)
        self._apply_cell_dist_handle_visibility()
        self.cell_dist_combo.currentIndexChanged.connect(self._on_cell_dist_mode_changed)
        self.cell_width_sliders.widths_changed.connect(self._on_cell_widths_changed)
        self.rib_spacing_panel.applied.connect(self._on_rib_spacing_applied)

        settings_column = QtWidgets.QWidget()
        settings_column_layout = QtWidgets.QVBoxLayout(settings_column)
        settings_column_layout.setContentsMargins(0, 0, 0, 0)
        settings_column_layout.addWidget(self.mode_toggle)
        settings_column_layout.addWidget(self.leparagliding_panel)
        settings_column_layout.addWidget(self.cell_dist_toggle)
        settings_column_layout.addWidget(self.shape_settings_widget)
        settings_column_layout.addStretch()

        self.right_widget_layout.insertWidget(0, settings_column)
        #expect_value(self.right_widget.layout()).insertWidget(0, self.canvas_controls)
        self._selection_changed()

        self.shape_input.on_change.append(self.shape_settings_widget.update_shape)
        self.shape_input.on_change.append(self._on_spline_dragged)
        self.shape_input.on_change.append(self._selection_changed)

        self.shape_settings_widget.changed.connect(self.apply_settings)

    @property
    def shape(self) -> EditableShape:
        return as_editable_shape(self.project.glider.shape)

    # ── Shape mode toggle: spline <-> leparagliding ──
    def _set_handles_visible(self, visible: bool) -> None:
        """Show or hide only the planform's draggable control points."""
        self.shape_input.front.setVisible(visible)
        self.shape_input.back.setVisible(visible)

    def _set_shape(self, new_shape: EditableShape) -> None:
        """Replace the project's shape, keeping the input widgets' cached
        references in sync (they hold ``glider_shape`` from construction)."""
        self.project.glider.shape = new_shape
        self.shape_input.glider_shape = new_shape
        self.shape_input.refresh_from_shape()
        self.distribution_input.glider_shape = new_shape

    def _to_spline_shape(self) -> ParametricShape:
        """Change only the planform representation, preserving cell distribution."""
        shape = self.shape
        if isinstance(shape, LeparaglidingShape):
            return ParametricShape.from_shape(shape)
        if isinstance(shape, ParametricShape):
            return shape.copy()
        raise TypeError(f"Cannot convert {type(shape)} to a spline shape")

    def _to_leparagliding_shape(
        self, params: LeparaglidingShapeParams, cell_num: int | None = None
    ) -> LeparaglidingShape:
        """Change only the planform representation, preserving cell distribution."""
        shape = self.shape
        target_cell_num = shape.cell_num if cell_num is None else cell_num
        widths = None if shape.cell_widths is None else list(shape.cell_widths)
        if widths is not None:
            needed = target_cell_num // 2 + (target_cell_num % 2)
            widths = (widths + [1.0] * max(0, needed - len(widths)))[:needed]
        return LeparaglidingShape(
            params,
            shape.config,
            rib_distribution=shape.rib_distribution.copy(),
            cell_num=target_cell_num,
            cell_widths=widths,
        )

    def _on_mode_changed(self, _index: int) -> None:
        mode = self.mode_combo.currentData()
        if mode == self.MODE_PARAMETRIC:
            # Spline -> Leparagliding changes LE/TE only.
            params = self.leparagliding_panel.collect_params()
            self._set_shape(self._to_leparagliding_shape(params))
            self.leparagliding_panel._restore_from_shape()
            self.leparagliding_panel.setVisible(True)
            self._set_handles_visible(False)
            self._update()
        else:
            # Leparagliding -> spline keeps the generated LE/TE and the current
            # independent spline/sliders cell distribution.
            self._set_shape(self._to_spline_shape())
            self.leparagliding_panel.setVisible(False)
            self._set_handles_visible(True)
            self._update()

    def _on_parametric_changed(self) -> None:
        params = self.leparagliding_panel.collect_params()
        self._set_shape(self._to_leparagliding_shape(params))
        self._update()

    def _on_spline_dragged(self, _shape: EditableShape) -> None:
        """User dragged a control point in spline mode. If the shape still uses
        another representation, convert it to a spline shape so the edit sticks."""
        if self.mode_combo.currentData() == self.MODE_SPLINE and type(self.shape) is not ParametricShape:
            self._set_shape(self._to_spline_shape())

    # ── Cell-distribution toggle: rib-distribution spline <-> cell-width sliders ──
    def _set_cell_dist_widgets_visible(self, visible: bool) -> None:
        """Replace the upper spline editor with sliders and show their presets."""
        target = self.cell_width_sliders if visible else self.distribution_canvas
        self.cell_distribution_stack.setCurrentWidget(target)
        self.rib_spacing_panel.setVisible(visible)

    def _apply_cell_dist_handle_visibility(self) -> None:
        """Rib-distribution handles depend only on cell-distribution mode."""
        self.distribution_input.set_handle_visible(
            self.cell_dist_combo.currentData() == "spline"
        )

    def _on_cell_dist_mode_changed(self, _index: int) -> None:
        if self.cell_dist_combo.currentData() == "sliders":
            # Seed the widths from the current distribution, then edit via sliders.
            self.shape.apply_cell_widths(self.shape._current_cell_widths())
            self.cell_width_sliders.refresh()
            self._set_cell_dist_widgets_visible(True)
        else:
            # Back to a free rib-distribution curve.
            self.shape.cell_widths = None
            self._set_cell_dist_widgets_visible(False)
        self._apply_cell_dist_handle_visibility()
        self.distribution_input.refresh_from_shape()
        self.shape_input.redraw()

    def _on_cell_widths_changed(self) -> None:
        self.distribution_input.refresh_from_shape()
        self.shape_input.redraw()

    def _on_rib_spacing_applied(self) -> None:
        self.cell_width_sliders.refresh()
        self.distribution_input.refresh_from_shape()
        self.shape_input.redraw()

    def set_sweep(self, value: float) -> None:
        if isinstance(self.shape, ParametricShape):
            self.shape.set_sweep(value)
            self._update()
    
    def apply_settings(self) -> None:
        settings = self.shape_settings_widget.settings
        self.shape_input.config.apply_zrot = settings.zrot

        shape: EditableShape = self.shape

        if self.mode_combo.currentData() == self.MODE_PARAMETRIC:
            # Scale the leparagliding params to reach the requested area / aspect
            # ratio, then regenerate — otherwise apply_leparagliding_params would
            # rebuild from the unchanged panel values and discard the edit.
            params = self.leparagliding_panel.collect_params()
            old_area = shape.area
            old_ar = shape.aspect_ratio
            new_area = settings.area
            new_ar = settings.aspect_ratio
            if (
                (new_area != old_area or new_ar != old_ar)
                and old_area > 0 and old_ar > 0
                and new_area > 0 and new_ar > 0
            ):
                old_span = math.sqrt(old_ar * old_area)
                new_span = math.sqrt(new_ar * new_area)
                LeparaglidingShape.scale_params(
                    params,
                    new_span / old_span,
                    (new_area / new_span) / (old_area / old_span),
                )
            self._set_shape(self._to_leparagliding_shape(params, settings.cell_count))
            self.leparagliding_panel._restore_from_shape()
        else:
            shape.set_area(settings.area)
            shape.set_aspect_ratio(settings.aspect_ratio)
            shape.cell_num = settings.cell_count
            if shape.cell_widths is not None:
                # Keep the explicit distribution authoritative and resize it when
                # the number of cells changes while sliders mode is active.
                shape.apply_cell_widths(shape._get_cell_widths())

            if self.settings.sweep != settings.sweep and isinstance(shape, ParametricShape):
                shape.set_sweep(settings.sweep)

        self.settings = dataclasses.replace(settings)
        self._update()

    def _update(self) -> None:
        self.shape_input.refresh_from_shape()
        self.distribution_input.refresh_from_shape()
        if self.cell_dist_combo.currentData() == "sliders":
            self.cell_width_sliders.refresh()
        self.shape_settings_widget.update_shape(self.shape)
        self.shape_input.redraw()

    def selection_changed(self, selected: list[tuple[GliderProject, Color]]) -> None:
        self.shape_input.draw_shapes(selected, normalize_area=self.shape_settings_widget.normalize_area, normalize_span=self.shape_settings_widget.normalize_span)
        self.distribution_input.draw_shapes(selected)

    def apply(self, update: bool=True) -> None:
        logging.info(f"new shape: {self.shape_backup.area} -> {self.shape.area}")
        shape = self.shape.copy()
        self.project.glider.shape = self.shape_backup

        if self.settings.scale_lines:
            # scale everything before putting the new shape
            # (which has an updated area already)
            self.project.glider.set_area(shape.area)

        self.project.glider.shape = shape
        self.project.glider.rescale_curves()

        #self.project.glider.apply_shape_and_arc(self.project.glider_3d)
        #self.project.glider_3d.lineset.recalc()
        super().apply(True)


