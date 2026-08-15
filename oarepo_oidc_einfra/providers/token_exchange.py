# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Authenticate an existing Invenio user from an exchanged e-INFRA JWT."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jwt
from flask import abort, current_app, request
from invenio_accounts.models import UserIdentity
from oarepo_runtime.ext import AuthProvider

from ..audit_log import audit_log
from ..remote import BACKEND_NAME

JWT_SEGMENT_SEPARATOR_COUNT = 2

if TYPE_CHECKING:
    from invenio_accounts.models import User


class EInfraTokenExchangeProvider(AuthProvider):
    """Authenticate a request carrying an exchanged e-INFRA access token."""

    def before_request(self) -> User | None:
        """Return the linked user, or ``None`` when no Bearer token exists."""
        token = self._bearer_token()
        if token is None:
            return None

        # Leave opaque OAuth access tokens to the standard OAuth provider.
        if token.count(".") != JWT_SEGMENT_SEPARATOR_COUNT:
            return None

        claims = self._validate_token(token)  # type: ignore[return]
        return self._find_user(claims["sub"])

    @staticmethod
    def _bearer_token() -> str | None:
        authorization = request.headers.get("Authorization")
        if authorization is None:
            return None

        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token.strip():
            return None

        return str(token.strip())

    @staticmethod
    def _validate_token(token: str) -> dict[str, Any]:  # type: ignore[return]
        """Verify token signature, audience, issuer and validity claims."""
        audience = current_app.config.get(
            "EINFRA_TOKEN_EXCHANGE_AUDIENCE",
            current_app.config.get("INVENIO_EINFRA_CONSUMER_KEY"),
        )
        issuer = current_app.config.get("EINFRA_TOKEN_EXCHANGE_ISSUER")
        public_key = current_app.config.get("EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY")

        try:
            return jwt.decode(  # type: ignore[no-any-return]
                token,
                key=public_key,  # ty: ignore[invalid-argument-type]
                algorithms=["RS256"],
                audience=audience,
                issuer=issuer,
                options={"require": ["sub", "exp", "iat"]},
            )
        except jwt.PyJWTError:
            audit_log.exception("Rejected e-INFRA token: JWT validation failed")
            abort(403)

    @staticmethod
    def _find_user(subject: str) -> User:
        """Resolve an e-INFRA subject to an already-provisioned Invenio user."""
        identity = UserIdentity.query.filter_by(
            method=BACKEND_NAME,
            id=subject,
        ).one_or_none()

        if identity is None or identity.user is None:
            audit_log.error("No local user is linked to e-INFRA subject %s", subject)
            abort(403)

        return identity.user
