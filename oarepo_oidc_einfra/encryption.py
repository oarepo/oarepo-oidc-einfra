# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Encryption and decryption of request id using FernetEngine encryption."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from flask import current_app
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine

if TYPE_CHECKING:
    from uuid import UUID


def encrypt(request_id: str | UUID) -> str:
    """Encrypt the request id using FernetEngine encryption."""
    return cast("str", _get_engine().encrypt(str(request_id)))


def decrypt(encrypted_request_id: str) -> str:
    """Decrypt the request id using FernetEngine encryption."""
    return cast("str", _get_engine().decrypt(encrypted_request_id))


def _get_engine() -> FernetEngine:
    engine = FernetEngine()
    engine._update_key(  # noqa: SLF001 # protected member access
        current_app.config["SECRET_KEY"]
    )
    return engine
