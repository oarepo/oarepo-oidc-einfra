#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
"""Support for global roles and their membership."""

from __future__ import annotations

from invenio_accounts.models import Role, User
from invenio_db import db


class GlobalRolesSupport:
    """A support class for working with global roles and their members."""

    @classmethod
    def set_global_roles_membership(cls, user: User, global_roles: set[str]) -> None:
        """Set the global roles for the user."""
        transformed_roles = db.session.query(Role).filter(Role.name.in_(global_roles)).all()
        if len(transformed_roles) != len(global_roles):
            raise ValueError(
                "Not all global roles were found in the database: "
                + ", ".join(set(global_roles) - {role.name for role in transformed_roles})
            )
        user.roles = transformed_roles  # type: ignore[reportAttributeAccessIssue]
        db.session.add(user)
        db.session.commit()

    def set_user_global_roles(
        self,
        user: User,
        global_roles: set[Role],
    ) -> None:
        """Set the global roles for the user."""
        user.roles = list(global_roles)  # type: ignore[reportAttributeAccessIssue]
        db.session.add(user)
        db.session.commit()
