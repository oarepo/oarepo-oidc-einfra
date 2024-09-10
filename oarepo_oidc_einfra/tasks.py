#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""
Background tasks.
"""
import json
import logging
from typing import List, Tuple

from celery import shared_task
from flask import current_app
from invenio_accounts.models import User
from invenio_communities.communities.records.api import Community
from invenio_db import db
from invenio_files_rest.storage import PyFSFileStorage

from oarepo_oidc_einfra.communities import CommunitySupport
from oarepo_oidc_einfra.mutex import mutex
from oarepo_oidc_einfra.perun.dump import PerunDumpData
from oarepo_oidc_einfra.perun.oidc import einfra_to_local_users_map
from oarepo_oidc_einfra.proxies import current_einfra_oidc

log = logging.getLogger("PerunSynchronizationTask")


@shared_task
@mutex("EINFRA_SYNC_MUTEX")
def synchronize_community_to_perun(community_id) -> None:
    """
    Synchronizes community into Perun groups and resources.
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
        name=f"Community {slug}",
        description=community.metadata["description"] or f"Group for community {slug}",
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
            resource_name=f"Community:{slug}:{role_name}",
            resource_description=f"Resource for community {slug} and role {role_name}",
            resource_capabilities=[f"res:communities:{slug}:role:{role_name}"],
        )


def map_community_or_role(
    api,
    *,
    parent_id,
    name,
    description,
    resource_name,
    resource_description,
    resource_capabilities,
):
    """
    Map a single community or community role, adds synchronization service so that we get
    the resource in the dump from perun.

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
        name=name, description=description, parent_group_id=parent_id
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
def synchronize_all_communities_to_perun():
    """
    Checks and repairs community mapping within perun
    """
    for community_model in Community.model_cls.query.all():
        synchronize_community_to_perun(str(community_model.id))


@shared_task
@mutex("EINFRA_SYNC_MUTEX")
def update_from_perun_dump(dump_url, fix_communities_in_perun=True):
    """
    Updates user communities from perun dump and checks for local communities
    not propagated to perun yet (and propagates them)

    :param dump_url:        url with the dump
    :param fix_communities_in_perun     if some local communities were not propagated to perun, propagate them
    """
    location = PyFSFileStorage(dump_url)
    with location.open() as f:
        data = json.load(f)

    community_support = CommunitySupport()
    dump = PerunDumpData(
        data, community_support.slug_to_id, community_support.role_names
    )

    if fix_communities_in_perun:
        synchronize_communities_to_perun(
            community_support.all_community_roles, dump.aai_community_roles
        )

    synchronize_users_from_perun(dump, community_support)


def synchronize_communities_to_perun(repository_community_roles, aai_community_roles):
    resource_community_roles: List[Tuple[str, str]]

    if repository_community_roles - aai_community_roles:
        log.info(
            "Some community roles are not mapped "
            f"to any resource: {repository_community_roles - aai_community_roles}"
        )
        unsynchronized_communities = {
            cr.community_id for cr in repository_community_roles - aai_community_roles
        }
        for community_id in unsynchronized_communities:
            synchronize_community_to_perun.delay(community_id)


def synchronize_users_from_perun(dump, community_support):
    local_users_by_einfra = einfra_to_local_users_map()
    for aai_user in dump.users():
        local_user_id = local_users_by_einfra.pop(aai_user.einfra_id, None)
        # do not create new users proactively, we can do it on the first login
        if not local_user_id:
            continue

        user = User.query.filter_by(id=local_user_id).one()

        update_user_metadata(
            user, aai_user.full_name, aai_user.email, aai_user.organization
        )
        community_support.set_user_community_membership(user, aai_user.roles)
    # for users that are not in the dump anymore, remove all communities
    for local_user_id in local_users_by_einfra.values():
        user = User.query.filter_by(id=local_user_id).one()
        community_support.set_user_community_membership(user, set())


def update_user_metadata(user, full_name, email, organization):
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
def create_aai_invitation(request_id):
    raise NotImplementedError("This task is not implemented yet, waiting on PERUN API.")


@shared_task
def change_aai_role(community_slug, user_id, role):
    raise NotImplementedError("This task is not implemented yet, waiting on PERUN API.")
