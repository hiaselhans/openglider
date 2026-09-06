import re
from typing import Any, Self, Annotated

from packaging.version import Version
import openglider.rs
import pydantic

from openglider.lines.node import Node
from openglider.utils.config_table import ConfigTable
from openglider.vector.unit import Angle, Length, Percentage
from openglider.version import __version__

class SewingAllowanceConfig(ConfigTable):
    table_name = "Sewing Allowance"

    general: Length = Length("10mm")
    design: Length = Length("10mm")
    trailing_edge: Length = Length("10mm")
    entry: Length = Length("10mm")
    folded: Length = Length("10mm")

def validate_version(version: Version | str) -> Version:
    if isinstance(version, str):
        return Version(version)

    return version

VersionType = Annotated[Version, pydantic.BeforeValidator(validate_version)]

class ParametricGliderConfig(ConfigTable):
    table_name = "Data"

    speed: float
    glide: float

    pilot_position: openglider.rs.vector.Vector3D
    pilot_position_name: str = "main"

    brake_offset: openglider.rs.vector.Vector3D = openglider.rs.vector.Vector3D([0.05, 0, 0.4])
    brake_name: str = "brake"

    has_stabicell: bool = False
    stabi_cell_position: float = 0.7
    stabi_cell_width: float = 0.5
    stabi_cell_length: float = 0.6
    stabi_cell_thickness: float = 0.7

    use_mean_profile: bool = False
    aoa_offset: Angle | None = None
    aoa_absolute: bool = False
    last_profile_height: float = 0
    
    use_sag: bool = True
    baseline_pct: Percentage | None = None

    color_groups: dict[str, str] | None = None

    version: VersionType = Version(__version__)

    @classmethod
    def __from_json__(cls, **data: Any) -> Self:
        for name in "pilot_position", "brake_offset":
            data[name] = openglider.rs.vector.Vector3D(data[name])
        
        return cls(**data)
    
    def __json__(self) -> dict[str, Any]:
        data = super().__json__()
        data["version"] = str(self.version)
        return data

    def _serialize_table_value(self, key: str, value: Any) -> list[Any]:
        if key == "version":
            return [Version(__version__)]
        return super()._serialize_table_value(key, value)

    def get_lower_attachment_points(self) -> dict[str, Node]:
        points = {
            self.pilot_position_name: self.pilot_position,
            self.brake_name: self.pilot_position + self.brake_offset
        }

        return {
            name: Node(name=name, node_type=Node.NODE_TYPE.LOWER, position=position) for name, position in points.items()
        }
    
    @classmethod
    def _migrate_table(cls, data: list[tuple[str, list[Any]]]) -> list[tuple[str, list[Any]]]:
        migrated = list(data)

        def pop_key(key: str) -> list[Any] | None:
            for i, (existing_key, value) in enumerate(migrated):
                if existing_key == key:
                    migrated.pop(i)
                    return value
            return None

        def upsert_key(key: str, value: list[Any]) -> None:
            for i, (existing_key, _) in enumerate(migrated):
                if existing_key == key:
                    migrated[i] = (key, value)
                    return
            migrated.append((key, value))

        if (stabicell := pop_key("stabicell")) is not None:
            upsert_key("has_stabicell", stabicell)

        node_data: dict[str, dict[str, float]] = {}
        node_keywords: list[str] = []

        for keyword, values in migrated:
            # OLD data migration
            if match := re.match(r"ahp([xyz])(.*)", keyword):
                node_keywords.append(keyword)
                coordinate, node_name = match.groups()
                node_data.setdefault(node_name, {})
                node_data[node_name][coordinate] = float(values[0])

        if node_keywords:
            node_keyword_set = set(node_keywords)
            migrated = [entry for entry in migrated if entry[0] not in node_keyword_set]

            nodes = [
                (name, openglider.rs.vector.Vector3D([node["x"], node["y"], node["z"]]))
                for name, node in node_data.items()
            ]
            # take the lower node as main point
            if nodes[0][1][2] > nodes[1][1][2]:
                nodes = [nodes[1], nodes[0]]

            upsert_key("pilot_position", list(nodes[0][1]))
            upsert_key("pilot_position_name", [nodes[0][0]])
            upsert_key("brake_offset", list(nodes[1][1] - nodes[0][1]))
            upsert_key("brake_name", [nodes[1][0]])

        return migrated
