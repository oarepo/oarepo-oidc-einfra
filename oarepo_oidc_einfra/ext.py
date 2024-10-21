#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""A flask extension for E-INFRA OIDC authentication."""

import threading
from functools import cached_property

import boto3
import botocore.client
from flask import Flask, current_app
from invenio_communities.communities.services.components import (
    DefaultCommunityComponents,
)
from invenio_communities.members.services.components import (
    DefaultCommunityMemberComponents,
)

from oarepo_oidc_einfra.perun import PerunLowLevelAPI
from oarepo_oidc_einfra.services.components.aai_communities import CommunityAAIComponent
from oarepo_oidc_einfra.services.components.aai_invitations import (
    AAIInvitationComponent,
)

from .cli import einfra as einfra_cmd

boto3_client_lock = threading.Lock()


class EInfraOIDCApp:
    """EInfra OIDC extension."""

    def __init__(self, app: Flask | None = None):
        """Create the extension."""
        if app:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Add the extension to the app and loads initial configuration."""
        app.extensions["einfra-oidc"] = self
        self.init_config(app)
        app.cli.add_command(einfra_cmd)

    def init_config(self, app: Flask) -> None:
        """Load the default configuration."""
        self.register_sync_component_to_community_service(app)

        # sets the default configuration values
        from . import config

        for k in dir(config):
            if k.startswith("EINFRA_"):
                app.config.setdefault(k, getattr(config, k))

    def register_sync_component_to_community_service(self, app: Flask) -> None:
        """Register components to the community service."""
        # Community -> AAI synchronization service component
        communities_components = app.config.get("COMMUNITIES_SERVICE_COMPONENTS", None)
        if isinstance(communities_components, list):
            communities_components.append(CommunityAAIComponent)
        elif not communities_components:
            app.config["COMMUNITIES_SERVICE_COMPONENTS"] = [
                CommunityAAIComponent,
                *DefaultCommunityComponents,
            ]

        # Invitation service component
        communities_members_components = app.config.get(
            "COMMUNITIES_MEMBERS_SERVICE_COMPONENTS", None
        )
        if isinstance(communities_members_components, list):
            communities_members_components.append(AAIInvitationComponent)
        elif not communities_members_components:
            app.config["COMMUNITIES_MEMBERS_SERVICE_COMPONENTS"] = [
                AAIInvitationComponent,
                *DefaultCommunityMemberComponents,
            ]

    def perun_api(self) -> PerunLowLevelAPI:
        """Create a new Perun API instance."""
        return PerunLowLevelAPI(
            base_url=current_app.config["EINFRA_API_URL"],
            service_id=current_app.config["EINFRA_SERVICE_ID"],
            service_username=current_app.config["EINFRA_SERVICE_USERNAME"],
            service_password=current_app.config["EINFRA_SERVICE_PASSWORD"],
        )

    @cached_property
    def dump_boto3_client(self) -> botocore.client.BaseClient:
        """Create a new boto3 client for the dump."""
        with boto3_client_lock:
            # see https://stackoverflow.com/questions/52820971/is-boto3-client-thread-safe
            # why this lock is here
            return boto3.client(
                "s3",
                aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
                aws_secret_access_key=current_app.config[
                    "EINFRA_USER_DUMP_S3_SECRET_KEY"
                ],
                endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
            )
