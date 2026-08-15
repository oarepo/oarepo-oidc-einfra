# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Background tasks."""

from __future__ import annotations

import hashlib
import json
import logging
from io import BytesIO
from typing import TYPE_CHECKING

import boto3
from celery import shared_task
from flask import current_app
from invenio_accounts.models import User
from invenio_db import db

from oarepo_oidc_einfra.models import EInfraUserEntitlements
from oarepo_oidc_einfra.perun.dump import PerunDumpData
from oarepo_oidc_einfra.perun.entitlements import update_user_entitlements
from oarepo_oidc_einfra.proxies import current_einfra_oidc

if TYPE_CHECKING:
    from datetime import datetime


log = logging.getLogger("PerunSynchronizationTask")


def get_latest_perun_dump_path() -> str:
    """Get the path to the latest perun dump file in the S3 bucket."""
    # locate the last dump in the s3
    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )

    all_keys: list[tuple[str, datetime]] = []

    continuation_token = None
    while True:
        kwargs = {"Bucket": current_app.config["EINFRA_USER_DUMP_S3_BUCKET"]}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)

        all_keys.extend(
            (obj["Key"], obj["LastModified"]) for obj in response.get("Contents", []) if obj["Key"].endswith(".json")
        )

        if "NextContinuationToken" not in response:
            break
        continuation_token = response["NextContinuationToken"]

    if not all_keys:
        raise ValueError("No perun dump files found in the S3 bucket.")

    last_dump_path, _max_timestamp = max(all_keys, key=lambda x: x[1])

    log.info(
        "Last perun dump is at path %s with timestamp %s",
        last_dump_path,
        _max_timestamp,
    )
    return last_dump_path


@shared_task
def update_from_perun_dump(
    dump_path: str | None = None,
    checksum: str | None = None,
) -> None:
    """Update user communities from perun dump and propagate local communities that are not in perun yet.

    The dump with perun data is downloaded from the S3 storage and the users are synchronized
    with the database.

    Note: we suppose that the dump is small enough to be processed in a single task

    :param dump_path:        url with the dump
    :param checksum:         sha-256 checksum of the dump
    """
    if not current_einfra_oidc.dump_enabled:
        return

    log.info(
        "Updating from perun dump %s with checksum %s",
        dump_path,
        checksum,
    )
    if not dump_path:
        dump_path = get_latest_perun_dump_path()
        log.info("Using dump path %s", dump_path)

    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )

    with BytesIO() as obj:
        client.download_fileobj(
            Bucket=current_app.config["EINFRA_USER_DUMP_S3_BUCKET"],
            Key=dump_path,
            Fileobj=obj,
        )
        obj.seek(0)
        value = obj.getvalue()
        if checksum is not None:
            value_checksum = hashlib.sha256(value).hexdigest()
            if value_checksum != checksum:
                log.error("Checksum of the downloaded dump does not match the expected checksum.")
                return
        data = json.loads(value.decode("utf-8"))

    dump = PerunDumpData(data)

    synchronize_users_from_perun(dump)


def synchronize_users_from_perun(
    dump: PerunDumpData,
) -> None:
    """Synchronize users from perun dump to the database.

    :param dump:                 perun dump data
    """
    known_user_ids = set(db.session.scalars(db.session.query(EInfraUserEntitlements.user_id)))

    for aai_user in dump.users():
        known_user_ids.discard(aai_user.user.id)
        with db.session.begin_nested():
            try:
                update_user_metadata(
                    aai_user.user,
                    aai_user.full_name,
                    aai_user.email,
                    aai_user.organization,
                )
                update_user_entitlements(aai_user.user, aai_user.entitlements, cause="perun-dump-sync")
            except Exception:
                log.exception("Can not update user %s", repr(aai_user))
                db.session.rollback()

    for user_id in known_user_ids:
        # we need to remove the entitlements of the user that are no longer in the dump
        with db.session.begin_nested():
            try:
                user = db.session.query(User).filter_by(id=user_id).first()
                if user is None:
                    continue
                update_user_entitlements(user, set(), cause="perun-dump-user-removed")
            except Exception:
                log.exception("Can not update user entitlements for %s", user_id)
                db.session.rollback()


def update_user_metadata(user: User, full_name: str, email: str, organization: str) -> None:
    """Update user metadata in the database.

    If the data is the same, nothing is updated.

    :param user:        user object
    :param full_name:   full name
    :param email:       email
    :param organization: organization
    """
    save = False
    original_user_profile = user.user_profile or {}
    user_profile = user.user_profile or {}
    if full_name != original_user_profile.get("full_name"):
        user_profile["full_name"] = full_name
        save = True
    if organization != original_user_profile.get("affiliations"):
        user_profile["affiliations"] = organization
        save = True
    email = email.lower()
    if email != user.email:
        user.email = email
        save = True
    if save:
        user.user_profile = {**(user_profile or {})}  # type: ignore[reportAttributeAccessIssue]
        db.session.add(user)
        db.session.commit()
