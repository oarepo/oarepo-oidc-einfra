#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Background tasks."""

from __future__ import annotations

import json
import logging
from io import BytesIO
from itertools import chain, islice
from typing import TYPE_CHECKING, Iterable, Literal
from urllib.parse import urljoin

import boto3
from celery import shared_task
from flask import current_app, url_for
from invenio_accounts.models import User
from invenio_communities.communities.records.api import Community
from invenio_communities.members.records.api import Member
from invenio_db import db
from invenio_requests.records.api import Request

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
    community = Community.pid.resolve(community_id)
    slug = community.slug
    roles = current_app.config["COMMUNITIES_ROLES"]

    api = current_einfra_oidc.perun_api()

    group, resource = map_community_or_role(
        api,
        parent_id=current_app.config["EINFRA_COMMUNITIES_GROUP_ID"],
        parent_vo=current_app.config["EINFRA_REPOSITORY_VO_ID"],
        name=f"Community {slug}",
        description=community.metadata.get("description")
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
            parent_vo=current_app.config["EINFRA_REPOSITORY_VO_ID"],
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
        vo_id=current_app.config["EINFRA_REPOSITORY_VO_ID"],
        facility_id=current_app.config["EINFRA_REPOSITORY_FACILITY_ID"],
        group_id=group["id"],
        name=resource_name,
        description=resource_description,
        capability_attr_id=current_app.config["EINFRA_CAPABILITIES_ATTRIBUTE_ID"],
        capabilities=resource_capabilities,
        perun_sync_service_id=current_app.config["EINFRA_SYNC_SERVICE_ID"],
    )
    return group, resource


@shared_task
def synchronize_all_communities_to_perun() -> None:
    """Check and repair community mapping within perun."""
    for community_model in Community.model_cls.query.all():
        synchronize_community_to_perun(str(community_model.id))


@shared_task
@mutex("EINFRA_SYNC_MUTEX")
def update_from_perun_dump(
    dump_path: str, fix_communities_in_perun: bool = True
) -> None:
    """Update user communities from perun dump and propagate local communities that are not in perun yet.

    The dump with perun data is downloaded from the S3 storage and the users are synchronized
    with the database.

    Note: we suppose that the dump is small enough to be processed in a single task and the processing
    will take less than 1 hour (the default task timeout inside the mutex).

    :param dump_path:        url with the dump
    :param fix_communities_in_perun     if some local communities were not propagated to perun, propagate them
    """
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
        data = json.loads(obj.getvalue().decode("utf-8"))

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
    print([aai_user.email for aai_user in dump.users()])
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
            db.session.query(User)
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
            print("Setting user", user, aai_user.roles)
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
        db.session.add(user)
        db.session.commit()


@shared_task
def create_aai_invitation(request_id: str) -> dict | None:
    """Create an invitation in AAI for an invenio invitation request.

    :param request_id:  id of the invenio invitation request
    :return:            invitation data as returned from perun
    """
    perun_api = current_einfra_oidc.perun_api()

    request = Request.get_record(request_id)
    invitation = Member.get_member_by_request(request_id)

    capability = get_perun_capability_from_invenio_role(
        request.topic.slug, invitation.role
    )
    group = perun_api.get_resource_by_capability(
        vo_id=current_app.config["EINFRA_REPOSITORY_VO_ID"],
        facility_id=current_app.config["EINFRA_REPOSITORY_FACILITY_ID"],
        capability=capability,
    )

    if not group:
        log.error(
            f"Resource for capability {capability} not found inside Perun, "
            f"so can not send invitation to its associated group."
        )
        return None

    encrypted_request_id = encrypt(request_id)

    redirect_url = urljoin(
        f'https://{current_app.config["SERVER_NAME"]}',
        url_for(
            "oarepo_oidc_einfra.invitation_redirect", request_id=encrypted_request_id
        ),
    )

    email = invitation.user.email
    return perun_api.send_invitation(
        vo_id=current_app.config["EINFRA_REPOSITORY_VO_ID"],
        group_id=group["id"],
        email=email,
        fullName=invitation.user.user_profile.get("full_name", email),
        language=current_app.config["EINFRA_DEFAULT_INVITATION_LANGUAGE"],
        expiration=request.expires_at.date().isoformat(),
        redirect_url=redirect_url,
    )


@shared_task
def change_aai_role(community_slug: str, user_id: int, new_role: str) -> None:
    """Propagate changed community role to AAI.

    :param community_slug:  community slug
    :param user_id:         user id     (internal)
    :param new_role:        new role name
    """
    remove_aai_user_from_community(community_slug, user_id)
    add_aai_role(community_slug, user_id, new_role)


@shared_task
def remove_aai_user_from_community(community_slug: str, user_id: int) -> None:
    """Remove user from perun group representing a community.

    :param community_slug:  community slug
    :param user_id:         user id
    """
    for role in CommunitySupport().role_names:
        aai_group_op("remove_user_from_group", community_slug, user_id, role)


@shared_task
def add_aai_role(community_slug: str, user_id: int, role: str) -> None:
    """Add user to perun group representing a community and a role.

    :param community_slug:  community slug
    :param user_id:         user id
    :param role:            role name
    """
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
        vo_id=current_app.config["EINFRA_REPOSITORY_VO_ID"],
        facility_id=current_app.config["EINFRA_REPOSITORY_FACILITY_ID"],
        capability=get_perun_capability_from_invenio_role(community_slug, role),
    )
    if resource is None:
        log.error(
            f"Resource for {community_slug} and role {role} not found inside Perun, "
            f"so can not remove user from its associated group."
        )
        return

    user = perun_api.get_user_by_attribute(
        attribute_name=current_app.config["EINFRA_USER_EINFRAID_ATTRIBUTE"],
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
        getattr(perun_api, op)(user["id"], group["id"])
