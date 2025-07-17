#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Helper proxy to the state object."""

from contextvars import ContextVar
from typing import TYPE_CHECKING

from flask import current_app
from werkzeug.local import LocalProxy

if TYPE_CHECKING:
    from oarepo_oidc_einfra.ext import EInfraOIDCApp

current_einfra_oidc: "EInfraOIDCApp" = (  # type: ignore
    LocalProxy["EInfraOIDCApp"](lambda: current_app.extensions["einfra-oidc"])
)
"""Helper proxy to get the current einfra oidc."""


synchronization_disabled = ContextVar(
    "synchronization_disabled",
    default=False,
)
"""
   Context variable to indicate if the synchronization with perun is disabled.

   Normally adding/removing/changing roles of the user is propagated to Perun as 
   we want to keep the state in sync.
   
   However, when user logs in, we do not want to propagate the changes to Perun
   as they have been just sent so they are already in sync. Setting this variable
   to True indicates that the synchronization is disabled and no changes should be
   propagated.
"""
