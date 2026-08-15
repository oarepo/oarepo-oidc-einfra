# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""OIDC resources (API + UI)."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import ClassVar

import boto3
from flask import Blueprint, Flask, current_app, g, request
from flask_login import login_required
from flask_resources import Resource, ResourceConfig, route
from invenio_access.factory import action_factory
from invenio_access.permissions import Permission
from invenio_cache.proxies import current_cache
from invenio_records_resources.services.errors import PermissionDeniedError

from oarepo_oidc_einfra.tasks import update_from_perun_dump

log = logging.getLogger(__name__)


upload_dump_action = action_factory("upload-oidc-einfra-dump")


class OIDCEInfraAPIResourceConfig(ResourceConfig):
    """Configuration for the REST API."""

    blueprint_name = "oarepo_oidc_einfra_api"
    """Blueprint name."""

    url_prefix = "/auth/oidc/einfra"
    """URL prefix for the resource, will be at /api/auth/oidc/einfra."""

    routes: ClassVar[dict[str, str]] = {
        "upload-dump": "/dumps/upload",
        "notify-dump": "/dumps/notify",
    }
    """Routes for the resource."""


class OIDCEInfraAPIResource(Resource):
    """REST API for the EInfra OIDC."""

    def __init__(self, config: OIDCEInfraAPIResourceConfig | None = None):
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
        if not Permission(upload_dump_action).allows(g.identity):  # type: ignore[reportArgumentType]
            raise PermissionDeniedError

        if request.headers.get("Content-Type") != "application/json":
            return {
                "status": "error",
                "message": "Content-Type must be application/json",
            }, 400

        dump_path, checksum = store_dump(request.data)
        update_from_perun_dump.delay(dump_path, checksum)  # type: ignore[reportFunctionMemberAccess]
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
        if not Permission(upload_dump_action).allows(g.identity):  # type: ignore[reportArgumentType]
            raise PermissionDeniedError

        update_from_perun_dump.delay(current_app.config["EINFRA_LAST_DUMP_PATH"], None)  # type: ignore[reportFunctionMemberAccess]
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
    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )
    client.put_object(
        Bucket=current_app.config["EINFRA_USER_DUMP_S3_BUCKET"],
        Key=dump_path,
        Body=request_data,
        ContentLength=len(request_data),
    )
    current_cache.cache.set("EINFRA_LAST_DUMP_PATH", dump_path)

    return dump_path, hashlib.sha256(request_data).hexdigest()


def create_api_blueprint(_app: Flask) -> Blueprint:
    """Create a blueprint for the REST API."""
    return OIDCEInfraAPIResource().as_blueprint()
