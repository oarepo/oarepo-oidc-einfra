from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_users_resources.proxies import current_users_service


def test_create_user_with_profile(app, db, location, search_clear, client):

    member_email = "test@test.com"
    member_full_name = "Test User"

    user = current_users_service.create(
        system_identity,
        {"email": member_email},
    )._user

    u = db.session.query(User).get(user.id)
    u.user_profile = {"full_name": member_full_name}
    db.session.add(u)
    db.session.commit()
    db.session.expunge_all()

    u = db.session.query(User).get(user.id)

    assert u.user_profile["full_name"] == member_full_name
