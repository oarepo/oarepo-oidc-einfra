#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

"""REST resources."""
from datetime import datetime, UTC

from flask import current_app, g, request
from flask_resources import Resource, ResourceConfig, route
from invenio_access import Permission, action_factory
from invenio_files_rest.storage import PyFSFileStorage
from flask_principal import PermissionDenied

from oarepo_oidc_einfra.encryption import decrypt
from oarepo_oidc_einfra.tasks import update_from_perun_dump
from flask_login import login_required
from invenio_requests.records.api import Request
from invenio_requests.proxies import current_requests_service
from invenio_access.permissions import system_identity
from invenio_accounts.models import User
from invenio_db import db
from invenio_records_resources.resources.errors import PermissionDeniedError

import logging
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

    def __init__(self, config=None):
        """Initialize the resource."""
        super(OIDCEInfraResource, self).__init__(
            config=config or OIDCEInfraResourceConfig()
        )

    def create_url_rules(self):
        """Create URL rules for the resource."""
        routes = self.config.routes
        return [
            route("POST", routes["upload-dump"], self.upload_dump),
            route("GET", routes["accept-invitation"], self.accept_invitation),
        ]

    def upload_dump(self):
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

        dump_url = current_app.config["EINFRA_DUMP_DATA_URL"]
        now = datetime.now(UTC).strftime("%Y-%m-%d-%H-%M-%S")
        dump_path = f"{dump_url}/{now}.json"

        location = PyFSFileStorage(dump_path)  # handles both filesystem and s3
        with location.open(mode="wb") as f:
            f.write(request.data)

        update_from_perun_dump.delay(dump_path)
        return {"status": "ok"}, 201

    @login_required
    def accept_invitation(self):
        """Accept an invitation to join a community. This is an endpoint to which user is directed
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
                raise PermissionDenied("The invitation was intended for a different user")

        # now, change the receiver to the current user
        invitation_request.receiver = {"user": g.identity.id}
        invitation_request.commit()

        current_requests_service.execute_action(system_identity, request_id, "accept")


def create_rest_blueprint(app):
    """Create a blueprint for the REST API."""
    return OIDCEInfraResource().as_blueprint()
