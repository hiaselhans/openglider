import logging
import re
import math
from typing import Any

import pyqtgraph
from pyqtgraph.GraphicsScene.mouseEvents import MouseDragEvent
from openglider.gui.qt import QtCore, QtGui, QtWidgets
from openglider.gui.views_2d.elements import Image
from openglider.utils.colors import Color

logger = logging.getLogger(__name__)

#print(type(pyqtgraph.ViewBox))
class Canvas(pyqtgraph.ViewBox):
    grid = True
    locked_aspect_ratio = False
    static = False

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._grid = None
        self.update_data()
        self.setAcceptDrops(True)

    def update_data(self) -> None:
        if self.grid:
            if self._grid is None or self._grid not in self.addedItems:
                self._grid = pyqtgraph.GridItem()
                self.addItem(self._grid)
        elif self._grid and not self.grid:
            self.removeItem(self._grid)
            self._grid = None

        self.setAspectLocked(self.locked_aspect_ratio)

        self.update()

    def mouseDragEvent(self, ev: MouseDragEvent, axis: None=None) -> None:
        ev.accept()

        pos = ev.pos()
        last_pos = ev.lastPos()
        diff = -(pos - last_pos)

        ## Scale or translate based on mouse button
        if ev.button() & (QtCore.Qt.MouseButton.LeftButton | QtCore.Qt.MouseButton.MiddleButton):
            if ev.isFinish():  ## This is the final move in the drag; change the view scale now
                #print "finish"
                self.rbScaleBox.hide()
                ax = QtCore.QRectF(pyqtgraph.Point(ev.buttonDownPos(ev.button())), pyqtgraph.Point(pos))
                ax = self.childGroup.mapRectFromParent(ax)
                #self.showAxRect(ax)
                #self.axHistoryPointer += 1
                #self.axHistory = self.axHistory[:self.axHistoryPointer] + [ax]
            else:
                ## update shape of scale box
                self.updateScaleBox(ev.buttonDownPos(), ev.pos())
        elif self.static:
            return
        elif ev.button() & QtCore.Qt.MouseButton.RightButton:
            tr = diff  # *mask
            tr = self.mapToView(tr) - self.mapToView(pyqtgraph.Point(0, 0))
            x = tr.x() # if mask[0] == 1 else None
            y = tr.y() # if mask[1] == 1 else None

            self._resetTarget()
            if x is not None or y is not None:
                self.translateBy(x=x, y=y)
            self.sigRangeChangedManually.emit(self.state['mouseEnabled'])

    def dragEnterEvent(self, e: QtGui.QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.accept()
        else:
            e.ignore()

    def dropEvent(self, e: QtGui.QDropEvent) -> None:
        """
        Drag and Drop glider files
        """
        if e.mimeData().hasUrls():
            e.setDropAction(QtCore.Qt.DropAction.CopyAction)
            e.accept()
            fname = None
            # Workaround for OSx dragging and dropping
            for url in e.mimeData().urls():
                #if op_sys == 'Darwin':
                #    fname = str(NSURL.URLWithString_(str(url.toString())).filePathURL().path())
                fname = str(url.toLocalFile())
            
            if fname:
                # process file
                logger.info(f"read file: {fname}")
                self.load_bg_image(fname)

        else:
            e.ignore()

    def load_bg_image(self, path: str) -> None:
        background_image = Image.read_jpg(path)
        self.addItem(background_image)

        sc = self.scene()
        sc.sigMouseClicked.connect(background_image.clickEvent)
        sc.sigMouseMoved.connect(background_image.dragEvent)

    def wheelEvent(self, ev: QtGui.QWheelEvent, axis: None=None) -> None:
        if self.static is False:
            super().wheelEvent(ev, axis=axis)

    def get_widget(self) -> pyqtgraph.GraphicsView:
        canvas = pyqtgraph.GraphicsView()
        canvas.setCentralItem(self)
        canvas.setAcceptDrops(True)
        canvas.dragEnterEvent = self.dragEnterEvent
        canvas.dropEvent = self.dropEvent

        return canvas


class CanvasGrid(pyqtgraph.GraphicsLayoutWidget):
    def __init__(self, parent: QtWidgets.QWidget=None):
        super().__init__(parent)

        self.viewbox = Canvas()
        self.setCentralItem(self.viewbox)



class _BaseLayoutGraphics(QtWidgets.QGraphicsObject):
    points: dict[str, list[QtCore.QPointF]]
    lines: dict[str, list[tuple[QtCore.QPointF, QtCore.QPointF]]]
    polygons: dict[str, list[list[QtCore.QPointF]]]
    texts: list[tuple[str, QtCore.QPointF, float, str, float | None, str | None]]
    shown_layers: list[str] | None = None

    bounding_box: QtCore.QRectF | None = None

    def __init__(self, layout: Any, fill: bool=False, color: Color | None=None):
        super().__init__()
        self.layout = layout
        self.fill = fill
        self.alpha = 255
        self.color = color
        self.update()

    @staticmethod
    def _normalize_color_code(color_code: str) -> str:
        qt_color = QtGui.QColor(color_code)
        if qt_color.isValid():
            return qt_color.name().lstrip("#")

        try:
            color = Color.parse_hex(color_code)
            return color.hex()
        except Exception:
            return "000000"

    def _reset_primitives(self) -> None:
        self.points = {}
        self.lines = {}
        self.polygons = {}
        self.texts = []

    def paint(self, p: QtGui.QPainter, *args: Any) -> None:
        def setup_brush(color_code: str | Color) -> None:
            if isinstance(color_code, str):
                color = Color.parse_hex(color_code)
            else:
                color = color_code

            qt_color = QtGui.QColor(*color.rgb(), self.alpha)

            brush = QtGui.QBrush(qt_color)
            pen = QtGui.QPen(brush, 1)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(brush)

        for color_code, points in self.points.items():
            setup_brush(color_code)
            for point in points:
                p.drawPoint(point)
        
        for color_code, lines in self.lines.items():
            if self.color:
                setup_brush(self.color)
            else:
                setup_brush(color_code)
            for line in lines:
                p.drawLine(line[0], line[1])
        
        for color_code, polygons in self.polygons.items():
            setup_brush(color_code)
            for polygon in polygons:
                p.drawPolygon(polygon)

        for text_value, anchor, angle_deg, color_code, font_size, font_family in self.texts:
            if self.color:
                setup_brush(self.color)
            else:
                setup_brush(color_code)

            font = p.font()
            if font_size is not None:
                font.setPointSizeF(max(1.0, font_size))
            if font_family:
                font.setFamily(font_family)
            p.setFont(font)

            p.save()
            p.translate(anchor)
            p.rotate(-angle_deg)
            p.drawText(QtCore.QPointF(0.0, 0.0), text_value)
            p.restore()


                
    def boundingRect(self) -> QtCore.QRectF:
        return self.bounding_box or QtCore.QRectF(0,0,0,0)


class RsLayoutGraphics(_BaseLayoutGraphics):
    def update(self) -> None:  # type: ignore
        self._reset_primitives()

        bbox = self.layout.bbox()
        if bbox is None:
            self.bounding_box = QtCore.QRectF(0, 0, 0, 0)
        else:
            min_x, max_x, min_y, max_y = bbox
            self.bounding_box = QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y)

        for part in self.layout.parts:
            for layer_name, layer in part.layers.items():
                if self.shown_layers is not None and layer_name not in self.shown_layers:
                    continue

                style = layer.style
                if not style.visible:
                    continue

                stroke = style.stroke or "#000000"
                color = self._normalize_color_code(stroke)

                for line in layer.lines:
                    points_qt = [QtCore.QPointF(p.x, p.y) for p in line.nodes]
                    if len(points_qt) == 1:
                        self.points.setdefault(color, [])
                        self.points[color].append(points_qt[0])
                    elif len(points_qt) > 1:
                        fill_color = style.fill if self.fill else None
                        if fill_color:
                            normalized_fill = self._normalize_color_code(fill_color)
                            self.polygons.setdefault(normalized_fill, [])
                            self.polygons[normalized_fill].append(points_qt)
                        else:
                            self.lines.setdefault(color, [])
                            for p1, p2 in zip(points_qt[:-1], points_qt[1:]):
                                self.lines[color].append((p1, p2))

                for text in layer.texts:
                    dx = text.p2.x - text.p1.x
                    dy = text.p2.y - text.p1.y
                    length = math.hypot(dx, dy)
                    direction_x, direction_y = (1.0, 0.0)
                    if length > 0:
                        direction_x, direction_y = (dx / length, dy / length)

                    char_count = max(1, len(text.text))
                    font_size = style.font_size
                    if font_size is None:
                        if text.size is not None:
                            font_size = text.size
                        else:
                            font_size = length / char_count if length > 0 else 1.0

                    text_width = font_size * char_count
                    align = max(-1.0, min(1.0, text.align))
                    base_factor = (align + 1.0) * 0.5
                    base_x = text.p1.x + dx * base_factor
                    base_y = text.p1.y + dy * base_factor
                    horizontal_offset = -base_factor * text_width
                    letter_height = text.height * font_size
                    vertical_offset = letter_height * (text.valign - 0.5)
                    normal_x, normal_y = (-direction_y, direction_x)
                    anchor_x = base_x + direction_x * horizontal_offset + normal_x * vertical_offset
                    anchor_y = base_y + direction_y * horizontal_offset + normal_y * vertical_offset
                    angle_deg = math.degrees(math.atan2(dy, dx))

                    text_color = style.fill or style.stroke or "#000000"
                    self.texts.append((
                        text.text,
                        QtCore.QPointF(anchor_x, anchor_y),
                        angle_deg,
                        self._normalize_color_code(text_color),
                        font_size,
                        style.font_family,
                    ))

