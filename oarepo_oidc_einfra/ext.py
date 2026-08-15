# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""A Flask extension for E-INFRA OIDC authentication."""

from __future__ import annotations

from functools import cached_property

from flask import Flask, current_app


class EInfraOIDCApp:
    """EInfra OIDC extension."""

    def __init__(self, app: Flask | None = None):
        """Create the extension."""
        if app:
            self.init_app(app)

    def init_app(self, app: Flask) -> None:
        """Add the extension to the app and loads initial configuration."""
        self.app = app

        app.extensions["einfra-oidc"] = self
        self.init_config(app)

    def init_config(self, app: Flask) -> None:
        """Load the default configuration."""
        # sets the default configuration values
        from . import config

        for k in dir(config):
            if k.startswith("EINFRA_"):
                app.config.setdefault(k, getattr(config, k))

        if not app.config.get("EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY"):
            app.config["EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY"] = app.config.get("EINFRA_RSA_KEY")

        if not app.config["EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY"]:
            raise RuntimeError("EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY is not configured")

    @cached_property
    def community_roles_with_priorities(self) -> dict[str, int]:
        """Returns a dictionary mapping community role names to their priority index.

        The priority index is used to sort roles by their priority, with the highest priority first.
        """
        return {role["name"]: idx for idx, role in enumerate(self.app.config["COMMUNITIES_ROLES"])}

    @cached_property
    def dump_enabled(self) -> bool:
        """Check if the S3 dump configuration is properly set up.

        Returns True if all required S3 configuration values are set and non-empty.
        """
        return bool(
            current_app.config.get("EINFRA_USER_DUMP_S3_ACCESS_KEY")
            and current_app.config.get("EINFRA_USER_DUMP_S3_SECRET_KEY")
            and current_app.config.get("EINFRA_USER_DUMP_S3_ENDPOINT")
            and current_app.config.get("EINFRA_USER_DUMP_S3_BUCKET"),
        )
