import copy
import os
from unittest.mock import Mock

import pytest
from invenio_access.permissions import system_identity
from invenio_app.factory import create_api
from invenio_communities.cli import create_communities_custom_field
from invenio_communities.communities.records.api import Community
from invenio_communities.proxies import current_communities
from oarepo_communities.cf.aai import AAIMappingCF

from oidc_einfra import remote


@pytest.fixture(scope="module")
def create_app(instance_path, entry_points):
    """Application factory fixture."""

    return create_api


@pytest.fixture(scope="module")
def community_service(app):
    """Community service."""
    return current_communities.service


@pytest.fixture(scope="module")
def member_service(community_service):
    """Members subservice."""
    return community_service.members


@pytest.fixture(scope="module")
def app_config(app_config):
    # Custom fields
    app_config["JSONSCHEMAS_HOST"] = "localhost"
    app_config[
        "RECORDS_REFRESOLVER_CLS"
    ] = "invenio_records.resolver.InvenioRefResolver"
    app_config[
        "RECORDS_REFRESOLVER_STORE"
    ] = "invenio_jsonschemas.proxies.current_refresolver_store"

    app_config["COMMUNITIES_CUSTOM_FIELDS"] = [
        AAIMappingCF("aai_mapping"),
    ]
    app_config["SEARCH_HOSTS"] = [
        {
            "host": os.environ.get("OPENSEARCH_HOST", "localhost"),
            "port": os.environ.get("OPENSEARCH_PORT", "9200"),
        }
    ]

    app_config["CACHE_TYPE"] = "SimpleCache"  # Flask-Caching related configs
    app_config["CACHE_DEFAULT_TIMEOUT"] = 300

    app_config["OAUTHCLIENT_REMOTE_APPS"] = {"eduid": remote.REMOTE_APP}
    app_config["PERUN_APP_CREDENTIALS_CONSUMER_KEY"] = "lalala"
    return app_config


@pytest.fixture(scope="function")
def minimal_community():
    """Minimal community metadata."""
    return {
        "access": {
            "visibility": "public",
            "record_policy": "open",
        },
        "slug": "public",
        "metadata": {
            "title": "My Community",
        },
    }


@pytest.fixture(scope="function")
def minimal_community2(minimal_community):
    edited = copy.deepcopy(minimal_community)
    edited["slug"] = "comm2"
    return edited


@pytest.fixture(scope="module")
def users(UserFixture, app, database):
    """Users."""
    users = {}
    for r in ["owner", "manager", "curator", "reader"]:
        u = UserFixture(
            email=f"{r}@{r}.org",
            password=r,
            username=r,
            user_profile={
                "full_name": f"{r} {r}",
                "affiliations": "CERN",
            },
            preferences={
                "visibility": "public",
                "email_visibility": "restricted",
            },
            active=True,
            confirmed=True,
        )
        u.create(app, database)
        users[r] = u
    # when using `database` fixture (and not `db`), commit the creation of the
    # user because its implementation uses a nested session instead
    database.session.commit()
    return users


@pytest.fixture(scope="module")
def community_factory(community_service):
    def _community(identity, community_dict):
        c = community_service.create(identity, community_dict)
        Community.index.refresh()
        return c

    return _community


@pytest.fixture(scope="function")
def community(community_factory, users, community_service, minimal_community, location):
    return community_factory(users["owner"].identity, minimal_community)


@pytest.fixture(scope="function")
def community2(
    community_factory, users, community_service, minimal_community2, location
):
    """A community."""
    return community_factory(users["owner"].identity, minimal_community2)


@pytest.fixture(scope="function")
def init_cf(base_app):
    result = base_app.test_cli_runner().invoke(
        create_communities_custom_field, ["-f", "aai_mapping"]
    )
    assert result.exit_code == 0
    Community.index.refresh()


@pytest.fixture(scope="module")
def aai_mapping_example_dict():
    return [{"role": "curator", "aai_group": "test_community:curator"}]


@pytest.fixture(scope="function")
def community_with_aai_mapping_cf(
    users,
    community_service,
    community,
    minimal_community,
    aai_mapping_example_dict,
    init_cf,
):
    minimal_community["custom_fields"]["aai_mapping"] = aai_mapping_example_dict
    community = community_service.update(
        system_identity, community["id"], minimal_community
    )
    Community.index.refresh()
    return community


@pytest.fixture(scope="function")
def community2_with_aai_mapping_cf(
    users,
    community_service,
    community2,
    minimal_community2,
    aai_mapping_example_dict,
    init_cf,
):
    edited = copy.deepcopy(aai_mapping_example_dict)
    edited.append({"role": "curator", "aai_group": "alt_test_community:curator"})
    minimal_community2["custom_fields"]["aai_mapping"] = edited
    community = community_service.update(
        system_identity, community2["id"], minimal_community2
    )
    Community.index.refresh()
    return community


@pytest.fixture
def return_userinfo_curator():
    def _return_userinfo(val):
        if val == "https://login.cesnet.cz/oidc/userinfo":
            usrinfo_obj = Mock()
            usrinfo_obj.data = {"eduperson_entitlement": ["test_community:curator"]}
            return usrinfo_obj

    return _return_userinfo


@pytest.fixture
def return_userinfo_two_communities():
    def _return_userinfo(val):
        if val == "https://login.cesnet.cz/oidc/userinfo":
            usrinfo_obj = Mock()
            usrinfo_obj.data = {
                "eduperson_entitlement": [
                    "test_community:curator",
                    "alt_test_community:curator",
                ]
            }
            return usrinfo_obj

    return _return_userinfo


@pytest.fixture
def return_userinfo_both():
    def _return_userinfo(val):
        if val == "https://login.cesnet.cz/oidc/userinfo":
            usrinfo_obj = Mock()
            usrinfo_obj.data = {
                "eduperson_entitlement": [
                    "test_community:curator",
                    "test_community:reader",
                ]
            }
            return usrinfo_obj

    return _return_userinfo


@pytest.fixture
def return_userinfo_noone():
    def _return_userinfo(val):
        if val == "https://login.cesnet.cz/oidc/userinfo":
            usrinfo_obj = Mock()
            usrinfo_obj.data = {"eduperson_entitlement": []}
            return usrinfo_obj

    return _return_userinfo
