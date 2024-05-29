import importlib
from unittest.mock import Mock

import jwt
from flask_login.utils import _create_identifier
from invenio_access.permissions import system_identity
from invenio_communities import current_communities
from invenio_communities.members.records.api import Member
from invenio_oauthclient.ext import InvenioOAuthClient
from invenio_search.engine import dsl

from oidc_einfra.communities import account_info_link_perun_groups, \
    get_user_aai_communities

# userinfo url 'https://login.cesnet.cz/oidc/'


def get_user_community_roles(user_id):
    Member.index.refresh()
    members_service = current_communities.service.members
    search = members_service._search(
        "search",
        system_identity,
        {},
        None,
        extra_filter=dsl.Q("term", **{"user.id": str(user_id)}),
    )
    result = search.execute()
    ret = []
    for hit in result:
        ret.append((hit["community_id"], hit["role"]))
    return ret


def token_getter_mock(remote, token=""):
    return ["token"]


def set_remote(return_userinfo_fixture, monkeypatch):
    remote = Mock()
    remote.consumer_key = "333e0e21-83bc-414f-bb4c-6df622fc1331"
    remote.base_url = "https://login.cesnet.cz/oidc/"

    remote.get.side_effect = return_userinfo_fixture
    module = importlib.import_module("cesnet_openid_remote.communities")
    monkeypatch.setattr(module, "token_getter", token_getter_mock)
    return remote


def test_adding_groups(
    db,
    community_with_aai_mapping_cf,
    users,
    return_userinfo_both,
    monkeypatch,
    search_clear,
):
    remote = set_remote(return_userinfo_both, monkeypatch)
    user = users["curator"]

    roles_before = get_user_community_roles(user.id)

    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )

    roles_after = get_user_community_roles(user.id)
    assert len(roles_before) == 0
    assert len(roles_after) == 1
    assert roles_after[0][1] == "curator"

    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )
    roles_after_repeat = get_user_community_roles(user.id)
    assert len(roles_after_repeat) == 1
    assert roles_after_repeat[0][1] == "curator"


def test_remove_groups(
    db,
    community_with_aai_mapping_cf,
    users,
    return_userinfo_curator,
    return_userinfo_noone,
    monkeypatch,
    search_clear,
):
    remote = set_remote(return_userinfo_curator, monkeypatch)
    user = users["curator"]

    roles_before = get_user_community_roles(user.id)

    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )

    roles_after = get_user_community_roles(user.id)
    assert len(roles_before) == 0
    assert len(roles_after) == 1
    assert roles_after[0][1] == "curator"

    remote.get.side_effect = return_userinfo_noone
    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )
    roles_after_perun_deletion = get_user_community_roles(user.id)
    assert len(roles_after_perun_deletion) == 0


def test_two_communities(
    db,
    community_with_aai_mapping_cf,
    community2_with_aai_mapping_cf,
    users,
    return_userinfo_two_communities,
    return_userinfo_noone,
    monkeypatch,
    search_clear,
):
    remote = set_remote(return_userinfo_two_communities, monkeypatch)
    user = users["curator"]

    roles_before = get_user_community_roles(user.id)

    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )

    roles_after = get_user_community_roles(user.id)
    assert len(roles_before) == 0
    assert len(roles_after) == 2

    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )
    roles_after_repeat = get_user_community_roles(user.id)
    assert len(roles_after_repeat) == 2

    remote.get.side_effect = return_userinfo_noone
    account_info_link_perun_groups(
        remote,
        token=None,
        response=None,
        account_info={"user": {"email": "curator@curator.org"}},
    )
    roles_after_perun_deletion = get_user_community_roles(user.id)
    assert len(roles_after_perun_deletion) == 0


def test_aai_mapping_group_facet(
    db, community_with_aai_mapping_cf, community2_with_aai_mapping_cf, search_clear
):
    # todo doesn't seem to work correctly for now, returns communities without queried roles too
    mapped_communities = get_user_aai_communities(
        {
            "alt_test_community:curator",
        }
    )
    assert len(mapped_communities) == 1


class MockSerializer:
    def loads(self, token):
        return {
            "sid": _create_identifier(),
            "app": "eduid",
            "next": "https://127.0.0.1:5000/",
        }


id_token_unregistered = {
    "sub": "noonenobodynothing",
    "email_verified": False,
    "preferred_username": "nobody",
    "given_name": "noone",
    "locale": "cs",
    "auth_time": 3,
    "name": "nobody noone",
    "family_name": "noone",
    "email": "nobody@noone.nope",
}


def test_user_unregistered(
    db,
    app,
    community_with_aai_mapping_cf,
    users,
    return_userinfo_both,
    monkeypatch,
    client,
    search_clear,
):
    InvenioOAuthClient(app)
    module = importlib.import_module("invenio_oauthclient.views.client")
    monkeypatch.setattr(module, "serializer", MockSerializer())

    # todo pozn. autocreate_user is called before linking perun groups and crashes if external id is not provided in id token
    # the get oauth_get_user function uses it to get the user, therefore i can't find a way to not get user in account_info_link_perun_groups without directly hacking it
    module = importlib.import_module("cesnet_openid_remote.communities")
    monkeypatch.setattr(
        module, "oauth_get_user", lambda a, account_info, access_token: None
    )
    monkeypatch.setattr(
        module, "get_user_perun_groups", lambda x: ["test_community:curator"]
    )

    from flask_oauthlib.client import OAuthRemoteApp

    monkeypatch.setattr(
        OAuthRemoteApp,
        "handle_oauth2_response",
        lambda self, x: {
            "access_token": "lalala",
            "token_type": "Bearer",
            "expires_in": 3599,
            "scope": "lalala",
            "id_token": jwt.encode(id_token_unregistered, ""),
        },
    )
    res = client.get("/oauth/authorized/eduid/?code=dxuW0cqdD2CW&state=eyJhbGci")
    user_id = len(users) + 1
    roles = get_user_community_roles(user_id)
    assert len(roles) == 1
