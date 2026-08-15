# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for oarepo_oidc_einfra/providers/token_exchange.py.

``EInfraTokenExchangeProvider`` authenticates requests carrying an RFC 8693 ("OAuth 2.0
Token Exchange", https://datatracker.ietf.org/doc/html/rfc8693) delegated-access-token,
presented as a JWT bearer token in the ``Authorization`` header. Per RFC 8693 the exchanged
token is itself a JWT that must be validated like any other JWT access/ID token (signature,
audience, issuer, expiry - see RFC 8693 section 4.1's ``mapped from`` discussion and RFC 7519
for the JWT claims themselves); this module does not perform the exchange itself (that
happens at the e-INFRA AAI token endpoint), it only validates a token that has already been
exchanged and resolves it to a local user.
"""

from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import current_app
from flask_login import current_user
from invenio_accounts.models import User, UserIdentity
from invenio_db import db
from werkzeug.exceptions import Forbidden

from oarepo_oidc_einfra.providers.token_exchange import EInfraTokenExchangeProvider
from oarepo_oidc_einfra.remote import BACKEND_NAME

AUDIENCE = "test-token-exchange-audience"
ISSUER = "https://login.e-infra.cz/oidc/"


@pytest.fixture(scope="module")
def rsa_keypair():
    """Generate a throw-away RSA keypair used to sign/verify test tokens."""
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


@pytest.fixture(scope="module")
def app_config(app_config, rsa_keypair):
    _, public_pem = rsa_keypair
    app_config["EINFRA_TOKEN_EXCHANGE_AUDIENCE"] = AUDIENCE
    app_config["EINFRA_TOKEN_EXCHANGE_ISSUER"] = ISSUER
    app_config["EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY"] = public_pem
    return app_config


def _make_token(private_pem, **overrides):
    """Build a signed RS256 exchanged access token, as e-INFRA AAI would issue it."""
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "exchangedsub@einfra.cesnet.cz",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_pem, algorithm="RS256")


@pytest.fixture
def linked_user(app, database):
    """Create a user linked to the e-infra backend under a known (unique per test) subject.

    Unique per call since the module-scoped ``database`` fixture is not rolled back between
    tests, so a fixed email/subject would collide once more than one test uses this fixture.
    """
    import uuid

    unique = uuid.uuid4().hex
    user = User(email=f"exchange-user-{unique}@example.org", active=True)
    db.session.add(user)
    db.session.commit()
    subject = f"exchangedsub-{unique}@einfra.cesnet.cz"
    UserIdentity.create(user=user, method=BACKEND_NAME, external_id=subject)
    db.session.commit()
    user.subject = subject
    return user


# ---------------------------------------------------------------------------
# _bearer_token
# ---------------------------------------------------------------------------


def test_bearer_token_returns_none_without_authorization_header(app):
    with app.test_request_context("/"):
        assert EInfraTokenExchangeProvider._bearer_token() is None


@pytest.mark.parametrize(
    "header_value",
    [
        "Basic dXNlcjpwYXNz",  # a different auth scheme entirely
        "Bearer",  # scheme with no token at all
        "Bearer ",  # scheme with only whitespace
        "Bearer    ",
    ],
)
def test_bearer_token_returns_none_for_non_bearer_or_empty(app, header_value):
    with app.test_request_context("/", headers={"Authorization": header_value}):
        assert EInfraTokenExchangeProvider._bearer_token() is None


@pytest.mark.parametrize("scheme", ["Bearer", "bearer", "BEARER"])
def test_bearer_token_extracts_token_case_insensitively(app, scheme):
    with app.test_request_context("/", headers={"Authorization": f"{scheme} sometoken123"}):
        assert EInfraTokenExchangeProvider._bearer_token() == "sometoken123"


def test_bearer_token_strips_surrounding_whitespace(app):
    with app.test_request_context("/", headers={"Authorization": "Bearer   sometoken123   "}):
        assert EInfraTokenExchangeProvider._bearer_token() == "sometoken123"


# ---------------------------------------------------------------------------
# _validate_token
# ---------------------------------------------------------------------------


def test_validate_token_accepts_well_formed_token(app, rsa_keypair):
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, sub="validatesub@einfra.cesnet.cz")

    claims = EInfraTokenExchangeProvider._validate_token(token)

    assert claims["sub"] == "validatesub@einfra.cesnet.cz"


def test_validate_token_rejects_wrong_audience(app, rsa_keypair):
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, aud="someone-else")

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._validate_token(token)


def test_validate_token_rejects_wrong_issuer(app, rsa_keypair):
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, iss="https://not-e-infra.example.org/")

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._validate_token(token)


def test_validate_token_rejects_expired_token(app, rsa_keypair):
    private_pem, _ = rsa_keypair
    now = datetime.datetime.now(datetime.UTC)
    token = _make_token(private_pem, iat=now - datetime.timedelta(hours=1), exp=now - datetime.timedelta(minutes=1))

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._validate_token(token)


def test_validate_token_rejects_token_signed_with_wrong_key(app):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private_pem = other_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = _make_token(other_private_pem)

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._validate_token(token)


@pytest.mark.parametrize("missing_claim", ["sub", "exp", "iat"])
def test_validate_token_rejects_missing_required_claims(app, rsa_keypair, missing_claim):
    private_pem, _ = rsa_keypair
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "sub@einfra.cesnet.cz",
        "aud": AUDIENCE,
        "iss": ISSUER,
        "iat": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    del claims[missing_claim]
    token = jwt.encode(claims, private_pem, algorithm="RS256")

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._validate_token(token)


def test_validate_token_falls_back_to_invenio_einfra_consumer_key_for_audience(app, rsa_keypair, monkeypatch):
    private_pem, _ = rsa_keypair
    monkeypatch.delitem(current_app.config, "EINFRA_TOKEN_EXCHANGE_AUDIENCE", raising=False)
    monkeypatch.setitem(current_app.config, "INVENIO_EINFRA_CONSUMER_KEY", "fallback-audience")
    token = _make_token(private_pem, aud="fallback-audience")

    claims = EInfraTokenExchangeProvider._validate_token(token)

    assert claims["aud"] == "fallback-audience"


# ---------------------------------------------------------------------------
# _find_user
# ---------------------------------------------------------------------------


def test_find_user_returns_linked_user(app, database, linked_user):
    user = EInfraTokenExchangeProvider._find_user(linked_user.subject)

    assert user.id == linked_user.id


def test_find_user_aborts_when_no_identity_is_linked(app, database):
    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._find_user("no-such-subject@einfra.cesnet.cz")


def test_find_user_aborts_when_identity_has_no_user(app, monkeypatch):
    orphaned_identity = SimpleNamespace(user=None)
    fake_query = MagicMock()
    fake_query.filter_by.return_value.one_or_none.return_value = orphaned_identity
    monkeypatch.setattr(UserIdentity, "query", fake_query)

    with pytest.raises(Forbidden):
        EInfraTokenExchangeProvider._find_user("orphan@einfra.cesnet.cz")


# ---------------------------------------------------------------------------
# before_request
# ---------------------------------------------------------------------------


def test_before_request_returns_none_without_authorization_header(app):
    with app.test_request_context("/"):
        assert EInfraTokenExchangeProvider().before_request() is None


@pytest.mark.parametrize(
    "token",
    [
        "opaque-oauth-access-token",  # 0 dots - not JWT-shaped at all
        "only.one.dot.too.many",  # 4 dots - not a 3-segment JWT either
        "one.dot",  # 1 dot - not a 3-segment JWT
    ],
)
def test_before_request_ignores_non_jwt_tokens(app, token):
    # opaque access tokens are left for the standard OAuth2 provider to handle
    with app.test_request_context("/", headers={"Authorization": f"Bearer {token}"}):
        assert EInfraTokenExchangeProvider().before_request() is None


def test_before_request_returns_linked_user_for_valid_token(app, database, linked_user, rsa_keypair):
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, sub=linked_user.subject)

    with app.test_request_context("/", headers={"Authorization": f"Bearer {token}"}):
        user = EInfraTokenExchangeProvider().before_request()

    assert user.id == linked_user.id


def test_before_request_aborts_for_valid_but_unlinked_token(app, database, rsa_keypair):
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, sub="nobody-links-to-me@einfra.cesnet.cz")

    with app.test_request_context("/", headers={"Authorization": f"Bearer {token}"}), pytest.raises(Forbidden):
        EInfraTokenExchangeProvider().before_request()


def test_before_request_aborts_for_invalid_token_signature(app):
    with app.test_request_context("/", headers={"Authorization": "Bearer a.b.c"}), pytest.raises(Forbidden):
        EInfraTokenExchangeProvider().before_request()


# ---------------------------------------------------------------------------
# end-to-end: the provider is wired into oarepo_runtime's before_request hook
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def whoami_route(app):
    """Register a tiny test-only route once for the end-to-end tests below.

    Flask refuses to register new routes (or error handlers) on an app that has already
    handled a request, so this must be set up (and depended on by every end-to-end test)
    before any test in this module sends a real request through ``app.test_client()``.
    """
    from flask import jsonify

    @app.route("/_test_whoami")
    def _whoami():
        if current_user.is_authenticated:
            return {"email": current_user.email}, 200
        return {"anonymous": True}, 200

    # the app's default 403 handler renders a themed HTML error page, which needs webpack
    # assets that are not built in this test environment - a plain JSON handler avoids that
    # unrelated failure mode and lets this test focus on the status code the provider caused
    @app.errorhandler(403)
    def _forbidden(e):
        return jsonify(error=str(e)), 403

    return "/_test_whoami"


def test_full_request_logs_in_user_from_exchanged_token(app, database, linked_user, rsa_keypair, whoami_route):
    """A request with a valid exchanged token should be authenticated by the real app.

    ``oarepo_runtime.ext.OARepoRuntime.auth_before_request`` (registered as a Flask
    ``before_request`` hook) calls every ``oarepo.auth_providers`` entry point, including
    this one, and logs in whatever user is returned - this test exercises that full chain,
    not just the provider in isolation.
    """
    private_pem, _ = rsa_keypair
    token = _make_token(private_pem, sub=linked_user.subject)

    with app.test_client() as client:
        resp = client.get(whoami_route, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json == {"email": linked_user.email}

    # sanity check: a fresh client (no session cookie from the login above) sees anonymous
    with app.test_client() as anonymous_client:
        resp = anonymous_client.get(whoami_route)
        assert resp.status_code == 200
        assert resp.json == {"anonymous": True}


def test_full_request_rejects_invalid_exchanged_token(app, whoami_route):
    with app.test_client() as client:
        resp = client.get(whoami_route, headers={"Authorization": "Bearer a.b.c"})
        assert resp.status_code == 403
