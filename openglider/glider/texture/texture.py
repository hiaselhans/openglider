from __future__ import annotations

import math
import re
import warnings
from collections.abc import Iterable
from pathlib import Path
from xml.etree import ElementTree

import openglider.rs
from PIL import Image

from openglider.glider.texture.uv_map.mirrored import UVMapMirrored
from openglider.glider.texture.uv_map.stacked import UVMapStacked
from openglider.utils.dataclass import BaseModel

class Texture(BaseModel):
    uv_map: UVMapMirrored | UVMapStacked
    texture: SVGTexture


class SVGTexture:
    """SVG-backed texture utility for vector extraction and raster sampling."""

    def __init__(self, svg_data: str, dpi: int = 300):
        self.dpi = dpi
        self._svg_data = svg_data
        self._svg_root = ElementTree.fromstring(svg_data)
        self.width, self.height = self._read_svg_size(self._svg_data)
        self._normalized_vectors: list[openglider.rs.vector.PolyLine2D] | None = None
        self._raster: Image.Image | None = None
        self._raster_by_max_dim: dict[tuple[int, float], Image.Image] = {}

    @classmethod
    def read(cls, file_path: Path, dpi: int = 300) -> SVGTexture:
        svg_bytes = file_path.read_bytes()
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                svg_data = svg_bytes.decode(encoding)
                return cls(svg_data=svg_data, dpi=dpi)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"could not decode svg file: {file_path}")

    @staticmethod
    def _parse_svg_length(value: str | None) -> float | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None

        for suffix in ("px", "pt", "pc", "mm", "cm", "in"):
            if text.endswith(suffix):
                text = text[: -len(suffix)]
                break

        try:
            return float(text)
        except ValueError:
            return None

    @classmethod
    def _read_svg_size(cls, svg_data: str, source: Path | None = None) -> tuple[float, float]:
        try:
            root = ElementTree.fromstring(svg_data)
        except ElementTree.ParseError as err:
            raise ValueError("could not read svg file") from err

        width = cls._parse_svg_length(root.get("width"))
        height = cls._parse_svg_length(root.get("height"))

        if width is not None and height is not None:
            return max(width, 1.0), max(height, 1.0)

        view_box = root.get("viewBox") or root.get("viewbox")
        if view_box:
            parts = [part for part in view_box.replace(",", " ").split() if part]
            if len(parts) == 4:
                try:
                    return max(float(parts[2]), 1.0), max(float(parts[3]), 1.0)
                except ValueError:
                    pass

        raise ValueError("svg file has no usable size information")

    @staticmethod
    def _compose_transform(
        parent_transform: tuple[float, float, float, float, float, float],
        child_transform: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float, float, float, float, float]:
        a1, b1, c1, d1, e1, f1 = parent_transform
        a2, b2, c2, d2, e2, f2 = child_transform
        return (
            a1 * a2 + c1 * b2,
            b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2,
            b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1,
            b1 * e2 + d1 * f2 + f1,
        )

    @staticmethod
    def _apply_transform(
        point: tuple[float, float],
        transform: tuple[float, float, float, float, float, float],
    ) -> tuple[float, float]:
        x, y = point
        a, b, c, d, e, f = transform
        return (a * x + c * y + e, b * x + d * y + f)

    def _normalize_point(self, x: float, y: float) -> tuple[float, float]:
        min_x, min_y, width, height = self._svg_viewbox()
        if width == 0 or height == 0:
            return 0.0, 0.0
        u = (x - min_x) / width
        v = 1.0 - ((y - min_y) / height)
        return u, v

    def _svg_viewbox(self) -> tuple[float, float, float, float]:
        root = self._svg_root
        view_box = root.get("viewBox") or root.get("viewbox")
        if view_box is None:
            return 0.0, 0.0, self.width, self.height

        parts = [part for part in view_box.replace(",", " ").split() if part]
        if len(parts) != 4:
            return 0.0, 0.0, self.width, self.height

        try:
            min_x, min_y, width, height = [float(part) for part in parts]
        except ValueError:
            return 0.0, 0.0, self.width, self.height

        return min_x, min_y, width, height

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @staticmethod
    def _number_re() -> re.Pattern[str]:
        return re.compile(r"[-+]?(?:\d*\.\d+|\d+\.\d*|\d+)(?:[eE][-+]?\d+)?")

    @classmethod
    def _parse_transform_value(cls, value: str | None) -> tuple[float, float, float, float, float, float]:
        if value is None or not value.strip():
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

        matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        matches = list(re.finditer(r"([A-Za-z]+)\s*\(([^)]*)\)", value))
        for match in matches:
            name = match.group(1).lower()
            args = [float(token) for token in cls._number_re().findall(match.group(2))]
            if name == "matrix" and len(args) == 6:
                matrix = cls._compose_transform(matrix, (args[0], args[1], args[2], args[3], args[4], args[5]))
            elif name == "translate" and len(args) >= 1:
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0.0
                matrix = cls._compose_transform(matrix, (1.0, 0.0, 0.0, 1.0, tx, ty))
            elif name == "scale" and len(args) >= 1:
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                matrix = cls._compose_transform(matrix, (sx, 0.0, 0.0, sy, 0.0, 0.0))
            elif name == "rotate" and len(args) >= 1:
                angle = math.radians(args[0])
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)
                cx = args[1] if len(args) > 1 else 0.0
                cy = args[2] if len(args) > 2 else 0.0
                matrix = cls._compose_transform(
                    matrix,
                    (1.0, 0.0, 0.0, 1.0, cx, cy),
                )
                matrix = cls._compose_transform(
                    matrix,
                    (cos_a, sin_a, -sin_a, cos_a, 0.0, 0.0),
                )
                matrix = cls._compose_transform(
                    matrix,
                    (1.0, 0.0, 0.0, 1.0, -cx, -cy),
                )
            elif name == "skewx" and len(args) >= 1:
                angle = math.radians(args[0])
                matrix = cls._compose_transform(matrix, (1.0, 0.0, math.tan(angle), 1.0, 0.0, 0.0))
            elif name == "skewy" and len(args) >= 1:
                angle = math.radians(args[0])
                matrix = cls._compose_transform(matrix, (1.0, math.tan(angle), 0.0, 1.0, 0.0, 0.0))

        return matrix

    def _iter_svg_paths(
        self,
        element: ElementTree.Element,
        transform: tuple[float, float, float, float, float, float] = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    ) -> Iterable[tuple[tuple[float, float, float, float, float, float], ElementTree.Element]]:
        tag_name = self._local_name(element.tag)
        local_transform = self._parse_transform_value(element.get("transform"))
        current_transform = self._compose_transform(transform, local_transform)

        if tag_name == "path":
            yield current_transform, element

        for child in list(element):
            yield from self._iter_svg_paths(child, current_transform)

    @staticmethod
    def _path_has_curve_commands(path_data: str) -> bool:
        letters = re.findall(r"[A-Za-z]", path_data)
        unsupported = [letter for letter in letters if letter not in {"M", "m", "L", "l", "Z", "z"}]
        return bool(unsupported)

    @classmethod
    def _parse_path_points(cls, path_data: str) -> list[list[tuple[float, float]]]:
        tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.\d*|\d+)(?:[eE][-+]?\d+)?", path_data)
        if not tokens:
            return []

        subpaths: list[list[tuple[float, float]]] = []
        current_path: list[tuple[float, float]] = []
        current = (0.0, 0.0)
        start = (0.0, 0.0)
        command: str | None = None
        index = 0

        while index < len(tokens):
            token = tokens[index]
            if token in {"M", "m", "L", "l", "Z", "z"}:
                if token in {"M", "m"}:
                    if current_path:
                        subpaths.append(current_path)
                        current_path = []
                    current = start
                    command = token
                    index += 1
                    continue
                if token in {"Z", "z"}:
                    if current_path and current_path[0] != start:
                        current_path.append(start)
                    if current_path:
                        subpaths.append(current_path)
                    current_path = []
                    current = start
                    command = None
                    index += 1
                    continue
                command = token
                index += 1
                continue

            if command is None:
                index += 1
                continue

            if index + 1 >= len(tokens):
                break

            x = float(tokens[index])
            y = float(tokens[index + 1])
            index += 2

            if command in {"M", "m"}:
                target = (x, y) if command == "M" else (current[0] + x, current[1] + y)
                current = target
                start = target
                current_path = [target]
            elif command in {"L", "l"}:
                target = (x, y) if command == "L" else (current[0] + x, current[1] + y)
                current = target
                current_path.append(target)

        if current_path:
            subpaths.append(current_path)

        return subpaths

    def _extract_vectors(self, svg_root: ElementTree.Element) -> list[openglider.rs.vector.PolyLine2D]:
        vectors: list[openglider.rs.vector.PolyLine2D] = []

        for transform, node in self._iter_svg_paths(svg_root):
            if self._local_name(node.tag) != "path":
                continue

            path_data = node.get("d") or ""
            if not path_data.strip():
                continue

            if self._path_has_curve_commands(path_data):
                warnings.warn(f"Skipping SVG path with unsupported curve commands in path data: {path_data[:80]!r}")
                continue

            try:
                subpaths = self._parse_path_points(path_data)
            except ValueError as exc:
                warnings.warn(f"Skipping malformed SVG path: {exc}")
                continue

            for points in subpaths:
                if len(points) < 2:
                    continue

                transformed = [self._normalize_point(*self._apply_transform((x, y), transform)) for x, y in points]
                vectors.append(openglider.rs.vector.PolyLine2D(transformed))

        return vectors

    def get_vectors(self, bbox: tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D]) -> list[openglider.rs.vector.PolyLine2D]:
        """Return normalized SVG outlines remapped into the requested bbox.

        The ReportLab parse is performed lazily because this path is only needed
        for plotfile-style vector overlays, not for the raster texture pipeline.
        """
        if self._normalized_vectors is None:
            self._normalized_vectors = self._extract_vectors(self._svg_root)
        return [self._map_to_bbox(polyline, bbox) for polyline in self._normalized_vectors]

    def _map_to_bbox(
        self,
        polyline: openglider.rs.vector.PolyLine2D,
        bbox: tuple[openglider.rs.vector.Vector2D, openglider.rs.vector.Vector2D] | tuple[float, float, float, float],
    ) -> openglider.rs.vector.PolyLine2D:
        if len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox):
            x0, x1, y0, y1 = bbox
            min_x, max_x = sorted((x0, x1))
            min_y, max_y = sorted((y0, y1))
        else:
            min_x, min_y = bbox[0]
            max_x, max_y = bbox[1]

        width = max(max_x - min_x, 1e-9)
        height = max(max_y - min_y, 1e-9)

        mapped = [(min_x + p[0] * width, min_y + p[1] * height) for p in polyline]
        return openglider.rs.vector.PolyLine2D(mapped)

    def _get_raster(self) -> Image.Image:
        if self._raster is None:
            px_w = max(1, int(round(self.width * self.dpi / 72.0)))
            px_h = max(1, int(round(self.height * self.dpi / 72.0)))
            width, height, rgba = openglider.rs.svg_mod.render_svg_rgba_from_string(self._svg_data, px_w, px_h)
            self._raster = Image.frombytes("RGBA", (int(width), int(height)), bytes(rgba))
        return self._raster

    def get_raster_bounded(
        self,
        max_dim: int = 8192,
        precision: float = 1.0,
        cache: bool = True,
    ) -> Image.Image:
        """Return full texture raster capped to max_dim without giant intermediates."""
        max_dim = max(1, int(max_dim))
        precision = max(0.1, min(float(precision), 1.0))
        cache_key = (max_dim, round(precision, 3))
        if cache:
            cached = self._raster_by_max_dim.get(cache_key)
            if cached is not None:
                return cached

        px_w, px_h = self._get_bounded_raster_size(max_dim=max_dim, precision=precision)
        width, height, rgba = openglider.rs.svg_mod.render_svg_rgba_from_string(self._svg_data, px_w, px_h)
        image = Image.frombytes("RGBA", (int(width), int(height)), bytes(rgba))
        if cache:
            self._raster_by_max_dim[cache_key] = image
        return image

    def _get_bounded_raster_size(self, max_dim: int, precision: float) -> tuple[int, int]:
        px_w = max(1, int(round(self.width * self.dpi / 72.0)))
        px_h = max(1, int(round(self.height * self.dpi / 72.0)))
        scale = min(1.0, max_dim / max(px_w, px_h))
        render_scale = min(scale, precision)
        render_dpi = max(10, int(math.floor(self.dpi * render_scale)))
        px_w = max(1, int(round(self.width * render_dpi / 72.0)))
        px_h = max(1, int(round(self.height * render_dpi / 72.0)))
        return px_w, px_h

    def sample_color(self, u: float, v: float) -> tuple[int, int, int]:
        image = self._get_raster()
        width, height = image.size

        u = min(max(u, 0.0), 1.0)
        v = min(max(v, 0.0), 1.0)

        px = min(width - 1, max(0, int(round(u * (width - 1)))))
        py = min(height - 1, max(0, int(round(v * (height - 1)))))
        color = image.getpixel((px, py))
        if isinstance(color, tuple) and len(color) >= 3:
            return (int(color[0]), int(color[1]), int(color[2]))
        elif isinstance(color, int):
            return (int(color), int(color), int(color))
        else:
            raise ValueError(f"unexpected pixel color format: {color}")