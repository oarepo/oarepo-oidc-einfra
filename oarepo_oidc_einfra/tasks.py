#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Background tasks."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from itertools import chain, islice
from typing import TYPE_CHECKING, Literal

from celery import shared_task
from flask import current_app, url_for
from flask_security.datastore import UserDatastore
from invenio_accounts.models import User, UserIdentity
from invenio_cache.proxies import current_cache
from invenio_communities.communities.records.api import Community
from invenio_communities.members.records.api import Member
from invenio_db import db
from invenio_requests.records.api import Request
from werkzeug.local import LocalProxy

from oarepo_oidc_einfra.communities import CommunityRole, CommunitySupport
from oarepo_oidc_einfra.encryption import encrypt
from oarepo_oidc_einfra.mutex import mutex
from oarepo_oidc_einfra.perun.dump import PerunDumpData
from oarepo_oidc_einfra.perun.mapping import (
    einfra_to_local_users_map,
    get_perun_capability_from_invenio_role,
    get_user_einfra_id,
)
from oarepo_oidc_einfra.proxies import current_einfra_oidc

if TYPE_CHECKING:
    from uuid import UUID

    from oarepo_oidc_einfra.perun import PerunLowLevelAPI

log = logging.getLogger("PerunSynchronizationTask")


@shared_task
@mutex("EINFRA_SYNC_MUTEX")
def synchronize_community_to_perun(community_id: str) -> None:
    """Synchronize community into Perun groups and resources.

    The call is idempotent, if the perun mapping already exists,
    it is left untouched.

    :param community_id:        id of the community

    Structure inside Perun

    groups:
    EINFRA_COMMUNITIES_GROUP_ID
      +-- Community {slug}
          +-- Role {role_name} of {slug}
          +-- Role {role_name} of {slug} ...

    resources:
    EINFRA_REPOSITORY_FACILITY_ID
      +-- Community:{slug}    - capab. res:communities:{slug}, assigned community group
        +-- Community:{slug}:{role_name}  - capab. res:communities:{slug}:role:{role_name}, assigned role group
    """
    community: Community = Community.pid.resolve(community_id)  # type: ignore
    slug = community.slug
    log.info("Synchronizing community %s to Perun", slug)
    roles = current_app.config["COMMUNITIES_ROLES"]

    api = current_einfra_oidc.perun_api()

    group, resource = map_community_or_role(
        api,
        parent_id=current_einfra_oidc.communities_group_id,
        parent_vo=current_einfra_oidc.repository_vo_id,
        name=f"Community {slug}",
        description=community.metadata.get("description")  # type: ignore
        or f"Group for community {slug}",
        resource_name=f"Community:{slug}",
        resource_description=f"Resource for community {slug}",
        resource_capabilities=[f"res:communities:{slug}"],
    )

    parent_id = group["id"]

    # for each role, generate group & resource for the role
    for role in roles:
        role_name = role["name"]
        map_community_or_role(
            api,
            name=f"Role {role_name} of {slug}",
            description=f"Group for role {role_name} of community {slug}",
            parent_id=parent_id,
            parent_vo=current_einfra_oidc.repository_vo_id,
            resource_name=f"Community:{slug}:{role_name}",
            resource_description=f"Resource for community {slug} and role {role_name}",
            resource_capabilities=[f"res:communities:{slug}:role:{role_name}"],
        )


def map_community_or_role(
    api: PerunLowLevelAPI,
    *,
    parent_id: int,
    parent_vo: int,
    name: str,
    description: str,
    resource_name: str,
    resource_description: str,
    resource_capabilities: list[str],
) -> tuple[dict, dict]:
    """Map a single community or community role to perun's groups and resources.

    The call adds synchronization service so that we get the resource in the dump from perun.

    :param api:                     perun api
    :param parent_id:               parent group
    :param name:                    name of the group representing the community/role
    :param description:             description of the group
    :param resource_name:           name of the resource
    :param resource_description:    description of the resource
    :param resource_capabilities:   resource capabilities
    :return:        (group json, resource json)
    """
    # generate group for community
    group, group_created, admin_added = api.create_group(
        name=name,
        description=description,
        parent_group_id=parent_id,
        parent_vo=parent_vo,
    )

    # add the synchronization resource
    resource, resource_created = api.create_resource_with_group_and_capabilities(
        vo_id=current_einfra_oidc.repository_vo_id,
        facility_id=current_einfra_oidc.repository_facility_id,
        group_id=group["id"],
        name=resource_name,
        description=resource_description,
        capability_attr_id=current_einfra_oidc.capabilities_attribute_id,
        capabilities=resource_capabilities,
        perun_sync_service_id=current_einfra_oidc.sync_service_id,
    )
    return group, resource


@shared_task
def synchronize_all_communities_to_perun() -> None:
    """Check and repair community mapping within perun."""
    log.info("Synchronizing all communities to Perun")
    for community_model in Community.model_cls.query.all():
        synchronize_community_to_perun(str(community_model.id))


def get_latest_perun_dump_path() -> str:
    """Get the path to the latest perun dump file in the S3 bucket."""
    # locate the last dump in the s3
    client = current_einfra_oidc.dump_boto3_client

    all_keys: list[tuple[str, datetime]] = []

    continuation_token = None
    while True:
        kwargs = {"Bucket": current_einfra_oidc.dump_s3_bucket}
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        response = client.list_objects_v2(**kwargs)

        for obj in response.get("Contents", []):
            if obj["Key"].endswith(".json"):
                all_keys.append((obj["Key"], obj["LastModified"]))

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
@mutex("EINFRA_SYNC_MUTEX")
def update_from_perun_dump(
    dump_path: str | None = None,
    checksum: str | None = None,
    fix_communities_in_perun: bool = True,
    check_dump_in_cache: bool = True,
) -> None:
    """Update user communities from perun dump and propagate local communities that are not in perun yet.

    The dump with perun data is downloaded from the S3 storage and the users are synchronized
    with the database.

    Note: we suppose that the dump is small enough to be processed in a single task and the processing
    will take less than 1 hour (the default task timeout inside the mutex).

    :param dump_path:        url with the dump
    :param checksum:         sha-256 checksum of the dump
    :param fix_communities_in_perun     if some local communities were not propagated to perun, propagate them
    :param check_dump_in_cache:    if the dump path is already in the cache, do not process it again
    """
    log.info(
        "Updating from perun dump %s with checksum %s",
        dump_path,
        checksum,
    )
    if not dump_path:
        dump_path = get_latest_perun_dump_path()
        log.info("Using dump path %s", dump_path)

    if check_dump_in_cache:
        cache_dump_path = current_cache.cache.get("EINFRA_LAST_DUMP_PATH")
        if cache_dump_path and cache_dump_path != dump_path:
            # already have a new dump path, no need to process this one
            log.info(
                "Should process file %s from cache, but the dump path "
                "has already changed, so skipping processing.",
                dump_path,
            )
            return
    client = current_einfra_oidc.dump_boto3_client

    with BytesIO() as obj:
        client.download_fileobj(
            Bucket=current_einfra_oidc.dump_s3_bucket,
            Key=dump_path,
            Fileobj=obj,
        )
        obj.seek(0)
        value = obj.getvalue()
        if checksum is not None:
            value_checksum = hashlib.sha256(value).hexdigest()
            if value_checksum != checksum:
                log.error(
                    "Checksum of the downloaded dump does not match the expected checksum."
                )
                return
        data = json.loads(value.decode("utf-8"))
    community_support = CommunitySupport()
    dump = PerunDumpData(
        data, community_support.slug_to_id, community_support.role_names
    )

    if fix_communities_in_perun:
        synchronize_communities_to_perun(
            community_support.all_community_roles, dump.aai_community_roles
        )

    synchronize_users_from_perun(dump, community_support)


def synchronize_communities_to_perun(
    repository_community_roles: set[CommunityRole],
    aai_community_roles: set[CommunityRole],
) -> None:
    """Synchronize communities to perun if they do not exist in perun yet.

    :param repository_community_roles:   set of community roles from the repository
    :param aai_community_roles:          set of community roles from the perun dump
    """
    if repository_community_roles - aai_community_roles:
        log.info(
            "Some community roles are not mapped "
            f"to any resource: {repository_community_roles - aai_community_roles}"
        )
        communities_not_in_perun = {
            str(cr.community_id)
            for cr in repository_community_roles - aai_community_roles
        }
        for community_id in communities_not_in_perun:
            synchronize_community_to_perun(community_id)


def chunks[T](iterable: Iterable[T], size: int = 10) -> Iterable[chain[T]]:
    """Split the iterable into chunks of the given size.

    :param iterable:    an iterable that will be split to chunks
    :param size:        size of the chunk
    """
    iterator = iter(iterable)
    for first in iterator:
        yield chain([first], islice(iterator, size - 1))


def synchronize_users_from_perun(
    dump: PerunDumpData, community_support: CommunitySupport
) -> None:
    """Synchronize users from perun dump to the database.

    :param dump:                 perun dump data
    :param community_support:    community support object
    """
    local_users_by_einfra = einfra_to_local_users_map()
    for aai_user_chunk in chunks(dump.users(), 100):
        aai_user_chunk_by_einfra_id = {u.einfra_id: u for u in aai_user_chunk}

        local_user_id_to_einfra_id = {}
        for einfra_id in aai_user_chunk_by_einfra_id:
            local_user_id = local_users_by_einfra.pop(einfra_id, None)
            if local_user_id:
                local_user_id_to_einfra_id[local_user_id] = einfra_id
        if not local_user_id_to_einfra_id:
            continue

        # bulk get users from the database
        local_users = (
            db.session.query(User)  # type: ignore
            .filter(User.id.in_(local_user_id_to_einfra_id.keys()))
            .all()
        )

        # bulk get communities for the users
        local_community_roles_by_user_id = (
            community_support.get_user_list_community_membership(
                local_user_id_to_einfra_id.keys()
            )
        )

        for user in local_users:
            aai_user = aai_user_chunk_by_einfra_id[local_user_id_to_einfra_id[user.id]]
            log.info("Setting user %s with roles %s", user, aai_user.roles)
            update_user_metadata(
                user, aai_user.full_name, aai_user.email, aai_user.organization
            )

            new_community_roles = filter_community_roles(
                community_support, aai_user.roles
            )

            community_support.set_user_community_membership(
                user,
                new_community_roles=new_community_roles,
                current_community_roles=local_community_roles_by_user_id.get(
                    user.id, set()
                ),
            )

        for unknown_user in set(aai_user_chunk_by_einfra_id.keys()) - set(
            local_user_id_to_einfra_id.values()
        ):
            log.info(
                "User with einfra id %s not yet found in the local database",
                unknown_user,
            )

    # for users that are not in the dump anymore, remove all communities
    for local_user_id in local_users_by_einfra.values():
        user = User.query.filter_by(id=local_user_id).one()
        log.info("Removing obsolete user %s", user)
        community_support.set_user_community_membership(user, set())


def filter_community_roles(
    community_support: CommunitySupport, aai_roles: Iterable[CommunityRole]
) -> set[CommunityRole]:
    """Filter community roles to keep only the most important role for each community.

    :param community_support:    community support object
    :param aai_roles:            an iterable community roles
    """
    new_community_roles: dict[UUID, CommunityRole] = {}

    for community_role in aai_roles:
        if community_role.community_id not in new_community_roles or (
            community_support.role_priority(community_role.role)
            > community_support.role_priority(
                new_community_roles[community_role.community_id].role
            )
        ):
            new_community_roles[community_role.community_id] = community_role
    return set(new_community_roles.values())


def update_user_metadata(
    user: User, full_name: str, email: str, organization: str
) -> None:
    """Update user metadata in the database.

    If the data is the same, nothing is updated.

    :param user:        user object
    :param full_name:   full name
    :param email:       email
    :param organization: organization
    """
    save = False
    user_profile = user.user_profile
    if full_name != user.user_profile.get("full_name"):
        user_profile["full_name"] = full_name
        save = True
    if organization != user.user_profile.get("affiliations"):
        user_profile["affiliations"] = organization
        save = True
    email = email.lower()
    if email != user.email:
        user.email = email
        save = True
    if save:
        user.user_profile = {**user_profile}
        db.session.add(user)  # type: ignore - we might need to install sqlalchemy[mypy]
        db.session.commit()  # type: ignore


@shared_task
def create_aai_invitation(request_id: str) -> dict | None:
    """Create an invitation in AAI for an invenio invitation request.

    :param request_id:  id of the invenio invitation request
    :return:            invitation data as returned from perun
    """
    perun_api = current_einfra_oidc.perun_api()

    request = Request.get_record(request_id)
    invitation = Member.get_member_by_request(request_id)
    invitation_role: str = invitation.role  # type: ignore

    if request.topic:
        topic = request.topic.resolve()  # type: ignore
    else:
        raise ValueError("AAI Invitation Request does not have a topic.")

    log.info(
        "Creating AAI invitation for user %s, community %s, role %s",
        invitation.model.user_id,
        topic.slug,
        invitation_role,
    )

    capability = get_perun_capability_from_invenio_role(topic.slug, invitation_role)
    resource = perun_api.get_resource_by_capability(
        vo_id=current_einfra_oidc.repository_vo_id,
        facility_id=current_einfra_oidc.repository_facility_id,
        capability=capability,
    )
    if not resource:
        raise ValueError(
            f"Resource for capability {capability} not found inside Perun."
        )
    groups = perun_api.get_resource_groups(resource_id=resource["id"])
    groups = [
        group
        for group in groups
        if group["voId"] == current_einfra_oidc.repository_vo_id
    ]

    if not groups:
        log.error(
            f"Resource for capability {capability} not found inside Perun, "
            f"so can not send invitation to its associated group."
        )
        return None
    if len(groups) > 1:
        log.error(
            f"More than one group for capability {capability} found inside Perun, "
            f"so can not send invitation to its associated group."
        )
        return None

    encrypted_request_id = encrypt(request_id)

    redirect_url = url_for(
        "oarepo_oidc_einfra_ui.accept_invitation",
        request_id=encrypted_request_id,
        _external=True,
    )
    if redirect_url.startswith("http://"):
        redirect_url = redirect_url.replace("http://", "https://", 1)

    if not invitation.model:
        raise ValueError(f"Invitation {invitation} does not have a model.")

    if request.expires_at is None:
        expiration_date = date.today() + timedelta(days=7)
    else:
        expiration_date = request.expires_at.date()  # type: ignore

    user = User.query.filter_by(id=invitation.model.user_id).one()
    perun_response = perun_api.send_invitation(
        vo_id=current_einfra_oidc.repository_vo_id,
        group_id=groups[0]["id"],
        email=user.email,
        fullName=user.user_profile.get("full_name", user.email),
        language=current_einfra_oidc.default_language,
        expiration=expiration_date.isoformat(),
        redirect_url=redirect_url,
    )

    # set the AAI id in the request payload so we can later use it to check if the
    # invitation was accepted or not (in case accept invitation endpoint is not called)
    request["payload"] = {
        **(request.get("payload", None) or {}),
        "aai_id": str(perun_response["id"]),
    }
    request.commit()
    db.session.commit()
    return perun_response


@shared_task
def change_aai_role(community_slug: str, user_id: int, new_role: str) -> None:
    """Propagate changed community role to AAI.

    :param community_slug:  community slug
    :param user_id:         user id     (internal)
    :param new_role:        new role name
    """
    log.info(
        "Changing AAI role for user %s in community %s to %s",
        user_id,
        community_slug,
        new_role,
    )
    remove_aai_user_from_community(community_slug, user_id)
    add_aai_role(community_slug, user_id, new_role)


@shared_task
def remove_aai_user_from_community(community_slug: str, user_id: int) -> None:
    """Remove user from perun group representing a community.

    :param community_slug:  community slug
    :param user_id:         user id
    """
    log.info(
        "Removing AAI user %s from community %s",
        user_id,
        community_slug,
    )
    for role in CommunitySupport().role_names:
        aai_group_op("remove_user_from_group", community_slug, user_id, role)


@shared_task
def add_aai_role(community_slug: str, user_id: int, role: str) -> None:
    """Add user to perun group representing a community and a role.

    :param community_slug:  community slug
    :param user_id:         user id
    :param role:            role name
    """
    log.info(
        "Adding AAI user %s to community %s with role %s",
        user_id,
        community_slug,
        role,
    )
    aai_group_op("add_user_to_group", community_slug, user_id, role)


def aai_group_op(
    op: Literal["add_user_to_group", "remove_user_from_group"],
    community_slug: str,
    user_id: int,
    role: str,
) -> None:
    """Universal function for adding/removing user from group in AAI.

    :param op:              operation to perform (add_user_to_group, remove_user_from_group)
    :param community_slug:  community slug
    :param user_id:         user id
    :param role:            role name
    """
    perun_api = current_einfra_oidc.perun_api()

    einfra_id = get_user_einfra_id(user_id)
    if not einfra_id:
        # nothing to synchronize as the user has no einfra identity
        return

    # 1. find resource by capability
    resource = perun_api.get_resource_by_capability(
        vo_id=current_einfra_oidc.repository_vo_id,
        facility_id=current_einfra_oidc.repository_facility_id,
        capability=get_perun_capability_from_invenio_role(community_slug, role),
    )
    if resource is None:
        log.error(
            f"Resource for {community_slug} and role {role} not found inside Perun, "
            f"so can not remove user from its associated group."
        )
        return

    user = perun_api.get_user_by_attribute(
        attribute_name=current_einfra_oidc.einfra_user_id_search_attribute,
        attribute_value=einfra_id,
    )
    if user is None:
        log.error(
            f"User with einfra id {einfra_id} not found inside Perun, "
            f"so can not remove user from its associated group."
        )
        return

    # 2. for each group, perform the operation on it
    for group in perun_api.get_resource_groups(resource_id=resource["id"]):
        try:
            getattr(perun_api, op)(
                vo_id=current_einfra_oidc.repository_vo_id,
                user_id=user["id"],
                group_id=group["id"],
            )
        except:
            log.error(f"Error while performing {op} on group {group} for user {user}")


@shared_task
def add_einfra_user_task(email: str, einfra_id: str) -> None:
    """Add a user to the system if it does not exist and link it with the EInfra identity."""
    log.info(
        "Checking EInfra user with email %s and EInfra ID %s",
        email,
        einfra_id,
    )
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
        log.info("    Created new user %s with email %s", user, email)

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
        log.info(
            "    Created new identity for user %s with EInfra ID %s",
            user,
            einfra_id,
        )


@shared_task
def import_perun_users_from_dump(dump_path: str | None = None) -> None:
    """Import users from the perun dump file.

    :param dump_path:  path to the perun dump file
    """
    log.info("Importing users from perun dump %s", dump_path)

    if not dump_path:
        dump_path = get_latest_perun_dump_path()
        log.info("Using dump path %s", dump_path)

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
        add_einfra_user_task(email, einfra_id)
