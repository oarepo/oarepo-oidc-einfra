#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
import pytest
from invenio_access.models import ActionUsers
from invenio_accounts.models import User
from invenio_oauth2server.models import Token
from invenio_records_resources.services.errors import PermissionDeniedError

from oarepo_oidc_einfra.resources import upload_dump_action


def test_store_dump(app, db, client, test_ui_pages):

    user = User(email="test@test.com", active=True)
    db.session.add(user)
    db.session.commit()

    token = Token.create_personal("test", user.id, scopes=[], is_internal=False)
    db.session.commit()

    with pytest.raises(PermissionDeniedError):
        client.post(
            "/api/oidc-einfra/dumps/upload",
            base_url="https://127.0.0.1:5000/",
            json={
                "resources": {},
                "users": {},
            },
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Content-Type": "application/json",
            },
        )

    db.session.add(ActionUsers.allow(upload_dump_action, user_id=user.id))
    db.session.commit()

    post_result = client.post(
        "/api/oidc-einfra/dumps/upload",
        base_url="https://127.0.0.1:5000/",
        json={
            "resources": {},
            "users": {},
        },
        headers={
            "Authorization": f"Bearer {token.access_token}",
            "Content-Type": "application/json",
        },
    )
    assert post_result.status_code == 201
    assert post_result.json == {"status": "ok"}
