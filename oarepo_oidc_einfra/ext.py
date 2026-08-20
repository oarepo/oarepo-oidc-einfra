# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""A Flask extension for E-INFRA OIDC authentication."""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING, cast

from flask import Flask, current_app

if TYPE_CHECKING:
    from oarepo_oidc_einfra.perun.entitlements import EntitlementsParser


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
            raise RuntimeError("EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY is not configured")  # pragma: no cover

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

    @cached_property
    def entitlements_parser(self) -> EntitlementsParser:
        """Return the entitlements parser function."""
        return cast("EntitlementsParser", current_app.config.get("EINFRA_ENTITLEMENTS_PARSER"))
