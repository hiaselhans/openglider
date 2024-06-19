from __future__ import annotations

import abc
import types
from typing import Any, ClassVar, Generic, Self, TypeVar

from openglider.utils.dataclass import BaseModel
import pydantic


ReturnType = TypeVar("ReturnType")
TupleType = TypeVar("TupleType")

class CellTuple(BaseModel, Generic[TupleType]):
    model_config = pydantic.ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid"
        )
    index_offset: ClassVar[tuple[int, int]] = (0, 1)
    first: TupleType
    second: TupleType

    def __getitem__(self, index: int) -> TupleType:
        if index == 0:
            return self.first
        elif index == 1:
            return self.second
        
        raise ValueError(f"invalid index: {index}")

    
    @classmethod
    def from_value(cls, value: TupleType) -> Self:
        return cls(first=value, second=value)

    @pydantic.model_validator(mode="before")
    @classmethod
    def _validate(cls, v: Any) -> dict[str, Any] | Self:
        if isinstance(v, tuple) and len(v) == 2:
            return {
                "first": v[0],
                "second": v[1]
            }
        else:
            return {
                "first": v,
                "second": v
            }

class SingleCellTuple(CellTuple):
    index_offset: ClassVar[tuple[int, int]] = (0, 0)


_type_cache: dict[type[DTO], list[tuple[str, str]]] = {}

class DTO(BaseModel, Generic[ReturnType], abc.ABC):
    model_config = pydantic.ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid"
        )
    _types: list[tuple[str, str]] | None = None

    def get_object(self) -> ReturnType:

        raise NotImplementedError
    
    @staticmethod
    def _get_type_string(type_: type | None) -> str:
        assert type_ is not None

        if isinstance(type_, types.UnionType):
            names = []
            for subtype in type_.__args__:
                names.append(subtype.__name__)
            
            return " | ".join(names)
        else:
            return type_.__name__
    
    @staticmethod
    def _is_cell_tuple(type: Any) -> CellTuple | None:
        try:
            if issubclass(type, CellTuple):
                return type
        except TypeError:
            pass

        return None

    @classmethod
    def describe(cls) -> list[tuple[str, str]]:
        if cls not in _type_cache:
            result = []
            for field_name, field in cls.model_fields.items():
                is_cell_tuple = cls._is_cell_tuple(field.annotation)

                if is_cell_tuple:
                    inner_type = is_cell_tuple.__fields__["first"].annotation
                    inner_type_str = cls._get_type_string(inner_type)

                    if sum(is_cell_tuple.index_offset) > 0:
                        for side in is_cell_tuple.index_offset:
                            result.append((f"{field_name} ({side+1})", inner_type_str))
                    else:
                        result.append((f"{field_name}", inner_type_str))
                
                else:
                    result.append((field_name, cls._get_type_string(field.annotation)))

            _type_cache[cls] = result

        return _type_cache[cls]
    
    @classmethod
    def describe_text(cls) -> str:
        result = ""
        for index, (field_name, field_type) in enumerate(cls.describe()):
            result += f" {index+1: 2d}: {field_name}  ({field_type})\n"

        return result

        
    @classmethod
    def column_length(cls) -> int:
        return len(cls.describe())
