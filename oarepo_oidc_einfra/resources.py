#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

"""REST resources."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

from flask import Blueprint, Flask, current_app, g, redirect, request
from flask_login import login_required
from flask_principal import PermissionDenied
from flask_resources import Resource, ResourceConfig, route
from invenio_access import Permission, action_factory
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_cache.proxies import current_cache
from invenio_db import db
from invenio_records_resources.resources.errors import PermissionDeniedError
from invenio_requests.proxies import current_requests_service
from invenio_requests.records.api import Request

from oarepo_oidc_einfra.encryption import decrypt
from oarepo_oidc_einfra.proxies import current_einfra_oidc
from oarepo_oidc_einfra.tasks import update_from_perun_dump

if TYPE_CHECKING:
    from werkzeug import Response

log = logging.getLogger(__name__)


upload_dump_action = action_factory("upload-oidc-einfra-dump")


class OIDCEInfraResourceConfig(ResourceConfig):
    """Configuration for the REST API."""

    blueprint_name = "oarepo_oidc_einfra"
    """Blueprint name."""

    url_prefix = "/oidc-einfra"
    """URL prefix for the resource, will be at /api/oidc-einfra."""

    routes = {
        "upload-dump": "/dumps/upload",
        "accept-invitation": "/invitations/<request_id>/accept",
    }
    """Routes for the resource."""


class OIDCEInfraResource(Resource):
    """REST API for the EInfra OIDC."""

    def __init__(self, config: Optional[OIDCEInfraResourceConfig] = None):
        """Initialize the resource."""
        super().__init__(config=config or OIDCEInfraResourceConfig())

    def create_url_rules(self) -> list[dict]:
        """Create URL rules for the resource."""
        routes = self.config.routes
        return [
            route("POST", routes["upload-dump"], self.upload_dump),
            route("GET", routes["accept-invitation"], self.accept_invitation),
        ]

    def upload_dump(self) -> tuple[dict, int]:
        """Upload a dump of the EInfra data.

        The dump will be uploaded to the configured location (EINFRA_DUMP_DATA_URL inside config)
        and then processed by a celery synchronization task.

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

        # get the invitation request and check if it is submitted.
        invitation_request = Request.get_record(request_id)
        assert invitation_request.state == "submitted"

        # if its user is not the current user, we might to delete
        # the user on the request so that it does not pollute the space
        request_user_id = invitation_request.payload.get("user_id")
        if request_user_id != str(g.identity.id):
            user = User.query.filter_by(User.id == request_user_id).one()
            if not user.is_active:
                db.session.delete(user)
            else:
                log.error(
                    "Invitation check failed: The user for which the invitation was sent (%s) "
                    "is an active user and is not the same as the current user %s, thus the "
                    "invitation was not accepted. This means that we need to check the users if duplicity"
                    "exists and if so, we need to merge them somehow.",
                    request_user_id,
                    g.identity.id,
                )
                raise PermissionDenied("Invitation link invalid")

        # now, change the receiver to the current user
        invitation_request.receiver = {"user": g.identity.id}
        invitation_request.commit()

        # accept the invitation. This has to be accepted with system_identity, because
        # the user instance has not been known at the time of the request creation (just the email address)
        # and the receiver thus had to be the system_identity.
        current_requests_service.execute_action(system_identity, request_id, "accept")
        return redirect("/")


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
        Bucket=current_app.config["EINFRA_USER_DUMP_S3_BUCKET"],
        Key=dump_path,
        Body=request_data,
    )
    current_cache.cache.set("EINFRA_LAST_DUMP_PATH", dump_path)

    return dump_path, hashlib.sha256(request_data).hexdigest()


def create_rest_blueprint(app: Flask) -> Blueprint:
    """Create a blueprint for the REST API."""
    return OIDCEInfraResource().as_blueprint()
