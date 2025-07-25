#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""EInfra terminal commands."""


import click
from flask.cli import with_appcontext
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_communities.communities.records.models import CommunityMetadata
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities

from oarepo_oidc_einfra.mutex import CacheMutex
from oarepo_oidc_einfra.resources import store_dump
from oarepo_oidc_einfra.tasks import (
    add_einfra_user_task,
    create_aai_invitation,
    import_perun_users_from_dump,
    synchronize_community_to_perun,
    update_from_perun_dump,
)


@click.group()
def einfra() -> None:
    """EInfra commands."""


@einfra.command("update_membership")
@click.argument("dump_file", required=False)
@with_appcontext
def update_membership_from_file(dump_file: str | None) -> None:
    """Upload a dump file to s3 and process it.

    Note: this command does not create new users, it only updates existing ones.

    :param dump_file: Path to the dump file on the local filesystem to import.
    """
    if dump_file:
        click.echo(f"Importing dump file {dump_file}")

        with open(dump_file, "rb") as f:
            path, checksum = store_dump(f.read())
    else:
        path = None
        checksum = None

    update_from_perun_dump(path, checksum)


@einfra.command("add_einfra_user")
@click.argument("email")
@click.argument("einfra_id")
@with_appcontext
def add_einfra_user(email: str, einfra_id: str) -> None:
    """Add a user to the system if it does not exist and link it with the EInfra identity."""
    add_einfra_user_task(email, einfra_id)


@einfra.command("clear_import_mutex")
@with_appcontext
def clear_import_mutex() -> None:
    """Clear the import mutex - should be used only as a last resort."""
    CacheMutex("EINFRA_SYNC_MUTEX").force_clear()


@einfra.command("import_users")
@click.argument("dump_path", required=False)
@with_appcontext
def import_perun_users(dump_path: str | None) -> None:
    """Import users from a dump file.

    :param dump_path: Path to the dump file in the S3 bucket.
    If not provided, it will use the last dump path.

    Note: this cli command is usually not used in the application, it is here for testing purposes.
    """
    import_perun_users_from_dump(dump_path)


@einfra.command("synchronize_community")
@click.argument("community_slug")
@with_appcontext
def synchronize_community(community_slug: str) -> None:
    """Re-synchronize a community to Perun."""
    community = current_communities.service.read(system_identity, community_slug)
    synchronize_community_to_perun(str(community.id))


@einfra.command("synchronize_all_communities")
@with_appcontext
def synchronize_all_communities() -> None:
    """Re-synchronize all communities to Perun."""
    from tqdm import tqdm

    community_list = CommunityMetadata.query.all()
    for community in tqdm(community_list):
        synchronize_community_to_perun(str(community.id))


@einfra.command("resend_invitation")
@click.argument("community_slug")
@click.argument("email")
@with_appcontext
def resend_invitation(community_slug: str, email: str) -> None:
    """Resend an invitation to a user to a community.

    :param community_slug: Slug of the community.
    :param email: Email of the user.
    """
    community = CommunityMetadata.query.filter_by(slug=community_slug).one()
    user = User.query.filter_by(email=email).one()
    member = MemberModel.query.filter_by(
        user_id=user.id, community_id=community.id
    ).one()
    request_id = member.request_id
    create_aai_invitation(str(request_id))
