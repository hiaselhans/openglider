from __future__ import annotations
from typing import TYPE_CHECKING, Dict, Any, Type, TypeVar

import pydantic
from pydantic.main import __dataclass_transform__
#from pydantic import Field as field
from dataclasses import dataclass as dc, asdict, replace, field, Field

from openglider.utils.cache import hash_attributes, hash_list

if TYPE_CHECKING:
    from pydantic.dataclasses import Dataclass

    OGDataclassT = TypeVar("OGDataclassT", bound="OGDataclass")
    class OGDataclass(Dataclass):
        def __json__(self: OGDataclassT) -> Dict[str, Any]:
            pass

        def copy(self: OGDataclassT) -> OGDataclassT:
            pass

        def __hash__(self: OGDataclassT) -> int:
            pass


class Config:
    arbitrary_types_allowed = True

@__dataclass_transform__(kw_only_default=True)
def dataclass(_cls) -> Type[OGDataclassT]:
    old_json = getattr(_cls, "__json__", None)
    if old_json is None or getattr(old_json, "is_auto", False):
        def __json__(instance):
            return {
                key: getattr(instance, key) for key in _cls_new.__dataclass_fields__
            }
        
        setattr(__json__, "is_auto", True)

        _cls.__json__ = __json__

    old_copy = getattr(_cls, "copy", None)
    if old_copy is None or getattr(old_copy, "is_auto", False):
        def copy(instance):
            return  replace(instance)
        
        setattr(copy, "is_auto", True)

        _cls.copy = copy
    
    old_hash = getattr(_cls, "__hash__", None)
    if old_hash is None or getattr(old_hash, "is_auto", False):
        # don't shadow hash (internal python name)
        def _hash(instance) -> int:
            try:
                lst = [getattr(instance, key) for key in _cls_new.__dataclass_fields__]
                return hash_list(lst)
            except Exception as e:
                raise ValueError(f"invalid elem: {instance}") from e

        
        setattr(_hash, "is_auto", True)

        _cls.__hash__ = _hash

    if TYPE_CHECKING:
        _cls_new = dc(_cls)
    else:
        _cls_new = pydantic.dataclasses.dataclass(config=Config)(_cls)
        
    return _cls_new

class BaseModel(pydantic.BaseModel):
    def __json__(self):
        return self.json()
