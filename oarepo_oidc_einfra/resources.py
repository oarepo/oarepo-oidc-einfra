#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

"""REST resources."""
from datetime import datetime

from flask import current_app, g, request
from flask_resources import Resource, ResourceConfig, route
from invenio_access import Permission, action_factory
from invenio_files_rest.storage import PyFSFileStorage
from invenio_records_resources.services.errors import PermissionDeniedError

from oarepo_oidc_einfra.tasks import update_from_perun_dump

upload_dump_action = action_factory("upload-oidc-einfra-dump")


class OIDCEInfraResourceConfig(ResourceConfig):
    """Configuration for the REST API."""

    blueprint_name = "oarepo_oidc_einfra"
    """Blueprint name."""

    url_prefix = "/oidc-einfra"
    """URL prefix for the resource, will be at /api/oidc-einfra."""

    routes = {"upload-dump": "/dumps/upload"}
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
        now = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
        dump_path = f"{dump_url}/{now}.json"

        location = PyFSFileStorage(dump_path)  # handles both filesystem and s3
        with location.open(mode="wb") as f:
            f.write(request.data)

        update_from_perun_dump.delay(dump_path)
        return {"status": "ok"}, 201


def create_rest_blueprint(app):
    """Create a blueprint for the REST API."""
    return OIDCEInfraResource().as_blueprint()
