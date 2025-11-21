#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

"""E-INFRA OIDC Auth backend for OARepo."""

from __future__ import annotations

from .remote import EINFRA_LOGIN_APP

__version__ = "2.0.0dev1"

__all__ = ("EINFRA_LOGIN_APP", "__version__")
