from functools import cached_property

from .objects.base import AAIBase, AAIObjectCache
from .objects.user import AAIUserContainer, AAIUser
from .objects.vo import AAIVOList, AAIVO


class PerunAPI(AAIBase):
    def __init__(self, connection=None):
        super().__init__()
        self._connection = connection
        self._cache = AAIObjectCache()

    @cached_property
    def vos(self):
        return AAIVOList(self,
                         lambda: self._req(manager="vosManager",
                                        method="getVos",
                                        result_class=AAIVO))

    @cached_property
    def users(self):
        return AAIUserContainer(self,
                                lambda: self._req(manager="usersManager",
                                             method="getUsers",
                                             result_class=AAIUser
                                             ))
