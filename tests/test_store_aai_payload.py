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
