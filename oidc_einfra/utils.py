from flask_principal import Identity, UserNeed
from invenio_access import any_user, authenticated_user
from invenio_accounts.models import User, UserIdentity
from invenio_db import db
from invenio_records_resources.services.uow import Operation


def get_authenticated_identity(user_id):
    """Return an authenticated identity for the given user."""
    identity = Identity(user_id)
    identity.provides.add(any_user)
    identity.provides.add(UserNeed(user_id))
    identity.provides.add(authenticated_user)
    return identity


def get_identity_user(identity):
    for need in identity.provides:
        if need.method == "id":
            return User.query.filter_by(id=need.value).one()
    raise ValueError("No user found in identity")


def get_identity_einfra_id(identity):
    user = get_identity_user(identity)
    return get_user_einfra_id(user)


def get_user_einfra_id(user):
    return UserIdentity.query.filter_by(id_user=user.id, method="e-infra").one().id


class CommitOp(Operation):
    def __init__(self, entry):
        """Initialize the record commit operation."""
        self._entry = entry

    def on_register(self, uow):
        """Commit record (will flush to the database)."""
        db.session.add(self._entry)
