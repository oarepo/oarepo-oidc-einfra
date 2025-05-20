#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""E-Infra OIDC Remote Auth backend for NRP."""

import datetime
from typing import cast

import jwt
from flask_oauthlib.client import OAuthRemoteApp
from invenio_accounts.models import User, UserIdentity
from invenio_db import db
from invenio_oauthclient import current_oauthclient
from invenio_oauthclient.contrib.settings import OAuthSettingsHelper
from invenio_oauthclient.handlers.token import token_getter
from invenio_oauthclient.models import RemoteToken
from invenio_oauthclient.oauth import oauth_get_user
from invenio_oauthclient.signals import account_info_received


class EInfraOAuthSettingsHelper(OAuthSettingsHelper):
    """E-Infra OIDC Remote Auth backend for NRP."""

    def __init__(
        self,
        *,
        title: str = "E-Infra AAI",
        description: str = "E-Infra authentication and authorization service.",
        base_url: str = "https://login.e-infra.cz/oidc/",
        app_key: str = "EINFRA",
        icon: str | None = None,
        access_token_url: str | None = None,
        authorize_url: str | None = None,
        access_token_method: str = "POST",
        request_token_params: dict | None = None,
        request_token_url: str | None = None,
        precedence_mask: str | None = None,
        signup_options: dict | None = None,
        logout_url: str | None = None,
        **kwargs: dict,
    ):
        """Initialize the E-Infra OIDC Remote Auth backend for NRP."""
        request_token_params = request_token_params or {
            "scope": " ".join(
                [
                    "openid",
                    "profile",
                    "email",
                    "eduperson_entitlement",
                    "isCesnetEligibleLastSeen",
                    "organization",
                ]
            )
        }

        access_token_url = access_token_url or f"{base_url}token"
        authorize_url = authorize_url or f"{base_url}authorize"
        content_type = "application/json"

        super().__init__(
            title=title,
            description=description,
            base_url=base_url,
            app_key=app_key,
            icon=icon,
            access_token_url=access_token_url,
            authorize_url=authorize_url,
            access_token_method=access_token_method,
            request_token_params=request_token_params,
            request_token_url=request_token_url,
            precedence_mask=precedence_mask,
            signup_options=signup_options,
            logout_url=logout_url,
            content_type=content_type,
            **kwargs,
        )

        self._handlers = dict(
            authorized_handler="invenio_oauthclient.handlers:authorized_signup_handler",
            signup_handler=dict(
                info="oarepo_oidc_einfra.remote:account_info",
                info_serializer="oarepo_oidc_einfra.remote:account_info_serializer",
                setup="oarepo_oidc_einfra.remote:account_setup",
                view="invenio_oauthclient.handlers:signup_handler",
            ),
        )

        self._rest_handlers = dict(
            authorized_handler="invenio_oauthclient.handlers.rest:authorized_signup_handler",
            signup_handler=dict(
                info="oarepo_oidc_einfra.remote:account_info",
                info_serializer="oarepo_oidc_einfra.remote:account_info_serializer",
                setup="oarepo_oidc_einfra.remote:account_setup",
                view="invenio_oauthclient.handlers.rest:signup_handler",
            ),
            response_handler="invenio_oauthclient.handlers.rest:default_remote_response_handler",
            authorized_redirect_url="/",
            signup_redirect_url="/",
            error_redirect_url="/",
        )

    def get_handlers(self) -> dict:
        """Return CESNET auth handlers."""
        return self._handlers

    def get_rest_handlers(self) -> dict:
        """Return CESNET auth REST handlers."""
        return self._rest_handlers


_cesnet_app = EInfraOAuthSettingsHelper()

"""
CESNET OpenID remote app.
"""
EINFRA_LOGIN_APP = _cesnet_app.remote_app


def account_info_serializer(remote: OAuthRemoteApp, resp: dict) -> dict:
    """Serialize the account info response object.

    :param remote: The remote application.
    :param resp: The response of the `authorized` endpoint.

    :returns: A dictionary with serialized user information.
    """
    decoded_token = jwt.decode(
        resp["id_token"],
        options={"verify_signature": True},
        key=remote.rsa_key,  # type: ignore
        audience=remote.consumer_key,  # type: ignore
        algorithms=["RS256"],
    )

    return {
        "external_id": decoded_token["sub"],
        "external_method": remote.name,
        "user": {
            "email": decoded_token.get("email"),
            "profile": {
                "full_name": decoded_token.get("name"),
            },
        },
    }


def account_info(remote: OAuthRemoteApp, resp: dict) -> dict:
    """Retrieve remote account information used to find local user.

    It returns a dictionary with the following structure:
        {
            'external_id': 'sub',
            'external_method': 'perun',
            'user': {
                'email': 'Email address',
                'profile': {
                    'full_name': 'Full Name',
                },
            }
        }
    :param remote: The remote application.
    :param resp: The response of the `authorized` endpoint.

    :returns: A dictionary with the user information.
    """
    handlers = current_oauthclient.signup_handlers[remote.name]
    handler_resp = handlers["info_serializer"](resp)

    return handler_resp


def account_setup(remote: OAuthRemoteApp, token: RemoteToken, resp: dict) -> None:
    """Perform additional setup after user have been logged in.

    :param remote: The remote application.
    :param token: The token value.
    :param resp: The response.
    """
    decoded_token = jwt.decode(
        resp["id_token"],
        options={"verify_signature": True},
        algorithms=["RS256"],
        key=remote.rsa_key,  # type: ignore
        audience=remote.consumer_key,  # type: ignore
    )

    with db.session.begin_nested():  # type: ignore
        token.remote_account.extra_data = {
            "full_name": decoded_token["name"],
        }

        user = token.remote_account.user

        # Create user <-> external id link.

        # If there is no user identity for this user and group, create it
        ui = UserIdentity.query.filter_by(
            user=user, method="e-infra", id=decoded_token["sub"]
        ).one_or_none()
        if not ui:
            UserIdentity.create(user, "e-infra", decoded_token["sub"])

        if user.confirmed_at is None:
            # Set the user as confirmed
            user.confirmed_at = datetime.datetime.now()
            with db.session.begin_nested():  # type: ignore
                db.session.add(user)  # type: ignore
                db.session.commit()  # type: ignore


# During overlay initialization.
@account_info_received.connect
def autocreate_user(
    remote: OAuthRemoteApp,
    token: RemoteToken | None = None,
    response: dict | None = None,
    account_info: dict | None = None,
) -> None:
    """Create a user if it does not exist.

    :param remote: The remote application.
    :param token: access token
    :param response: access response from the remote server
    :param account_info: account info from the remote server
    """
    assert account_info is not None

    email = account_info["user"]["email"].lower()
    id, method = account_info["external_id"], account_info["external_method"]
    user_profile = {
        "affiliations": "",
        "full_name": account_info["user"]["profile"]["full_name"],
    }

    user_identity = UserIdentity.query.filter_by(id=id, method=method).one_or_none()
    if not user_identity:
        user = User.query.filter(User.email == email).one_or_none()
        if not user:
            user = User(email=email, active=True, user_profile=user_profile)

            """
            Workaround note:

            When we create a user, we need to set 'confirmed_at' property,
            because contrary to the default security settings (False),
            the config variable SECURITY_CONFIRMABLE is set to True.
            Without setting 'confirmed_at' to some value, it is impossible to log in.
            """
            user.confirmed_at = datetime.datetime.now()

            with db.session.begin_nested():  # type: ignore
                db.session.add(user)  # type: ignore
                db.session.commit()  # type: ignore

        with db.session.begin_nested():  # type: ignore
            UserIdentity.create(user=user, method=method, external_id=id)
            db.session.commit()  # type: ignore

    else:
        assert user_identity.user is not None

        user_identity.user.email = email
        user_identity.user.user_profile = user_profile

        with db.session.begin_nested():  # type: ignore
            db.session.add(user_identity.user)  # type: ignore
            db.session.commit()  # type: ignore


def account_info_link_perun_groups(
    remote: OAuthRemoteApp, *, account_info: dict, **kwargs: dict
) -> None:
    """Set local user community membership based on the Perun groups retrieved from the userinfo token.

    :param remote: The remote application.
    :param account_info: The account info of the current user
    :param kwargs: Additional arguments (not used)
    """
    # make the import local to avoud circular imports
    from oarepo_oidc_einfra.communities import CommunitySupport
    from oarepo_oidc_einfra.perun import get_communities_from_userinfo_token

    user = oauth_get_user(
        remote.consumer_key,
        account_info=account_info,
        access_token=token_getter(remote)[0],  # type: ignore
    )

    if user is None:
        return

    userinfo_token = remote.get(cast("str", remote.base_url) + "userinfo").data
    aai_community_roles = get_communities_from_userinfo_token(
        cast("dict", userinfo_token)
    )

    CommunitySupport.set_user_community_membership(user, aai_community_roles)


account_info_received.connect(account_info_link_perun_groups)
