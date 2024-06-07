from .base import AAIContainer, AAIObject, aai_cached_get


class AAIUser(AAIObject):
    pass


class AAIUserContainer(AAIContainer):
    @aai_cached_get
    def get(self, id=None, uuid=None, einfra_id=None):
        if id:
            return self._req(
                manager="usersManager",
                method="getUser",
                result_class=AAIUser,
                extra_kwargs={"user": id},
            )
        if uuid:
            raise Exception("Perun API does not allow searching by uuid yet")
        if einfra_id:
            return self._req(
                manager="usersManager",
                method="getUsersByAttributeValue",
                result_class=AAIUser,
                extra_kwargs={
                    "attributeName": "urn:perun:user:attribute-def:def:login-namespace:einfraid-persistent-shadow",
                    "attributeValue": einfra_id,
                },
                result_transformer=lambda x: x[0],
            )

        raise KeyError(f"Do not have VO with {id=} {uuid=} {einfra_id=}")
