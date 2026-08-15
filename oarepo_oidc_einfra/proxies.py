# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Helper proxy to the state object."""

from __future__ import annotations

from typing import TYPE_CHECKING

from flask import current_app
from werkzeug.local import LocalProxy

if TYPE_CHECKING:
    from oarepo_oidc_einfra.ext import EInfraOIDCApp

current_einfra_oidc: EInfraOIDCApp = LocalProxy["EInfraOIDCApp"](lambda: current_app.extensions["einfra-oidc"])  # ty: ignore[invalid-assignment]
"""Helper proxy to get the current einfra oidc."""
