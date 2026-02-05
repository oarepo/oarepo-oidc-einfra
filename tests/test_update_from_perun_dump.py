#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
from pathlib import Path

from invenio_access.permissions import system_identity
from invenio_accounts.models import User, UserIdentity
from invenio_communities import current_communities
from invenio_communities.members import Member

from oarepo_oidc_einfra.communities import CommunityRole, CommunitySupport
from oarepo_oidc_einfra.resources import store_dump
from oarepo_oidc_einfra.tasks import update_from_perun_dump


def update_from_file(filename, fix_communities_in_perun=True):
    pth = Path(__file__).parent / "dump_data" / filename
    dump_path, checksum = store_dump(pth.read_bytes())
    update_from_perun_dump(
        dump_path, checksum, fix_communities_in_perun=fix_communities_in_perun
    )


def test_no_communities(app, db, location, search_clear):
    update_from_file("1.json")
    update_from_file("2.json")
    update_from_file("3.json")


def test_no_communities_user_exists_but_not_linked(
    app, db, location, search_clear, smart_record
):
    with smart_record("test_no_communities_user_exists_but_not_linked.yaml"):
        my_original_email = "ms@cesnet.cz"
        user = User(
            username="asdasdasd",
            email=my_original_email,
            active=True,
            password="1234",
            user_profile={"full_name": "Mirek Simek"},
        )
        db.session.add(user)
        db.session.commit()

        update_from_file("1.json")
        update_from_file("2.json")
        update_from_file("3.json")

        user = User.query.filter_by(username="asdasdasd").one()
        assert user.user_profile["full_name"] == "Mirek Simek"
        assert user.email == my_original_email


def test_no_communities_user_linked(app, db, location, search_clear, smart_record):
    with smart_record("test_no_communities_user_linked.yaml"):
        my_original_email = "ms@cesnet.cz"
        user = User(
            username="asdasdasd",
            email=my_original_email,
            active=True,
            password="1234",
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

        update_from_file("1.json")
        update_from_file("2.json")
        update_from_file("3.json")

        user = User.query.filter_by(username="asdasdasd").one()
        assert user.user_profile["full_name"] == "Miroslav Šimek"
        assert user.user_profile["affiliations"] == "CESNET, z. s. p. o."
        assert user.email == "miroslav.simek@cesnet.cz"


def test_with_communities(app, db, location, search_clear, smart_record):
    with smart_record("test_with_communities.yaml"):
        my_original_email = "ms@cesnet.cz"
        user = User(
            username="asdasdasd",
            email=my_original_email,
            active=True,
            password="1234",
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

        update_from_file("1.json")
        update_from_file("2.json")
        update_from_file("3.json")

        memberships = list(Member.model_cls.query.filter_by(user_id=user.id).all())
        assert len(memberships) == 1
        assert memberships[0].role == "curator"
        assert str(memberships[0].community_id) == community.id

        # add a new curator so that there will ve 2 curators
        u2 = User(email="u2@test.com", active=True, password="1234")
        db.session.add(u2)
        db.session.commit()

        cs = CommunitySupport()
        cs.set_user_community_membership(u2, {CommunityRole(community.id, "curator")})

        # this should remove the first one
        update_from_file("4.json")

        # check that the first one is gone
        memberships = list(Member.model_cls.query.filter_by(user_id=user.id).all())
        assert len(memberships) == 0


def test_user_not_found_anymore(app, db, location, search_clear, smart_record):
    with smart_record("test_suspend_user.yaml"):
        user = User(
            username="asdasdasd",
            email="ms@cesnet.cz",
            active=True,
            password="1234",
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

        update_from_file("5.json")

        # check that the user still exists
        User.query.filter_by(username="asdasdasd").one()


def test_update_deactivated_ignored(app, db, location, search_clear):
    # Create a user linked to e-infra identity
    user = User(
        username="testuser",
        email="ms@cesnet.cz",
        active=True,
        password="1234",
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

    # Create CUNI community
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

    # Update from dump with deactivated community capability
    # The dump contains res:deactivated-communities:CUNI:role:curator
    # which should be ignored (not create memberships)
    # Set fix_communities_in_perun=False to avoid trying to sync to Perun
    update_from_file("6.json", fix_communities_in_perun=False)

    # Verify that the user is NOT added to the community
    memberships = list(Member.model_cls.query.filter_by(user_id=user.id).all())
    assert len(memberships) == 0, "User should not be added to deactivated community"


def test_update_deactivated_attempts_remove_existing_role(
    app, db, location, search_clear
):
    # Create a user linked to e-infra identity
    user = User(
        username="testuser",
        email="ms@cesnet.cz",
        active=True,
        password="1234",
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

    # Create a second user (admin) who will remain in the community
    admin_user = User(
        username="testadmin",
        email="admin@test.com",
        active=True,
        password="1234",
        user_profile={"full_name": "Test Admin"},
    )
    db.session.add(admin_user)
    db.session.commit()

    # Create CUNI community
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

    # Give both users roles in the community
    cs = CommunitySupport()
    cs.set_user_community_membership(user, {CommunityRole(community.id, "member")})
    cs.set_user_community_membership(
        admin_user, {CommunityRole(community.id, "curator")}
    )

    # Verify both users have roles
    memberships = list(Member.model_cls.query.filter_by(user_id=user.id).all())
    assert len(memberships) == 1
    assert memberships[0].role == "member"
    assert str(memberships[0].community_id) == community.id

    admin_memberships = list(
        Member.model_cls.query.filter_by(user_id=admin_user.id).all()
    )
    assert len(admin_memberships) == 1
    assert admin_memberships[0].role == "curator"

    # Update from dump with deactivated community capability
    # The dump contains res:deactivated-communities:CUNI:role:curator
    # This will attempt to remove testuser's role (who is linked to the e-infra identity)
    # testadmin will remain, preventing the "last owner" issue
    # Set fix_communities_in_perun=False to avoid trying to sync to Perun
    update_from_file("6.json", fix_communities_in_perun=False)

    # Verify that testuser was removed
    memberships = list(Member.model_cls.query.filter_by(user_id=user.id).all())
    assert (
        len(memberships) == 0
    ), "testuser should be removed from the deactivated community"

    # Verify that testadmin remains
    admin_memberships = list(
        Member.model_cls.query.filter_by(user_id=admin_user.id).all()
    )
    assert len(admin_memberships) == 1, "testadmin should remain in the community"
