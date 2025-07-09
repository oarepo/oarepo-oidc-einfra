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
from typing import Callable

import boto3
import botocore.client
from flask import Flask, current_app
from invenio_base.utils import obj_or_import_string
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
            service_username=current_app.config["EINFRA_SERVICE_USERNAME"],
            service_password=current_app.config["EINFRA_SERVICE_PASSWORD"],
        )

    @property
    def repository_vo_id(self) -> int:
        """Get the repository VO ID."""
        return int(current_app.config["EINFRA_REPOSITORY_VO_ID"])

    @property
    def repository_facility_id(self) -> int:
        """Get the repository facility ID."""
        return int(current_app.config["EINFRA_REPOSITORY_FACILITY_ID"])

    @property
    def communities_group_id(self) -> int:
        """Get the communities group ID."""
        return int(current_app.config["EINFRA_COMMUNITIES_GROUP_ID"])

    @cached_property
    def capabilities_attribute_id(self) -> int:
        """Get the capabilities attribute ID."""
        return self.perun_api().get_attribute_by_name(
            current_app.config["EINFRA_CAPABILITIES_ATTRIBUTE_NAME"]
        )["id"]

    @property
    def capabilities_attribute_name(self) -> str:
        """Get the capabilities attribute name."""
        return current_app.config["EINFRA_CAPABILITIES_ATTRIBUTE_NAME"]

    @cached_property
    def sync_service_id(self) -> int:
        """Get the synchronization service ID."""
        return self.perun_api().get_service_by_name(
            current_app.config["EINFRA_SYNC_SERVICE_NAME"]
        )["id"]

    @property
    def default_language(self) -> str:
        """Get the default language."""
        return current_app.config["EINFRA_DEFAULT_INVITATION_LANGUAGE"]

    @property
    def einfra_user_id_search_attribute(self) -> str:
        """Get the user EInfra ID attribute."""
        return current_app.config["EINFRA_USER_ID_SEARCH_ATTRIBUTE"]

    @property
    def einfra_user_id_dump_attribute(self) -> str:
        """Get the user persistent EInfra ID attribute."""
        return current_app.config["EINFRA_USER_ID_DUMP_ATTRIBUTE"]

    @property
    def user_display_name_attribute(self) -> str:
        """Get the user display name attribute."""
        return current_app.config["EINFRA_USER_DISPLAY_NAME_ATTRIBUTE"]

    @property
    def user_organization_attribute(self) -> str:
        """Get the user organization attribute."""
        return current_app.config["EINFRA_USER_ORGANIZATION_ATTRIBUTE"]

    @property
    def user_preferred_mail_attribute(self) -> str:
        """Get the user preferred mail attribute."""
        return current_app.config["EINFRA_USER_PREFERRED_MAIL_ATTRIBUTE"]

    @property
    def dump_s3_bucket(self) -> str:
        """Get the dump S3 bucket name."""
        return current_app.config["EINFRA_USER_DUMP_S3_BUCKET"]

    @property
    def entitlement_namespaces(self) -> list[str]:
        """Get the entitlement namespaces."""
        return current_app.config["EINFRA_ENTITLEMENT_NAMESPACES"]

    @property
    def entitlement_prefix(self) -> str:
        """Get the entitlement prefix."""
        return current_app.config["EINFRA_ENTITLEMENT_PREFIX"]

    @property
    def synchronization_enabled(self) -> bool:
        """Is the synchronization enabled."""
        return current_app.config["EINFRA_COMMUNITY_SYNCHRONIZATION"]

    @property
    def invitation_synchronization_enabled(self) -> bool:
        """Is the invitation synchronization enabled."""
        return (
            current_app.config["EINFRA_COMMUNITY_INVITATION_SYNCHRONIZATION"]
            and self.synchronization_enabled
        )

    @property
    def members_synchronization_enabled(self) -> bool:
        """Is the members synchronization enabled."""
        return (
            current_app.config["EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION"]
            and self.synchronization_enabled
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

    @cached_property
    def role_transformer(self) -> Callable | None:
        """Get the role transformer function."""
        role_transformer = current_app.config.get(
            "EINFRA_COMMUNITIES_ROLES_TRANSFORMER", None
        )
        if role_transformer:
            return obj_or_import_string(role_transformer)
        return None
