"""Helper proxy to the state object."""

from flask import current_app
from werkzeug.local import LocalProxy

current_einfra_oidc = LocalProxy(lambda: current_app.extensions["einfra-oidc"])
"""Helper proxy to get the current einfra oidc."""
