from functools import cached_property

from .base import AAIContainer, AAIObject, aai_cached_get
from .user import AAIUser, AAIUserContainer


class AAIGroupAdminContainer(AAIContainer):
    def add(self, user: AAIUser):
        self._req(
            manager="groupsManager",
            method="addAdmin",
            http_method="POST",
            extra_kwargs={"group": self.parent.id, "user": user.id},
        )
        self._cached_items[str(user.uuid)] = user
        return user

    def remove(self, user: AAIUser):
        self._req(
            manager="groupsManager",
            method="removeAdmin",
            http_method="POST",
            extra_kwargs={"group": self.parent.id, "user": user.id},
        )
        self._cached_items.pop(str(user.uuid), None)
        return user


class AAIGroupMemberContainer(AAIUserContainer):
    def add(self, user: AAIUser):
        self._req(
            manager="groupsManager",
            method="addMember",
            http_method="POST",
            extra_kwargs={"group": self.parent.id, "user": user.id},
        )
        self._cached_items[str(user.uuid)] = user
        return user

    def remove(self, user: AAIUser):
        self._req(
            manager="groupsManager",
            method="removeMember",
            http_method="POST",
            extra_kwargs={"group": self.parent.id, "user": user.id},
        )
        self._cached_items.pop(str(user.uuid), None)
        return user


class AAIGroup(AAIObject):
    @cached_property
    def admins(self):
        return AAIGroupAdminContainer(
            self,
            lambda: self._req(
                manager="groupsManager",
                method="getAdmins",
                http_method="GET",
                result_class=AAIUser,
                extra_kwargs={"group": self.id, "onlyDirectAdmins": True},
            ),
        )

    @cached_property
    def members(self):
        return AAIGroupMemberContainer(
            self,
            lambda: self._req(
                manager="groupsManager",
                method="getGroupRichMembers",
                http_method="GET",
                result_class=AAIUser,
                extra_kwargs={"group": self.id},
            ),
        )

    @property
    def parent_vo(self):
        from oidc_einfra.perun_api import AAIVO

        parent = self
        while parent and not isinstance(parent, AAIVO):
            parent = parent.parent
        return parent

    @cached_property
    def subgroups(self):
        def get_subgroups():
            parent_vo = self.parent_vo
            if not self.parent_vo:
                return []
            return [
                g
                for g in parent_vo.groups.values()
                if g.metadata["parentGroupId"] == self.id
            ]

        return AAISubgroupContainer(self, get_subgroups)


class AAIGroupContainer(AAIContainer):
    @aai_cached_get
    def get(self, id=None, uuid=None):
        if id:
            return self._req(
                manager="groupsManager",
                method="getGroup",
                result_class=AAIGroup,
                extra_kwargs={"group": id},
            )
        if uuid in self:
            return self[uuid]

        raise KeyError(f"Do not have group with {id=} {uuid=}")


class AAISubgroupContainer(AAIContainer):
    def create(self, name, description):
        grp = self._req(
            manager="groupsManager",
            method="createGroup",
            result_class=AAIGroup,
            extra_kwargs={
                "name": name,
                "description": description,
                "parentGroup": self.parent.id,
            },
        )

        parent_vo = self.parent.parent_vo
        parent_vo.groups[grp.uuid] = grp
        return grp
