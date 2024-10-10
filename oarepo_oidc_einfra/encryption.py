from base64 import b64decode
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
