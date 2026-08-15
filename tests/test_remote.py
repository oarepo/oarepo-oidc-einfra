# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for oarepo_oidc_einfra/remote.py.

The overall approach mirrors invenio-oauthclient's own contrib tests (see e.g.
``tests/test_contrib_github.py`` and ``tests/test_contrib_eosc_aai.py`` in that project):
a real RSA-signed id_token is decoded by ``account_info_serializer``/``account_setup``,
and the ``account_info_received`` signal handlers (``autocreate_user``,
``account_info_link_perun_groups``) are exercised directly and, for the core signup path,
through the real ``invenio_oauthclient`` login/authorized views.
"""

from __future__ import annotations

import datetime
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import url_for
from invenio_accounts.models import User, UserIdentity
from invenio_communities.members.records.models import CommunityMetadata
from invenio_db import db
from invenio_oauthclient._compat import _create_identifier
from invenio_oauthclient.models import RemoteAccount, RemoteToken
from invenio_oauthclient.proxies import current_oauthclient
from invenio_oauthclient.views.client import serializer as state_serializer

from oarepo_oidc_einfra.perun.entitlements import CommunityEntitlement, GlobalRoleEntitlement
from oarepo_oidc_einfra.remote import (
    BACKEND_NAME,
    EInfraOAuthSettingsHelper,
    EINFRA_LOGIN_APP,
    account_info,
    account_info_link_perun_groups,
    account_info_serializer,
    account_setup,
    autocreate_user,
    find_locale,
    get_entitlements_from_userinfo_token,
)

GROUP_PREFIX = "urn:geant:cesnet.cz:group:"
RES_PREFIX = "urn:geant:cesnet.cz:res:"
CESNET_SUFFIX = "#perun.cesnet.cz"

USERINFO_TOKEN = {
    "sub": "9f3a7c2e1b6d4f80a5c3e9b7d2f4a6c8e0b1d3f5@einfra.cesnet.cz",
    "name": "Alex Testperson",
    "preferred_username": "testperson01",
    "given_name": "Alex",
    "family_name": "Testperson",
    "zoneinfo": "Europe/Prague",
    "locale": "cs",
    "email": "testperson01@example.org",
    "email_verified": True,
    "organization": "Example Research Organization",
    "eduperson_entitlement": [
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20ben8:Role%20member%20of%20ben8" + CESNET_SUFFIX,
        RES_PREFIX + "testing_nrp_devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:4eqq:role:member" + CESNET_SUFFIX,
        "https://example.org/ns/user-eligible-v1",
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%204eqq:Role%20member%20of%204eqq" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20uxbx:Role%20member%20of%20uxbx" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20uxbx" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200w0h:Role%20member%20of%200w0h" + CESNET_SUFFIX,
        RES_PREFIX + "communities:efbe:role:member" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20ben8" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test-nrp-devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0w0h:role:member" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0w0h" + CESNET_SUFFIX,
        "urn:mace:example.org:tcs:personal-user",
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d:Role%20member%20of%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200w0h" + CESNET_SUFFIX,
        RES_PREFIX + "communities:ben8:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%204eqq" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d:role:submitter" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20efbe:Role%20member%20of%20efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:ben8" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d:"
        "Role%20submitter%20of%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "example.org:RPs-test-services:nrp-devel" + CESNET_SUFFIX,
        RES_PREFIX + "communities:uxbx:role:member" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%200d9d" + CESNET_SUFFIX,
        GROUP_PREFIX + "VO_test_org:test_group:communities:Community%20efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:0d9d" + CESNET_SUFFIX,
        RES_PREFIX + "communities:4eqq" + CESNET_SUFFIX,
        RES_PREFIX + "communities:efbe" + CESNET_SUFFIX,
        RES_PREFIX + "communities:uxbx" + CESNET_SUFFIX,
    ],
}


@pytest.fixture
def known_communities(app, db):
    """Create the subset of communities from USERINFO_TOKEN that are known locally."""
    communities = [CommunityMetadata(slug=slug) for slug in ("efbe", "0d9d")]
    for community in communities:
        db.session.add(community)
    db.session.flush()

    return communities


def test_get_entitlements_from_userinfo_token_only_returns_known_community_roles(app, known_communities):
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert entitlements == {
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:efbe:role:member" + CESNET_SUFFIX,
            community_slug="efbe",
            role="member",
        ),
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:0d9d:role:member" + CESNET_SUFFIX,
            community_slug="0d9d",
            role="member",
        ),
    }


def test_get_entitlements_from_userinfo_token_ignores_unknown_communities(app):
    # none of the communities in USERINFO_TOKEN exist locally in this test
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert entitlements == set()


def test_get_entitlements_from_userinfo_token_ignores_unknown_roles(app, known_communities):
    # "0d9d:role:submitter" is present in the token, but "submitter" is not a role
    # configured in COMMUNITIES_ROLES, so it must be silently ignored
    entitlements = get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    assert all(e.role != "submitter" for e in entitlements if hasattr(e, "role"))


def test_get_entitlements_from_userinfo_token_with_no_entitlement_claim(app):
    assert get_entitlements_from_userinfo_token({}) == set()


def test_get_entitlements_from_userinfo_token_logs_by_exception_type(app, known_communities, caplog):
    with caplog.at_level(logging.DEBUG, logger="oarepo_oidc_einfra.perun.remote"):
        get_entitlements_from_userinfo_token(USERINFO_TOKEN)

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    info_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]

    # group entitlements and "res:testing_nrp_devel" have a type we do not recognize at
    # all - routine and expected for every user, so logged at debug
    assert any("testing_nrp_devel" in m for m in debug_messages)
    assert any("group" in m for m in debug_messages)

    # these look like entitlements we should understand (or almost do), but could not
    # be resolved - a malformed URL, a foreign namespace, an unknown community and an
    # unknown role - worth an info-level note
    assert any("user-eligible" in m for m in info_messages)
    assert any("personal-user" in m for m in info_messages)
    assert any("4eqq" in m for m in info_messages)
    assert any("submitter" in m for m in info_messages)

    assert not any("testing_nrp_devel" in m for m in info_messages)
    assert not any("Unknown community: 4eqq" in m for m in debug_messages)


# ---------------------------------------------------------------------------
# fixtures/helpers shared by the tests below
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app_config(app_config, rsa_keypair):
    """Register the e-infra remote app and its test RSA keypair."""
    _, public_pem = rsa_keypair
    app_config["OAUTHCLIENT_REMOTE_APPS"] = {"e-infra": EINFRA_LOGIN_APP}
    # flask_oauthlib resolves consumer_key/consumer_secret/rsa_key for a remote app with
    # app_key="EINFRA" from flat EINFRA_<PROPERTY> config keys (see OAuthRemoteApp._get_property)
    app_config["EINFRA_CONSUMER_KEY"] = "test-consumer-key"
    app_config["EINFRA_CONSUMER_SECRET"] = "test-consumer-secret"  # noqa S105
    app_config["EINFRA_RSA_KEY"] = public_pem
    app_config["I18N_LANGUAGES"] = [("cs", "Czech"), ("en_GB", "British English")]
    return app_config


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a throw-away RSA keypair used to sign/verify test id_tokens."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _make_id_token(private_pem, **overrides):
    """Build a signed RS256 id_token, as e-infra AAI would return it."""
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "abcdef1234@einfra.cesnet.cz",
        "name": "Jane Doe",
        "email": "jane.doe@example.org",
        "locale": "cs",
        "zoneinfo": "Europe/Prague",
        "aud": "test-consumer-key",
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_pem, algorithm="RS256")


def _fake_remote(public_pem, *, name=BACKEND_NAME, consumer_key="test-consumer-key", **extra):
    return SimpleNamespace(name=name, rsa_key=public_pem, consumer_key=consumer_key, **extra)


# ---------------------------------------------------------------------------
# find_locale
# ---------------------------------------------------------------------------


def test_find_locale_returns_exact_match(app):
    assert find_locale("cs") == "cs"


def test_find_locale_returns_prefix_match(app):
    # "en" is not itself in I18N_LANGUAGES, but "en_GB" starts with it
    assert find_locale("en") == "en_GB"


def test_find_locale_falls_back_to_default_for_unsupported_locale(app):
    assert find_locale("de") == app.config["BABEL_DEFAULT_LOCALE"]


def test_find_locale_falls_back_to_default_for_none(app):
    assert find_locale(None) == app.config["BABEL_DEFAULT_LOCALE"]


# ---------------------------------------------------------------------------
# EInfraOAuthSettingsHelper
# ---------------------------------------------------------------------------


def test_get_rest_handlers_returns_rest_handlers():
    helper = EInfraOAuthSettingsHelper()
    handlers = helper.get_rest_handlers()

    assert handlers["signup_handler"]["info"] == "oarepo_oidc_einfra.remote:account_info"
    assert handlers["signup_handler"]["setup"] == "oarepo_oidc_einfra.remote:account_setup"


# ---------------------------------------------------------------------------
# account_info_serializer / account_info
# ---------------------------------------------------------------------------


def test_account_info_serializer_decodes_id_token(app, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(
        private_pem,
        sub="hexhex@einfra.cesnet.cz",
        name="Alex Test",
        email="Alex@Example.ORG",
        locale="cs",
        zoneinfo="Europe/Prague",
    )

    result = account_info_serializer(remote, {"id_token": id_token})

    assert result == {
        "external_id": "hexhex@einfra.cesnet.cz",
        "external_method": BACKEND_NAME,
        "user": {
            "username": "einfra-cesnet-cz-hexhex",
            "email": "Alex@Example.ORG",
            "profile": {
                "full_name": "Alex Test",
                "locale": "cs",
                "timezone": "Europe/Prague",
            },
        },
    }


def test_account_info_serializer_falls_back_to_default_locale(app, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(private_pem, locale="unsupported-locale")

    result = account_info_serializer(remote, {"id_token": id_token})

    assert result["user"]["profile"]["locale"] == app.config["BABEL_DEFAULT_LOCALE"]


def test_account_info_serializer_username_without_at_sign(app, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(private_pem, sub="opaque-subject-without-at-sign")

    result = account_info_serializer(remote, {"id_token": id_token})

    assert result["external_id"] == "opaque-subject-without-at-sign"
    assert result["user"]["username"] == "opaque-subject-without-at-sign"


def test_account_info_serializer_rejects_wrong_audience(app, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(private_pem, aud="someone-else")

    with pytest.raises(jwt.InvalidAudienceError):
        account_info_serializer(remote, {"id_token": id_token})


def test_account_info_delegates_to_registered_info_serializer(app, rsa_keypair):
    # relies on OAUTHCLIENT_REMOTE_APPS (set in the module app_config fixture above) having
    # registered account_info_serializer as the "e-infra" info_serializer handler
    private_pem, public_pem = rsa_keypair
    remote = current_oauthclient.oauth.remote_apps[BACKEND_NAME]
    id_token = _make_id_token(private_pem, sub="delegate-test@einfra.cesnet.cz")

    result = account_info(remote, {"id_token": id_token})

    assert result["external_id"] == "delegate-test@einfra.cesnet.cz"


# ---------------------------------------------------------------------------
# account_setup
# ---------------------------------------------------------------------------


def _make_token(email):
    user = User(email=email, active=True)
    db.session.add(user)
    db.session.commit()
    token = RemoteToken.create(user.id, "test-consumer-key", "access-token", "secret")  # noqa S106
    return user, token


def test_account_setup_is_noop_for_other_remotes(app, database, rsa_keypair):
    _, public_pem = rsa_keypair
    user, token = _make_token("other-remote@example.org")
    remote = _fake_remote(public_pem, name="some-other-remote")

    account_setup(remote, token, {"id_token": "irrelevant"})

    assert token.remote_account.extra_data == {}
    assert UserIdentity.query.filter_by(id_user=user.id).count() == 0


def test_account_setup_creates_identity_and_confirms_user(app, database, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    user, token = _make_token("setup-new@example.org")
    assert user.confirmed_at is None
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(
        private_pem,
        sub="setupsub@einfra.cesnet.cz",
        name="Setup User",
        locale="cs",
        zoneinfo="Europe/Prague",
    )

    account_setup(remote, token, {"id_token": id_token})

    assert token.remote_account.extra_data == {
        "full_name": "Setup User",
        "locale": "cs",
        "timezone": "Europe/Prague",
    }
    identity = UserIdentity.query.filter_by(method=BACKEND_NAME, id="setupsub@einfra.cesnet.cz").one()
    assert identity.id_user == user.id
    assert user.confirmed_at is not None


def test_account_setup_does_not_duplicate_existing_identity(app, database, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    user, token = _make_token("setup-existing@example.org")
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(private_pem, sub="existingsub@einfra.cesnet.cz")

    account_setup(remote, token, {"id_token": id_token})
    account_setup(remote, token, {"id_token": id_token})

    assert UserIdentity.query.filter_by(method=BACKEND_NAME, id="existingsub@einfra.cesnet.cz").count() == 1


def test_account_setup_does_not_reset_confirmed_at(app, database, rsa_keypair):
    private_pem, public_pem = rsa_keypair
    user, token = _make_token("already-confirmed@example.org")
    confirmed_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    user.confirmed_at = confirmed_at
    db.session.add(user)
    db.session.commit()
    remote = _fake_remote(public_pem)
    id_token = _make_id_token(private_pem, sub="alreadyconfirmed@einfra.cesnet.cz")

    account_setup(remote, token, {"id_token": id_token})

    assert user.confirmed_at == confirmed_at


# ---------------------------------------------------------------------------
# autocreate_user
# ---------------------------------------------------------------------------


def test_autocreate_user_is_noop_for_other_remotes(app, database):
    remote = SimpleNamespace(name="some-other-remote")

    # should not raise even though account_info is missing/invalid for this remote
    autocreate_user(remote, account_info=None)


def test_autocreate_user_requires_account_info(app, database):
    remote = SimpleNamespace(name=BACKEND_NAME)

    with pytest.raises(ValueError, match="account_info is required"):
        autocreate_user(remote, account_info=None)


def _account_info(*, external_id, email, username, full_name="Full Name", locale="cs", timezone="Europe/Prague"):
    return {
        "external_id": external_id,
        "external_method": BACKEND_NAME,
        "user": {
            "username": username,
            "email": email,
            "profile": {"full_name": full_name, "locale": locale, "timezone": timezone},
        },
    }


def test_autocreate_user_creates_new_user_and_identity(app, database, search_clear):
    remote = SimpleNamespace(name=BACKEND_NAME)
    info = _account_info(
        external_id="newsub@einfra.cesnet.cz",
        email="New.User@Example.ORG",
        username="newuser1",
    )

    autocreate_user(remote, account_info=info)

    user = User.query.filter_by(email="new.user@example.org").one()
    assert user.username == "newuser1"
    assert user.user_profile["full_name"] == "Full Name"
    assert user.confirmed_at is not None
    identity = UserIdentity.query.filter_by(method=BACKEND_NAME, id="newsub@einfra.cesnet.cz").one()
    assert identity.id_user == user.id


def test_autocreate_user_attaches_identity_to_user_found_by_username(app, database, search_clear):
    existing = User(username="matchbyusername", email="matchbyusername@example.org", active=True)
    db.session.add(existing)
    db.session.commit()
    initial_count = User.query.count()

    remote = SimpleNamespace(name=BACKEND_NAME)
    info = _account_info(
        external_id="byusername@einfra.cesnet.cz",
        email="different-email@example.org",
        username="matchbyusername",
    )

    autocreate_user(remote, account_info=info)

    assert User.query.count() == initial_count
    identity = UserIdentity.query.filter_by(method=BACKEND_NAME, id="byusername@einfra.cesnet.cz").one()
    assert identity.id_user == existing.id


def test_autocreate_user_attaches_identity_to_user_found_by_email(app, database, search_clear):
    existing = User(username="uniqueusername1", email="matchbyemail@example.org", active=True)
    db.session.add(existing)
    db.session.commit()
    initial_count = User.query.count()

    remote = SimpleNamespace(name=BACKEND_NAME)
    info = _account_info(
        external_id="byemail@einfra.cesnet.cz",
        email="matchbyemail@example.org",
        username="a-completely-different-username",
    )

    autocreate_user(remote, account_info=info)

    assert User.query.count() == initial_count
    identity = UserIdentity.query.filter_by(method=BACKEND_NAME, id="byemail@einfra.cesnet.cz").one()
    assert identity.id_user == existing.id


def test_autocreate_user_updates_email_and_profile_for_existing_identity(app, database, search_clear):
    remote = SimpleNamespace(name=BACKEND_NAME)
    first_info = _account_info(
        external_id="repeat-login@einfra.cesnet.cz",
        email="old-email@example.org",
        username="repeatuser",
        full_name="Old Name",
    )
    autocreate_user(remote, account_info=first_info)
    user = User.query.filter_by(username="repeatuser").one()
    assert user.email == "old-email@example.org"

    second_info = _account_info(
        external_id="repeat-login@einfra.cesnet.cz",
        email="new-email@example.org",
        username="repeatuser",
        full_name="New Name",
    )
    autocreate_user(remote, account_info=second_info)

    db.session.refresh(user)
    assert user.email == "new-email@example.org"
    assert user.user_profile["full_name"] == "New Name"


def test_autocreate_user_does_not_steal_email_from_another_user(app, database, search_clear, caplog):
    other_user = User(username="emailowner", email="taken@example.org", active=True)
    db.session.add(other_user)
    db.session.commit()

    remote = SimpleNamespace(name=BACKEND_NAME)
    first_info = _account_info(
        external_id="conflict-login@einfra.cesnet.cz",
        email="conflict-user-original@example.org",
        username="conflictuser",
    )
    autocreate_user(remote, account_info=first_info)
    user = User.query.filter_by(username="conflictuser").one()

    second_info = _account_info(
        external_id="conflict-login@einfra.cesnet.cz",
        email="taken@example.org",
        username="conflictuser",
    )
    with caplog.at_level(logging.ERROR, logger="e_infra.audit"):
        autocreate_user(remote, account_info=second_info)

    db.session.refresh(user)
    # the email must NOT have been stolen from other_user
    assert user.email == "conflict-user-original@example.org"
    assert any("different user" in r.getMessage() for r in caplog.records)


def test_autocreate_user_raises_for_orphaned_identity(app, database, monkeypatch):
    remote = SimpleNamespace(name=BACKEND_NAME)
    info = _account_info(
        external_id="orphan@einfra.cesnet.cz",
        email="orphan@example.org",
        username="orphanuser",
    )

    orphaned_identity = SimpleNamespace(user=None)
    fake_query = MagicMock()
    fake_query.filter_by.return_value.one_or_none.return_value = orphaned_identity
    monkeypatch.setattr(UserIdentity, "query", fake_query)

    with pytest.raises(RuntimeError, match="has no associated user"):
        autocreate_user(remote, account_info=info)


# ---------------------------------------------------------------------------
# account_info_link_perun_groups
# ---------------------------------------------------------------------------


def test_account_info_link_perun_groups_is_noop_for_other_remotes(app, monkeypatch):
    import oarepo_oidc_einfra.remote as remote_module

    called = []
    monkeypatch.setattr(remote_module, "token_getter", lambda remote: called.append(True))

    remote = SimpleNamespace(name="some-other-remote")
    account_info_link_perun_groups(remote, account_info={})

    assert called == []


def test_account_info_link_perun_groups_requires_token(app, monkeypatch):
    import oarepo_oidc_einfra.remote as remote_module

    monkeypatch.setattr(remote_module, "token_getter", lambda remote: None)

    remote = SimpleNamespace(name=BACKEND_NAME)
    with pytest.raises(ValueError, match="Access token is required"):
        account_info_link_perun_groups(remote, account_info={})


def test_account_info_link_perun_groups_returns_early_if_no_local_user(app, monkeypatch):
    import oarepo_oidc_einfra.remote as remote_module

    monkeypatch.setattr(remote_module, "token_getter", lambda remote: ("access-token",))
    monkeypatch.setattr(remote_module, "oauth_get_user", lambda *args, **kwargs: None)

    def fail_if_called(url):
        raise AssertionError("remote.get should not be called if there is no local user")

    remote = SimpleNamespace(name=BACKEND_NAME, consumer_key="ck", base_url="https://example.org/", get=fail_if_called)
    # should not raise
    account_info_link_perun_groups(remote, account_info={})


def test_account_info_link_perun_groups_applies_entitlements(app, database, monkeypatch):
    import oarepo_oidc_einfra.remote as remote_module

    user = User(email="perun-link@example.org", active=True)
    db.session.add(user)
    db.session.commit()

    monkeypatch.setattr(remote_module, "token_getter", lambda remote: ("access-token",))
    monkeypatch.setattr(remote_module, "oauth_get_user", lambda *args, **kwargs: user)

    calls = []
    monkeypatch.setattr(
        remote_module,
        "update_user_entitlements",
        lambda user, entitlements, cause: calls.append((user, entitlements, cause)),
    )

    userinfo_response = SimpleNamespace(data=USERINFO_TOKEN)
    requested_urls = []

    def fake_get(url):
        requested_urls.append(url)
        return userinfo_response

    remote = SimpleNamespace(
        name=BACKEND_NAME,
        consumer_key="test-consumer-key",
        base_url="https://login.e-infra.cz/oidc/",
        get=fake_get,
    )

    account_info_link_perun_groups(remote, account_info={})

    assert requested_urls == ["https://login.e-infra.cz/oidc/userinfo"]
    assert len(calls) == 1
    called_user, entitlements, cause = calls[0]
    assert called_user is user
    assert cause == "login"
    # none of the communities in USERINFO_TOKEN exist locally in this test, so no
    # entitlement resolves - the important part is that the handler wired everything up
    assert entitlements == set()


def test_account_info_link_perun_groups_resolves_known_entitlements(
    app, database, known_communities, roles, monkeypatch
):
    """Test that community and global-role entitlements are actually parsed and resolved.

    Unlike the previous test (which only checks the wiring with an empty result), this one
    provisions real communities (via ``known_communities``: "efbe" and "0d9d") and a real
    global role (via ``roles``: "administration") and a userinfo token that references both,
    then asserts the handler resolves them into the exact expected Entitlement objects.
    """
    import oarepo_oidc_einfra.remote as remote_module

    user = User(email="perun-link-resolved@example.org", active=True)
    db.session.add(user)
    db.session.commit()

    monkeypatch.setattr(remote_module, "token_getter", lambda remote: ("access-token",))
    monkeypatch.setattr(remote_module, "oauth_get_user", lambda *args, **kwargs: user)

    calls = []
    monkeypatch.setattr(
        remote_module,
        "update_user_entitlements",
        lambda user, entitlements, cause: calls.append((user, entitlements, cause)),
    )

    # USERINFO_TOKEN already carries "communities:efbe:role:member" and
    # "communities:0d9d:role:member" (plus a bunch of noise/unresolvable entries) - add a
    # global-role entitlement on top, to exercise both entitlement kinds in one go.
    userinfo_data = {
        **USERINFO_TOKEN,
        "eduperson_entitlement": [
            *USERINFO_TOKEN["eduperson_entitlement"],
            RES_PREFIX + "roles:administration" + CESNET_SUFFIX,
        ],
    }
    userinfo_response = SimpleNamespace(data=userinfo_data)

    remote = SimpleNamespace(
        name=BACKEND_NAME,
        consumer_key="test-consumer-key",
        base_url="https://login.e-infra.cz/oidc/",
        get=lambda url: userinfo_response,
    )

    account_info_link_perun_groups(remote, account_info={})

    assert len(calls) == 1
    called_user, entitlements, cause = calls[0]
    assert called_user is user
    assert cause == "login"
    assert entitlements == {
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:efbe:role:member" + CESNET_SUFFIX,
            community_slug="efbe",
            role="member",
        ),
        CommunityEntitlement.from_slug(
            entitlement="urn:geant:cesnet.cz:res:communities:0d9d:role:member" + CESNET_SUFFIX,
            community_slug="0d9d",
            role="member",
        ),
        GlobalRoleEntitlement.from_role_name(
            entitlement="urn:geant:cesnet.cz:res:roles:administration" + CESNET_SUFFIX,
            role="administration",
        ),
    }


# ---------------------------------------------------------------------------
# end-to-end signup through the real invenio_oauthclient login/authorized views
# ---------------------------------------------------------------------------


def _oauth_state():
    return state_serializer.dumps({"app": BACKEND_NAME, "sid": _create_identifier(), "next": None})


def test_full_signup_flow_creates_confirmed_user(app, database, search_clear, rsa_keypair, monkeypatch):
    import oarepo_oidc_einfra.remote as remote_module

    # account_info_link_perun_groups needs its own access-token/userinfo-round-trip machinery
    # that is already covered in isolation above; disable it here so this test can focus on
    # exercising the real login -> authorized -> signup wiring end to end.
    monkeypatch.setattr(remote_module, "account_info_link_perun_groups", lambda *args, **kwargs: None)

    private_pem, _ = rsa_keypair
    id_token = _make_id_token(
        private_pem,
        sub="e2e-newsub@einfra.cesnet.cz",
        name="End To End",
        email="e2e@example.org",
    )
    oauth_token_response = {
        "access_token": "e2e-access-token",  # noqa S106
        "token_type": "bearer",
        "expires_in": 3600,
        "id_token": id_token,
    }

    with app.test_client() as client:
        client.get(url_for("invenio_oauthclient.login", remote_app=BACKEND_NAME))

        oauth = app.extensions["oauthlib.client"]
        oauth.remote_apps[BACKEND_NAME].handle_oauth2_response = MagicMock(return_value=oauth_token_response)

        resp = client.get(
            url_for(
                "invenio_oauthclient.authorized",
                remote_app=BACKEND_NAME,
                code="test",
                state=_oauth_state(),
            )
        )
        assert resp.status_code in (301, 302)

    user = User.query.filter_by(email="e2e@example.org").one()
    assert user.confirmed_at is not None
    identity = UserIdentity.query.filter_by(method=BACKEND_NAME, id="e2e-newsub@einfra.cesnet.cz").one()
    assert identity.id_user == user.id
    remote_account = RemoteAccount.query.filter_by(user_id=user.id).one()
    assert remote_account.extra_data.get("full_name") == "End To End"
    RemoteToken.query.filter_by(id_remote_account=remote_account.id).one()


def test_full_authorized_reject_redirects_home(app):
    with app.test_client() as client:
        client.get(url_for("invenio_oauthclient.login", remote_app=BACKEND_NAME))

        resp = client.get(
            url_for(
                "invenio_oauthclient.authorized",
                remote_app=BACKEND_NAME,
                error="access_denied",
                error_description="User denied access",
                state=_oauth_state(),
            )
        )
        assert resp.status_code in (301, 302)
        assert resp.location == "/"
