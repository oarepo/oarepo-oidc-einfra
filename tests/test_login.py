#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
from __future__ import annotations

import pytest
from invenio_access.permissions import system_identity
from invenio_accounts.models import User, UserIdentity
from invenio_communities import current_communities
from invenio_communities.members.records.models import MemberModel


@pytest.mark.skip(reason="This test is intended to be run manually")
def test_login(app, db, location, search_clear, client, test_ui_pages):
    """Test login via E-INFRA OIDC.

    This test shows how to log in a user using the E-Infra OIDC provider.
    As log-in is a process based on a web browser, the test must be run
    manually at the moment

    To run it, set the following environment variables:
    INVENIO_EINFRA_CONSUMER_KEY
    INVENIO_EINFRA_CONSUMER_SECRET

    Then check that you have correct e-infra configuration in the conftest.py
    (correct ids of groups, facilities, attributes, ...) and run the test.

    Note: The test will fail if the user does not have exactly one membership
    inside perun AAI in the community with the slug 'cuni' and role 'curator'
    """
    my_original_email = "ms@cesnet.cz"
    user = User(
        username="asdasdasd",
        email=my_original_email,
        active=True,
        password="1234",  # noqa S106 # this password is ok for testing
        user_profile={"full_name": "Mirek Simek"},
    )
    db.session.add(user)
    db.session.commit()

    UserIdentity.create(
        user=user,
        method="e-infra",
        external_id="user1@einfra.cesnet.cz",
    )
    db.session.commit()

    community = current_communities.service.create(
        system_identity,
        {
            "slug": "CUNI",
            "metadata": {
                "title": "Charles University",
                "description": "Charles university members",
            },
            "access": {"visibility": "public"},
        },
    )
    current_communities.service.indexer.refresh()

    member_list = MemberModel.query.filter_by(user_id=user.id).all()
    assert len(member_list) == 0

    resp = client.get("/oauth/login/e-infra/", base_url="https://127.0.0.1:5000/")
    assert resp.status_code == 302
    location = resp.headers["Location"]
    print(  # noqa T201
        "Open your browser and go to the following location. Log-in there and copy the final URL here"
    )
    print(location)  # noqa T201
    redirect_url = input("Paste the final URL here: ")
    redirect_url = redirect_url.strip()
    redirect_url = redirect_url[len("https://127.0.0.1:5000") :]

    resp = client.get(redirect_url, base_url="https://127.0.0.1:5000/")
    assert resp.status_code == 302
    location = resp.headers["Location"]

    # check that the user has the correct community roles
    member_list = MemberModel.query.filter_by(user_id=user.id).all()
    assert len(member_list) == 1
    assert str(member_list[0].community_id) == community.id
    assert member_list[0].role == "curator"
