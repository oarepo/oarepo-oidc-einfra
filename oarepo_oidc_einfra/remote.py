# -*- coding: utf-8 -*-
#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

import datetime

import jwt
from invenio_accounts.models import User, UserIdentity
from invenio_db import db
from invenio_oauthclient import current_oauthclient
from invenio_oauthclient.contrib.settings import OAuthSettingsHelper
from invenio_oauthclient.handlers.token import token_getter
from invenio_oauthclient.oauth import oauth_get_user
from invenio_oauthclient.signals import account_info_received


class EInfraOAuthSettingsHelper(OAuthSettingsHelper):
    """E-Infra OIDC Remote Auth backend for NRP."""

    def __init__(
        self,
        *,
        title="E-Infra AAI",
        description="E-Infra authentication and authorization service.",
        base_url="https://login.e-infra.cz/oidc/",
        app_key="EINFRA",
        icon=None,
        access_token_url=None,
        authorize_url=None,
        access_token_method="POST",
        request_token_params=None,
        request_token_url=None,
        precedence_mask=None,
        signup_options=None,
        logout_url=None,
        **kwargs,
    ):

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

    def get_handlers(self):
        """Return CESNET auth handlers."""
        return self._handlers

    def get_rest_handlers(self):
        """Return CESNET auth REST handlers."""
        return self._rest_handlers


_cesnet_app = EInfraOAuthSettingsHelper()

"""
CESNET OpenID remote app.
"""
EINFRA_LOGIN_APP = _cesnet_app.remote_app


def account_info_serializer(remote, resp):
    """
    Serialize the account info response object.

    :param remote: The remote application.
    :param resp: The response of the `authorized` endpoint.

    :returns: A dictionary with serialized user information.
    """
    decoded_token = jwt.decode(
        resp["id_token"],
        options={"verify_signature": True},
        key=remote.rsa_key,
        audience=remote.consumer_key,
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


def account_info(remote, resp):
    """
    Retrieve remote account information used to find local user.

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


def account_setup(remote, token, resp):
    """
    Perform additional setup after user have been logged in.

    :param remote: The remote application.
    :param token: The token value.
    :param resp: The response.
    """
    decoded_token = jwt.decode(
        resp["id_token"],
        options={"verify_signature": True},
        algorithms=["RS256"],
        key=remote.rsa_key,
        audience=remote.consumer_key,
    )

    with db.session.begin_nested():
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


# During overlay initialization.
@account_info_received.connect
def autocreate_user(remote, token=None, response=None, account_info=None):
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

            with db.session.begin_nested():
                db.session.add(user)
                db.session.commit()

        with db.session.begin_nested():
            UserIdentity.create(user=user, method=method, external_id=id)
            db.session.commit()

    else:
        assert user_identity.user is not None

        user_identity.user.email = email
        user_identity.user.user_profile = user_profile

        with db.session.begin_nested():
            db.session.add(user_identity.user)
            db.session.commit()


def account_info_link_perun_groups(remote, *, account_info, **kwargs):
    # make the import local to avoud circular imports
    from oarepo_oidc_einfra.communities import CommunitySupport
    from oarepo_oidc_einfra.perun import get_communities_from_userinfo_token

    user = oauth_get_user(
        remote.consumer_key,
        account_info=account_info,
        access_token=token_getter(remote)[0],
    )

    if user is None:
        return

    userinfo_token = remote.get(remote.base_url + "userinfo").data
    aai_community_roles = get_communities_from_userinfo_token(userinfo_token)

    CommunitySupport.set_user_community_membership(user, aai_community_roles)


account_info_received.connect(account_info_link_perun_groups)