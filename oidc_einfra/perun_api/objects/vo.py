from functools import cached_property

from .base import AAIContainer, AAIObject, aai_cached_get
from .group import AAIGroup, AAIGroupContainer
from .user import AAIUser


class AAIVO(AAIObject):

    @cached_property
    def groups(self):
        return AAIGroupContainer(
            self,
            lambda: self._req(
                manager="groupsManager",
                method="getAllRichGroupsWithAttributesByNames",
                result_class=AAIGroup,
                extra_kwargs={"vo": self.id},
            ),
        )

    def user_groups(self, user: "AAIUser"):
        return AAIGroupContainer(
            self,
            lambda: self._req(
                manager="groupsManager",
                method="getGroupsWhereUserIsActiveMember",
                result_class=AAIGroup,
                extra_kwargs={"user": user.id, "vo": self.id},
            ),
        )


class AAIVOList(AAIContainer):
    @aai_cached_get
    def get(self, id=None, uuid=None):
        if id:
            return self._req(
                manager="vosManager",
                method="getVo",
                result_class=AAIVO,
                extra_kwargs={"vo": id},
            )
        if uuid in self:
            # TODO: can not get vo by uuid (search api does not work for that),
            #  so listing all and searching locally
            return self[uuid]

        raise KeyError(f"Do not have VO with {id=} {uuid=}")
