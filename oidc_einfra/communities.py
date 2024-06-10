from collections import namedtuple
from typing import Set

from flask import current_app
from invenio_access.permissions import system_identity
from invenio_communities import current_communities
from invenio_communities.members.records.models import MemberModel
from invenio_db import db
from invenio_oauthclient.handlers.token import token_getter
from invenio_oauthclient.oauth import oauth_get_user
from marshmallow import ValidationError
from sqlalchemy import select

from oidc_einfra.models import CommunityAAIMapping
from oidc_einfra.proxies import current_einfra_oidc
from urnparse import URN8141


def account_info_link_perun_groups(remote, *, account_info, **kwargs):
    user = oauth_get_user(
        remote.consumer_key,
        account_info=account_info,
        access_token=token_getter(remote)[0],
    )
    external_id = account_info["external_id"]

    if user is None:
        return

    user_community_roles = get_user_repository_communities(user)
    aai_community_roles = get_user_aai_communities(remote)

    for community_id, role in aai_community_roles - user_community_roles:
        add_user_community_membership(community_id, role, user)

    for community_id, role in user_community_roles - aai_community_roles:
        try:
            remove_user_community_membership(community_id, role, user)
        except ValidationError as e:
            # This is a case when the user is the last member of a community - in this case he can not be removed
            current_app.logger.error(
                f"Failed to remove user {user.id} from community {community_id}: {e}"
            )


CommunityRole = namedtuple("CommunityRole", ["community_id", "role"])


def get_user_repository_communities(user) -> Set[CommunityRole]:
    ret = set()
    for row in db.session.execute(
        select([MemberModel.community_id, MemberModel.role]).where(
            MemberModel.user_id == user.id
        )
    ):
        ret.add(CommunityRole(row.community_id, row.role))
    return ret


def get_user_aai_communities(remote) -> Set[CommunityRole]:
    userinfo = remote.get(remote.base_url + "userinfo").data
    extended_entitlements = userinfo.get("eduperson_entitlement_extended", [])
    aai_groups = []
    for entitlement in extended_entitlements:
        urn = URN8141.from_string(entitlement)
        if urn.namespace_id.value not in current_app.config["EINFRA_ENTITLEMENT_NAMESPACES"]:
            continue
        for group_parts in current_app.config["EINFRA_ENTITLEMENT_GROUP_PARTS"]:
            if urn.specific_string.parts[:len(group_parts)] == group_parts and len(urn.specific_string.parts) > len(group_parts):
                aai_groups.append(urn.specific_string.parts[len(group_parts)])
        # specific_string.parts: ['cesnet.cz', 'group', '74319f37-4f11-4897-b9df-5458c956309b']

    mappings = CommunityAAIMapping.query.filter(
        CommunityAAIMapping.aai_group_uuid.in_(aai_groups)
    ).all()
    return {CommunityRole(mapping.community_id, mapping.role) for mapping in mappings}


def get_user_aai_groups(einfra_id, access_token):
    aai = current_einfra_oidc.aai_api(access_token=access_token)
    vo = aai.vos[current_app.config["EINFRA_REPOSITORY_VO"]]
    einfra_user = aai.users.get(einfra_id=einfra_id)
    user_groups = vo.user_groups(einfra_user)
    return set(x.uuid for x in user_groups.values())


def add_user_community_membership(community_id, community_role, user):
    data = {
        "role": community_role,
        "members": [{"type": "user", "id": str(user.id)}],
    }
    current_communities.service.members.add(system_identity, community_id, data)


def remove_user_community_membership(community_id, community_role, user):
    # TODO: BUG: this does not take role into account
    data = {"members": [{"type": "user", "id": str(user.id)}]}
    current_communities.service.members.delete(system_identity, community_id, data)
