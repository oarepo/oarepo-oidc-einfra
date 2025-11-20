#
# Copyright (c) 2025 CESNET z.s.p.o.
#
# This file is a part of oarepo-oidc-einfra (see https://github.com/oarepo/oarepo-oidc-einfra).
#
# oarepo-oidc-einfra is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.
#
from __future__ import annotations

from invenio_requests.records.api import Request


def test_store_aai_payload(app, db, location, search_clear, client):
    r = Request.create({})
    r.commit()
    r_id = r.id

    r["payload"] = {
        "aai_id": "12345",
    }
    r.commit()

    db.session.expunge_all()

    r = Request.get_record(r_id)
    assert r["payload"] == {
        "aai_id": "12345",
    }
