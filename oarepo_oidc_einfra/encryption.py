#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Encryption and decryption of request id using FernetEngine encryption."""

from uuid import UUID

from flask import current_app
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine


def encrypt(request_id: str | UUID) -> str:
    """Encrypt the request id using FernetEngine encryption."""
    return _get_engine().encrypt(str(request_id))


def decrypt(encrypted_request_id: str) -> str:
    """Decrypt the request id using FernetEngine encryption."""
    return _get_engine().decrypt(encrypted_request_id)


def _get_engine() -> FernetEngine:
    engine = FernetEngine()
    engine._update_key(current_app.config["SECRET_KEY"])
    return engine
