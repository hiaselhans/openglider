from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Literal

from odfdo import Document, DrawImage, Element, Frame

from openglider.glider.texture.texture import SVGTexture, Texture
from openglider.glider.texture.uv_map.stacked import UVMapStacked
from openglider.glider.texture.uv_map.mirrored import UVMapMirrored
from openglider.utils.config_table import ConfigTable
from openglider.utils.table import Table


if TYPE_CHECKING:
    from openglider.glider.glider import Glider
    from openglider.glider.shape import Shape


TextureStyle = Literal["mirrored", "stacked"]


class TextureTable(ConfigTable):
    table_name: ClassVar[str] = "Texture"
    default_asset_path: ClassVar[str] = "Pictures/openglider_texture.svg"
    package_url_prefix: ClassVar[str] = "vnd.sun.star.Package:"

    style: TextureStyle = "stacked"
    dpi: int = 300
    svg: str | None = None

    def has_texture(self) -> bool:
        return bool(self.svg and self.svg.strip())

    def get_texture(self, shape: Shape, glider3d: Glider) -> Texture | None:
        if not self.has_texture():
            return None

        if self.style == "stacked":
            uv_map = UVMapStacked(shape, glider3d)
        else:
            uv_map = UVMapMirrored(shape, glider3d)

        svg_texture = SVGTexture(svg_data=self.svg, dpi=self.dpi)

        return Texture(uv_map=uv_map, texture=svg_texture)

    @classmethod
    def _migrate_table(cls, data: list[tuple[str, list[Any]]]) -> list[tuple[str, list[Any]]]:
        migrated = list(data)

        for i, (key, values) in enumerate(migrated):
            if key != "svg" or not values:
                continue

            svg_value = values[0]
            if svg_value is None:
                migrated[i] = ("svg", [None])
            else:
                svg_text = str(svg_value)
                migrated[i] = ("svg", [svg_text if svg_text.strip() else None])

        return migrated

    @classmethod
    def get_asset_path_from_table(cls, table: Table | None) -> str | None:
        if table is None or table.num_rows == 0:
            return None

        for row in range(1, table.num_rows):
            key_raw = table[row, 0]
            if key_raw is None:
                continue
            key = str(key_raw).strip().lower()
            if key == "svg_asset":
                value_raw = table[row, 1]
                if value_raw is not None:
                    value = str(value_raw).strip()
                    if value:
                        if value.startswith(cls.package_url_prefix):
                            value = value[len(cls.package_url_prefix):]
                        return value

        return None

    @classmethod
    def _decode_svg_bytes(cls, svg_bytes: bytes) -> str | None:
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return svg_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @classmethod
    def _normalize_asset_path(cls, asset_path: str) -> str:
        normalized = asset_path.strip()
        if normalized.startswith(cls.package_url_prefix):
            normalized = normalized[len(cls.package_url_prefix):]
        return normalized

    @classmethod
    def _extract_texture_preview_href_from_document(cls, document: Any) -> str | None:
        body = getattr(document, "body", None)
        if body is None:
            return None

        get_sheet = getattr(body, "get_sheet", None)
        if not callable(get_sheet):
            return None

        table_node = get_sheet(name=cls.table_name)
        if table_node is None:
            return None

        for frame in table_node.get_frames():
            if frame.get_attribute("draw:name") != "TexturePreview":
                continue

            images = frame.get_images()
            if not images:
                return None

            href = images[0].get_attribute("xlink:href")
            if href is None:
                href = images[0].get_attribute("href")
            if not isinstance(href, str) or not href:
                return None

            normalized = cls._normalize_asset_path(href)
            return normalized or None

        return None

    @classmethod
    def _read_embedded_svg_from_document(
        cls,
        document: Document,
        asset_path: str | None = None,
    ) -> str | None:
        asset = asset_path or cls.default_asset_path
        candidate_paths: list[str] = [cls._normalize_asset_path(asset)]

        preview_href = cls._extract_texture_preview_href_from_document(document)
        if preview_href and preview_href not in candidate_paths:
            candidate_paths.append(preview_href)

        part_names = document.get_parts()
        for filename in part_names:
            if filename.startswith("Pictures/") and filename.lower().endswith(".svg") and filename not in candidate_paths:
                candidate_paths.append(filename)

        for candidate in candidate_paths:
            try:
                part_data = document.get_part(candidate)
            except KeyError:
                continue
            if not isinstance(part_data, (bytes, bytearray)):
                continue

            decoded = cls._decode_svg_bytes(bytes(part_data))
            if decoded is not None:
                return decoded

        return None

    @classmethod
    def read_embedded_svg_from_ods(
        cls,
        ods_source: Document,
        asset_path: str | None = None,
    ) -> str | None:
        if not isinstance(ods_source, Document):
            raise TypeError("read_embedded_svg_from_ods expects an odfdo Document")
        return cls._read_embedded_svg_from_document(ods_source, asset_path=asset_path)

    def get_table(self) -> Table:
        return super().get_table(
            exclude_fields={"svg"},
            extra_rows=[("svg_asset", f"{self.package_url_prefix}{self.default_asset_path}")]
        )

    @classmethod
    def _get_table_node(cls, document: Any, table_name: str) -> Any | None:
        body = getattr(document, "body", None)
        if body is None:
            return None

        get_sheet = getattr(body, "get_sheet", None)
        if not callable(get_sheet):
            return None

        return get_sheet(name=table_name)

    @classmethod
    def _set_image_href(cls, image: Any, asset_path: str) -> None:
        image.set_attribute("xlink:href", asset_path)
        image.set_attribute("xlink:type", "simple")
        image.set_attribute("xlink:show", "embed")
        image.set_attribute("xlink:actuate", "onLoad")

    @classmethod
    def _ensure_texture_preview_frame_in_document(cls, document: Any, asset_path: str) -> None:
        table_node = cls._get_table_node(document, cls.table_name)
        if table_node is None:
            return

        for frame in table_node.get_frames():
            if frame.get_attribute("draw:name") != "TexturePreview":
                continue

            images = frame.get_images()
            if images:
                cls._set_image_href(images[0], asset_path)
            else:
                frame.append(DrawImage(url=asset_path))
            return

        frame = Frame(
            name="TexturePreview",
            z_index=0,
            size=("10cm", "6cm"),
            position=("6cm", "1cm"),
        )
        frame.set_attribute("text:anchor-type", "cell")
        frame.set_attribute("table:end-cell-address", "Texture.J26")
        frame.set_attribute("svg:end-x", "0cm")
        frame.set_attribute("svg:end-y", "0cm")
        frame.append(DrawImage(url=asset_path))

        shapes = table_node.get_element("table:shapes")
        if shapes is None:
            shapes = Element.from_tag("table:shapes")
            table_node.append(shapes)
        shapes.append(frame)

    def embed_svg_in_document(self, document: Document, asset_path: str | None = None) -> str | None:
        if not self.svg:
            return None

        asset = asset_path or self.default_asset_path
        if "/" in asset:
            folder = asset.rsplit("/", 1)[0] + "/"
            if document.manifest.get_media_type(folder) is None:
                document.manifest.add_full_path(folder)

        if document.manifest.get_media_type(asset) is None:
            document.manifest.add_full_path(asset, "image/svg+xml")
        else:
            document.manifest.set_media_type(asset, "image/svg+xml")

        document.set_part(asset, self.svg.encode("utf-8"))

        self._ensure_texture_preview_frame_in_document(document, asset)
        return asset
