from invenio_accounts.models import Role, User
from invenio_db import db


class GlobalRolesSupport:
    """A support class for working with global roles and their members."""

    @classmethod
    def set_global_roles_membership(cls, user: User, global_roles: set[str]):
        transformed_roles = (
            db.session.query(Role).filter(Role.name.in_(global_roles)).all()
        )
        if len(transformed_roles) != len(global_roles):
            raise ValueError(
                "Not all global roles were found in the database: "
                + ", ".join(
                    set(global_roles) - {role.name for role in transformed_roles}
                )
            )
        user.roles = transformed_roles
        db.session.add(user)
        db.session.commit()

    def set_user_global_roles(
        self,
        user: User,
        global_roles: set[Role],
    ):
        user.roles = list(global_roles)
        db.session.add(user)
        db.session.commit()
