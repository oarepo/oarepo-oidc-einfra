# -*- coding: utf-8 -*-
#
# Copyright (C) 2023 CESNET.
#
# CESNET-OpenID-Remote is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""CESNET OIDC Auth backend for OARepo"""

from .remote import EINFRA_LOGIN_APP
from .version import __version__

__all__ = ("__version__", "EINFRA_LOGIN_APP")
