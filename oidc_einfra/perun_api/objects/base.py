import copy
import functools
from functools import cached_property
from typing import Any, Callable, List, Union


class AAIObjectCache:
    def __init__(self):
        self.uuid_cache = {}
        self.id_cache = {}

    def clone(self) -> "AAIObjectCache":
        return copy.deepcopy(self)

    def get(self, uuid=None, id=None) -> "AAIObject":
        if uuid:
            return self.uuid_cache[uuid]
        elif id:
            return self.id_cache[id]
        raise ValueError("Either uuid or id must be provided")

    def put(self, obj: "AAIObject"):
        self.uuid_cache[str(obj.uuid)] = obj
        self.id_cache[str(obj.id)] = obj

    def get_or_put(self, obj: "AAIObject"):
        try:
            return self.get(uuid=obj.uuid)
        except KeyError:
            self.put(obj)
            return obj

    def remove(self, obj: "AAIObject"):
        if obj.uuid in self.uuid_cache:
            del self.uuid_cache[obj.uuid]
            del self.id_cache[obj.id]

    def invalidate(self):
        self.uuid_cache = {}
        self.id_cache = {}


def aai_cached_get(f):
    @functools.wraps(f)
    def wrapper(self, id=None, uuid=None, **kwargs):
        cache = self._get("_cache")
        if id or uuid:
            try:
                return cache.get(id=id, uuid=uuid)
            except KeyError:
                pass
        return f(self, id=id, uuid=uuid, **kwargs)

    return wrapper


class AAIBase:

    def __init__(self, parent: Union["AAIBase", None] = None):
        self.parent = parent

    def _get(self, attr):
        if hasattr(self, attr):
            return getattr(self, attr)
        if self.parent:
            return self.parent._get(attr)
        raise AttributeError(f"Attribute {attr} not found on {self} or parents")

    def _req(
        self,
        manager: str,
        method: str,
        http_method: str = "GET",
        extra_kwargs=None,
        result_class=None,
        result_kwargs=None,
        result_transformer=None,
    ):
        connection = self._get("_connection")
        if http_method == "get":
            call = connection.get
        else:
            call = connection.post

        metadata = call(manager, method, **(extra_kwargs or {})).json()
        if result_transformer:
            metadata = result_transformer(metadata)

        if isinstance(metadata, list):
            return [
                self._construct_result(x, result_class, result_kwargs) for x in metadata
            ]

        return self._construct_result(metadata, result_class, result_kwargs)

    def _construct_result(self, metadata: Any, result_class, result_kwargs):
        if not result_class:
            return None
        ret = result_class(parent=self, metadata=metadata, **(result_kwargs or {}))
        return self._get("_cache").get_or_put(ret)


class AAIObject(AAIBase):
    """Representation of AAI object, having both internal id and global uuid"""

    def __init__(
        self,
        parent: "AAIBase",
        metadata: Any,
        id_param="id",
        uuid_param="uuid",
        connection=None,
    ):
        """
        Constructor of AAI object

        :param parent:      the parent of the object. Can be either another AAIObject or a AAIContainer
        :param metadata:    metadata of the object
        :param ops:         operations that can be performed on the object
        :param id_param:    name of the parameter in metadata that contains internal id
        :param uuid_param:  name of the parameter in metadata that contains global uuid
        :param connection:  optional connection to the AAI, must be filled on the root object, no need to propagate
                            it to every object
        """
        super().__init__(parent)
        self.parent = parent
        self.metadata = metadata
        print("Metadata", metadata)
        self.id = metadata[id_param]
        self.uuid = metadata[uuid_param]
        if connection:
            self.connection = connection

    def __str__(self):
        ret = f"{self.__class__.__name__} id={self.id} uuid={self.uuid}"
        if "name" in self.metadata:
            ret += f' name={self.metadata["name"]}'
        return ret

    def __repr__(self):
        return str(self)


class AAIContainer(AAIBase):
    def __init__(self, parent: AAIBase, items: List | Callable):
        super().__init__(parent)
        self._items = items

    @cached_property
    def _cached_items(self):
        if isinstance(self._items, dict):
            return self._items
        return {x.uuid: x for x in self._items()}

    def values(self):
        return self._cached_items.values()

    def keys(self):
        return self._cached_items.keys()

    def items(self):
        return self._cached_items.items()

    def refresh(self, load_immediately=False):
        del self._cached_items
        if load_immediately:
            return self._cached_items

    def __iter__(self):
        return iter(self._cached_items)

    def __getitem__(self, item_uuid):
        return self._cached_items[str(item_uuid)]

    def __setitem__(self, key, value):
        self._cached_items[str(key)] = value

    def __contains__(self, item):
        if not item:
            return False
        if isinstance(item, AAIObject):
            return item.uuid in self._cached_items
        else:
            return str(item) in self._cached_items
