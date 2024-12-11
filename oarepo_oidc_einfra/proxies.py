#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Helper proxy to the state object."""

from typing import TYPE_CHECKING

from flask import current_app
from werkzeug.local import LocalProxy

if TYPE_CHECKING:
    from oarepo_oidc_einfra.ext import EInfraOIDCApp

current_einfra_oidc: "EInfraOIDCApp" = (  # type: ignore
    LocalProxy["EInfraOIDCApp"](lambda: current_app.extensions["einfra-oidc"])
)
"""Helper proxy to get the current einfra oidc."""
