from collections import defaultdict
from typing import Dict, Set

from flask import abort
from invenio_access.permissions import system_identity
from invenio_communities import current_communities
from invenio_oauthclient.handlers.token import token_getter
from invenio_oauthclient.oauth import oauth_get_user
from invenio_search.engine import dsl


def get_user_community_roles(user) -> Dict[str, Set[str]]:
    members_service = current_communities.service.members
    search = members_service._search(
        "search",
        system_identity,
        {},
        None,
        extra_filter=dsl.Q("term", **{"user.id": str(user.id)}),
    )

    result = search.execute()
    ret = defaultdict(set)
    for hit in result:
        ret[hit["community_id"]].add(hit["role"])
    return ret


def get_user_perun_groups(remote):
    user_info = remote.get(f"{remote.base_url}userinfo")
    try:
        return set(user_info.data["eduperson_entitlement"])
    except (AttributeError, KeyError):
        return set()


def add_user_community_membership(community_id, community_role, user):
    data = {
        "role": community_role,
        "members": [{"type": "user", "id": str(user.id)}],
    }
    current_communities.service.members.add(system_identity, community_id, data)


def get_mapped_communities(perun_groups):
    communities = current_communities.service.scan(
        system_identity, params={"facets": {"aai_mapping_group": perun_groups}}
    )
    ret = {}
    for community in communities:
        aai_mapping = community.get("custom_fields", {}).get("aai_mapping")
        if aai_mapping:
            ret[community["id"]] = aai_mapping
    return ret


def remove_user_community_membership(community_id, user):
    data = {"members": [{"type": "user", "id": str(user.id)}]}
    current_communities.service.members.delete(system_identity, community_id, data)


def split_user_roles(mapping, current_roles, perun_groups):
    kept_roles = set()
    added_roles = set()
    for entry in mapping:
        if entry["aai_group"] in perun_groups:
            role = entry["role"]
            if role not in current_roles:
                added_roles.add(role)
            else:
                kept_roles.add(role)
    removed_roles = current_roles - kept_roles
    return kept_roles, added_roles, removed_roles


def account_info_link_perun_groups(remote, *, account_info, **kwargs):
    user = oauth_get_user(
        remote.consumer_key,
        account_info=account_info,
        access_token=token_getter(remote)[0],
    )

    if user is not None:
        return link_perun_groups(remote, user)


def link_perun_groups(remote, user):
    user_community_roles = get_user_community_roles(user)
    perun_groups = get_user_perun_groups(remote)
    communities = get_mapped_communities(perun_groups)

    # add part
    for community_id, mapping in communities.items():
        kept_roles, added_roles, removed_roles = split_user_roles(
            mapping, user_community_roles.pop(community_id, set()), perun_groups
        )
        if len(kept_roles) + len(added_roles) > 1:
            abort(
                403,
                f"User cannot be in multiple roles: {kept_roles | added_roles}",
            )
        if removed_roles:
            remove_user_community_membership(community_id, user)
            added_roles.update(kept_roles)
        for role in added_roles:
            add_user_community_membership(community_id, role, user)

    for community_id in user_community_roles:
        remove_user_community_membership(community_id, user)
