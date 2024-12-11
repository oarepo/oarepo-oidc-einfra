#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""EInfra terminal commands."""

import json
import logging
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING

import click
from flask import current_app
from flask.cli import with_appcontext
from invenio_access.permissions import system_identity
from invenio_accounts.models import User, UserIdentity
from invenio_communities.communities.records.models import CommunityMetadata
from invenio_communities.members.records.models import MemberModel
from invenio_communities.proxies import current_communities
from invenio_db import db
from werkzeug.local import LocalProxy

from oarepo_oidc_einfra.mutex import CacheMutex
from oarepo_oidc_einfra.proxies import current_einfra_oidc
from oarepo_oidc_einfra.resources import store_dump
from oarepo_oidc_einfra.tasks import (
    create_aai_invitation,
    synchronize_community_to_perun,
    update_from_perun_dump,
)

if TYPE_CHECKING:
    from flask_security.datastore import UserDatastore


@click.group()
def einfra() -> None:
    """EInfra commands."""


@einfra.command("upload_dump")
@click.argument("dump_file")
@with_appcontext
def upload_dump(dump_file: str) -> None:
    """Upload a dump file to s3 and process it.

    :param dump_file: Path to the dump file on the local filesystem to import.
    """
    click.echo(f"Importing dump file {dump_file}")

    with open(dump_file, "rb") as f:
        path, checksum = store_dump(f.read())

    update_from_perun_dump.delay(path, checksum)


@einfra.command("update_from_dump")
@click.argument("dump-path")
@click.option("--on-background/--on-foreground", default=False)
@click.option("--fix-communities-in-perun/--no-fix-communities-in-perun", default=True)
@click.option("--checksum", default=None)
@with_appcontext
def update_from_dump(
    dump_path: str,
    on_background: bool,
    fix_communities_in_perun: bool,
    checksum: str | None = None,
) -> None:
    """Update the data from the last imported dump.

    :param dump_name: Name of the dump to update from.
    :param on_background: Whether to run the task in the background.
    :param fix_communities_in_perun: Whether to fix communities in Perun.
    """
    # set python logger to show info from PerunSynchronizationTask
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("PerunSynchronizationTask")
    logger.setLevel(logging.INFO)

    if on_background:
        update_from_perun_dump.delay(
            dump_path, fix_communities_in_perun=fix_communities_in_perun
        )
    else:
        update_from_perun_dump(
            dump_path=dump_path,
            checksum=checksum,
            fix_communities_in_perun=fix_communities_in_perun,
        )


@einfra.command("add_einfra_user")
@click.argument("email")
@click.argument("einfra_id")
@with_appcontext
def add_einfra_user(email: str, einfra_id: str) -> None:
    """Add a user to the system if it does not exist and link it with the EInfra identity."""
    _add_einfra_user(email, einfra_id)


@einfra.command("clear_import_mutex")
@with_appcontext
def clear_import_mutex() -> None:
    """Clear the import mutex - should be used only as a last resort."""
    CacheMutex("EINFRA_SYNC_MUTEX").force_clear()


def _add_einfra_user(email: str, einfra_id: str) -> None:
    """Add a user to the system if it does not exist and link it with the EInfra identity."""
    _datastore: UserDatastore = LocalProxy(  # type: ignore
        lambda: current_app.extensions["security"].datastore
    )

    email = email.lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        kwargs = {
            "email": email,
            "password": None,
            "active": True,
            "confirmed_at": datetime.now(UTC),
        }
        _datastore.create_user(**kwargs)
        db.session.commit()  # type: ignore

        user = User.query.filter_by(email=email).one()

    identity = UserIdentity.query.filter_by(
        method="e-infra", id=einfra_id, id_user=user.id
    ).first()
    if not identity:
        UserIdentity.create(
            user=user,
            method="e-infra",
            external_id=einfra_id,
        )
        db.session.commit()  # type: ignore


@einfra.command("import_dump_users")
@click.argument("dump_path")
@with_appcontext
def import_dump_users(dump_path: str) -> None:
    """Import users from a dump file.

    :param dump_path: Path to the dump file in the S3 bucket.

    Note: this cli command is usually not used in the application, it is here for testing purposes.
    """
    client = current_einfra_oidc.dump_boto3_client

    with BytesIO() as obj:
        client.download_fileobj(
            Bucket=current_einfra_oidc.dump_s3_bucket,
            Key=dump_path,
            Fileobj=obj,
        )
        obj.seek(0)
        data = json.loads(obj.getvalue().decode("utf-8"))

    for user_data in data["users"].values():
        einfra_id = user_data["attributes"].get(
            "urn:perun:user:attribute-def:virt:login-namespace:einfraid-persistent"
        )
        email = user_data["attributes"].get(
            "urn:perun:user:attribute-def:def:preferredMail"
        )
        if not email or not einfra_id:
            continue
        print("Importing user", email, einfra_id)
        _add_einfra_user(email, einfra_id)


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
