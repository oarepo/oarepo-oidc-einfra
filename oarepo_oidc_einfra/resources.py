#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

"""OIDC resources (API + UI)."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from flask import Blueprint, Flask, current_app, flash, g, redirect, request
from flask_login import login_required, logout_user
from flask_login.utils import login_url as make_login_url
from flask_principal import PermissionDenied
from flask_resources import Resource, ResourceConfig, route
from flask_security import current_user
from invenio_access import Permission, action_factory
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_cache.proxies import current_cache
from invenio_communities.members.records.api import Member
from invenio_communities.proxies import current_communities
from invenio_db import db
from invenio_i18n import gettext as _
from invenio_records_resources.resources.errors import PermissionDeniedError
from invenio_requests.customizations import CommentEventType
from invenio_requests.proxies import current_events_service, current_requests_service
from invenio_requests.records.api import Request, RequestEventFormat

from oarepo_oidc_einfra.encryption import decrypt, encrypt
from oarepo_oidc_einfra.proxies import current_einfra_oidc
from oarepo_oidc_einfra.tasks import update_from_perun_dump

if TYPE_CHECKING:
    from werkzeug import Response

log = logging.getLogger(__name__)


upload_dump_action = action_factory("upload-oidc-einfra-dump")


class OIDCEInfraUIResourceConfig(ResourceConfig):
    """Configuration for the REST API."""

    blueprint_name = "oarepo_oidc_einfra_ui"
    """Blueprint name."""

    url_prefix = "/auth/oidc/einfra"
    """URL prefix for the resource."""

    routes = {
        "accept-invitation": "/invitations/<request_id>/accept",
    }
    """Routes for the resource."""


class OIDCEInfraUIResource(Resource):
    """REST API for the EInfra OIDC."""

    def __init__(self, config: Optional[OIDCEInfraUIResourceConfig] = None):
        """Initialize the resource."""
        super().__init__(config=config or OIDCEInfraUIResourceConfig())

    def create_url_rules(self) -> list[dict]:
        """Create URL rules for the resource."""
        routes = self.config.routes
        return [
            route("GET", routes["accept-invitation"], self.accept_invitation),
        ]

    def accept_invitation(self) -> Response:
        """Accept an invitation to join a community.

        This is an endpoint to which user is directed
        after clicking the link in the invitation email, accepting the terms and conditions and
        accepting the invitation.

        We expect the url to contain the request_id of the invitation request that was sent to the user
        and use it to accept the invitation.

        Note:
        If user accepts the invitation but this endpoint is not called, the invitation will be forever
        in the submitted state (until expiration). The user will still be able to access the community
        because the AAI will return the correct capabilities for the user.

        Currently, the PERUN api does not return the ID of the created invitation, so we cannot store it
        and check in a background task if the invitation was accepted and then change the state of the request.

        """
        assert request.view_args is not None

        request_id = decrypt(request.view_args["request_id"])

        if "fresh_login_token" not in request.args or not current_user.is_authenticated:
            # force logout and redirect to the same page with the fresh_login_token
            # so that the user is logged in again
            logout_user()

            # create a fresh login token that will guarantee that the user is logged in
            fresh_login_token = encrypt("fresh_login_token_" + str(request_id))

            # redirect to the login page to go through the login process again
            redirect_url = make_login_url(
                current_app.login_manager.login_view,
                next_url=self.add_query_param(
                    request.url, "fresh_login_token", fresh_login_token
                ),
            )

            return redirect(redirect_url)
        else:
            # check the fresh login token and raise error if it is not valid
            fresh_login_token = decrypt(request.args["fresh_login_token"])
            if fresh_login_token != "fresh_login_token_" + str(request_id):
                raise PermissionDenied("Invalid login token")

        # get the invitation request and check if it is submitted.
        invitation_request = Request.get_record(request_id)
        assert invitation_request.status == "submitted"

        # if its user is not the current user, we might to delete
        # the user on the request so that it does not pollute the space
        invitation = Member.get_member_by_request(request_id)

        # sanity check, should always be filled
        if not invitation.model:
            raise ValueError(f"Invitation {invitation} does not have a model.")

        original_request_user_id = invitation.model.user_id

        # AAI should have created a membership during the synchronization in login process
        found_membership = Member.model_cls.query.filter(
            Member.model_cls.user_id == g.identity.id,
            Member.model_cls.community_id == invitation.model.community_id,
            Member.model_cls.role == invitation.model.role,
            Member.model_cls.active.is_(True),
        ).one_or_none()

        if not found_membership:
            log.error(
                "User %s accepted an invitation to community %s, but no membership was found. Request ID: %s, Invitation ID: %s",
                g.identity.id,
                invitation.model.community_id,
                invitation_request.id,
                invitation.id,
            )
            flash(
                _(
                    "There was an error processing your invitation to a community. "
                    "Please log out of the repository, wait a couple of minutes and log in again. "
                    "If you will not become a member of the community, please contact the support."
                ),
                "error",
            )
            return redirect("/")

        if str(original_request_user_id) != str(g.identity.id):
            # the authenticated user's email is different than the one that the invitation was sent to.
            # we need to store this information in the invitation model as a comment.
            try:
                # if the user is already a member of the community, we need to remove
                # the invitation. At first remove the request id from the invitation
                # so that we can move it to the found_membership
                invitation.model.request_id = None
                db.session.add(invitation.model)
                db.session.commit()

                # now delete the invitation (that is, instance of a Member) from db and from the indexer
                current_communities.service.members.indexer.delete(invitation)
                invitation.delete(force=True)

                # add the request to the found membership
                found_membership.request_id = request_id

                # commit the found membership with the request id
                db.session.add(found_membership)
                db.session.commit()

                # reindex the found membership to have the request id in the index
                current_communities.service.members.indexer.index(
                    Member.get_record(found_membership.id)
                )

                # add a comment to the found membership
                actual_user = (
                    db.session.query(User).filter_by(id=g.identity.id).one_or_none()
                )
                if actual_user and actual_user.email:
                    actual_user_email = actual_user.email
                else:
                    actual_user_email = f"unknown email for user id {g.identity.id}"

                invitation_user = (
                    db.session.query(User)
                    .filter_by(id=original_request_user_id)
                    .one_or_none()
                )

                if invitation_user and invitation_user.email:
                    invitation_user_email = invitation_user.email
                else:
                    invitation_user_email = (
                        f"unknown email for user id {original_request_user_id}"
                    )
                current_events_service.create(
                    system_identity,
                    invitation_request.id,
                    {
                        "type": CommentEventType.type_id,
                        "payload": {
                            "content": (
                                "The user accepted the invitation, "
                                f"but their email address ({actual_user_email}) is different "
                                f"than the one that the invitation was sent to ({invitation_user_email}). "
                                "The request has been moved to the existing membership."
                            ),
                            "format": RequestEventFormat.HTML.value,
                        },
                    },
                    CommentEventType,
                )
            except Exception as e:
                log.error(
                    "Error while accepting invitation for user %s: %s",
                    g.identity.id,
                    e,
                )
                flash(
                    _(
                        "There was an error processing your invitation to a community. "
                        "Please log out of the repository, wait a couple of minutes and log in again. "
                        "If you will not become a member of the community, please contact the support."
                    ),
                    "error",
                )
                return redirect("/")

        # mark the request as accepted. Note: we are not running the accept action
        # here as we already have the membership created
        invitation_request.status = "accepted"
        invitation_request.commit()
        db.session.commit()
        current_requests_service.indexer.index(invitation_request)

        return redirect("/")

    @staticmethod
    def add_query_param(url: str, param_name: str, param_value: str):
        """Safely add a query parameter to a URL that might already have query parameters."""
        # Parse the URL into components
        parsed_url = urlparse(url)

        # Parse existing query parameters into a dictionary
        query_dict = parse_qs(parsed_url.query)

        # Add or update the parameter
        query_dict[param_name] = [
            str(param_value)
        ]  # Wrap in list to handle multiple values

        # Rebuild the query string
        new_query = urlencode(query_dict, doseq=True)

        # Reconstruct the URL with the new query
        new_url = urlunparse(parsed_url._replace(query=new_query))

        return new_url


class OIDCEInfraAPIResourceConfig(ResourceConfig):
    """Configuration for the REST API."""

    blueprint_name = "oarepo_oidc_einfra_api"
    """Blueprint name."""

    url_prefix = "/auth/oidc/einfra"
    """URL prefix for the resource, will be at /api/auth/oidc/einfra."""

    routes = {
        "upload-dump": "/dumps/upload",
        "notify-dump": "/dumps/notify",
    }
    """Routes for the resource."""


class OIDCEInfraAPIResource(Resource):
    """REST API for the EInfra OIDC."""

    def __init__(self, config: Optional[OIDCEInfraAPIResourceConfig] = None):
        """Initialize the resource."""
        super().__init__(config=config or OIDCEInfraAPIResourceConfig())

    def create_url_rules(self) -> list[dict]:
        """Create URL rules for the resource."""
        routes = self.config.routes
        return [
            route("POST", routes["upload-dump"], self.upload_dump),
            route("POST", routes["notify-dump"], self.notify_dump),
        ]

    @login_required
    def upload_dump(self) -> tuple[dict, int]:
        """Upload a dump of the EInfra data.

        The dump will be uploaded to the configured location and then processed
        by a celery synchronization task.

        The caller must have the permission to upload the dump (upload-oidc-einfra-dump action
        that can be assigned via invenio access commandline tool).
        """
        if not Permission(upload_dump_action).allows(g.identity):
            raise PermissionDeniedError()

        if request.headers.get("Content-Type") != "application/json":
            return {
                "status": "error",
                "message": "Content-Type must be application/json",
            }, 400

        dump_path, checksum = store_dump(request.data)
        update_from_perun_dump.delay(dump_path, checksum)
        return {"status": "ok"}, 201

    @login_required
    def notify_dump(self) -> tuple[dict, int]:
        """Notify that a dump of the EInfra data has been uploaded to the S3 storage.

        The dump has already been uploaded to the configured location EINFRA_LAST_DUMP_PATH
        and the caller is just notifying that it is ready to be processed.
        The dump will be processed by a celery synchronization task.

        The caller must have the permission to upload the dump
        (upload-oidc-einfra-dump action that can be assigned via invenio
        access commandline tool).
        """
        if not Permission(upload_dump_action).allows(g.identity):
            raise PermissionDeniedError()

        update_from_perun_dump.delay(current_app.config["EINFRA_LAST_DUMP_PATH"], None)
        return {"status": "ok"}, 201


def store_dump(request_data: bytes) -> tuple[str, str]:
    """Store the dump in the configured location and return the path.

    The dump is stored in the bucket configured in the EINFRA_USER_DUMP_S3_BUCKET,
    the actual path is put into the cache under the key EINFRA_LAST_DUMP_PATH
    and the path is returned.

    Storing the path into the cache means that even if the background task process
    multiple dumps out of order, the last one will be always the one that is processed -
    the previous ones will be ignored.
    """
    now = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M-%S")
    dump_path = f"{now}.json"
    client = current_einfra_oidc.dump_boto3_client
    client.put_object(
        Bucket=current_einfra_oidc.dump_s3_bucket,
        Key=dump_path,
        Body=request_data,
    )
    current_cache.cache.set("EINFRA_LAST_DUMP_PATH", dump_path)

    return dump_path, hashlib.sha256(request_data).hexdigest()


def create_ui_blueprint(app: Flask) -> Blueprint:
    """Create a blueprint for the REST API."""
    return OIDCEInfraUIResource().as_blueprint()


def create_api_blueprint(app: Flask) -> Blueprint:
    """Create a blueprint for the REST API."""
    return OIDCEInfraAPIResource().as_blueprint()
