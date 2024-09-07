#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Helper proxy to the state object."""

from flask import current_app
from werkzeug.local import LocalProxy

current_einfra_oidc = LocalProxy(lambda: current_app.extensions["einfra-oidc"])
"""Helper proxy to get the current einfra oidc."""
