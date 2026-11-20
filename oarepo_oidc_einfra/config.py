# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Configuration for the E-INFRA OIDC authentication, can be overwritten in invenio.cfg ."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oarepo_oidc_einfra.perun.entitlements import EntitlementsParser

EINFRA_ENTITLEMENT_NAMESPACES = {"geant"}
"""URN prefix for capabilities that can represent community roles."""

EINFRA_ENTITLEMENT_PREFIX = "cesnet.cz"
"""Parts of the entitlement URN name that represent communities."""

EINFRA_ENTITLEMENT_ISSUER = "perun.cesnet.cz"
"""Fragment (after the ``#``) appended to and expected on entitlements.

Used both when generating entitlements and when validating incoming ones.
"""

EINFRA_RSA_KEY = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmho5h/lz6USUUazQaVT3"
    b"\nPHloIk/Ljs2vZl/RAaitkXDx6aqpl1kGpS44eYJOaer4oWc6/QNaMtynvlSlnkuW"
    b"\nrG765adNKT9sgAWSrPb81xkojsQabrSNv4nIOWUQi0Tjh0WxXQmbV+bMxkVaElhd"
    b"\nHNFzUfHv+XqI8Hkc82mIGtyeMQn+VAuZbYkVXnjyCwwa9RmPOSH+O4N4epDXKk1V"
    b"\nK9dUxf/rEYbjMNZGDva30do0mrBkU8W3O1mDVJSSgHn4ejKdGNYMm0JKPAgCWyPW"
    b"\nJDoL092ctPCFlUMBBZ/OP3omvgnw0GaWZXxqSqaSvxFJkqCHqLMwpxmWTTAgEvAb"
    b"\nnwIDAQAB\n-----END PUBLIC KEY-----\n"
)
"""Public RSA key for verifying the OIDC token signature."""

CESID_RSA_KEY = (
    b"-----BEGIN PUBLIC KEY-----\n"
    b"MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqYftrqNBoc8m2dl+6zFY\n"
    b"c3VdrsryUPFXFI4P3PV43Ph5FW4fxfIPgruGXLp/FjKXwtlAdCc0hc/l6gU0kVJz\n"
    b"fr71PNoVLAk/E3fi7c2t1SAtofraqtpLpVA/rkTtyGcPAttKUpqTBFFpKnK54sQ3\n"
    b"vZyNOhKB2P8a5i2YKHq/YR36eGn3o4IamYT4hD+RcOu8J0MyKIpr3SQi/z2Gz5v1\n"
    b"hKZSFnbXRLfyjqJMTvzE5RYxfs1TgCeYdWE5PW4db3fIo5ts7OIVyCyqLWSe6doL\n"
    b"BedmWWsbHhYWeEyw0qK7XWFAL9honTIKEB4kGVPkpQQPxJmuUPFsdHePFwWGXjYu\n"
    b"8QIDAQAB\n"
    b"-----END PUBLIC KEY-----\n"
)
"""Public RSA key for verifying the CESiD OIDC token signature.

The ``cas-signing-key`` from https://login.cesid.cesnet.cz/cas/oidc/jwks
"""

EINFRA_USER_DUMP_S3_ACCESS_KEY = ""
"""Access key for the S3 bucket where the user dump from PERUN is stored."""

EINFRA_USER_DUMP_S3_SECRET_KEY = ""
"""Secret key for the S3 bucket where the user dump from PERUN is stored."""

EINFRA_USER_DUMP_S3_ENDPOINT = ""
"""Endpoint for the S3 bucket where the user dump from PERUN is stored."""

EINFRA_USER_DUMP_S3_BUCKET = ""
"""Bucket where the user dump from PERUN is stored."""

EINFRA_USER_ID_DUMP_ATTRIBUTE = "urn:perun:user:attribute-def:virt:login-namespace:einfraid-persistent"
"""Attribute on user inside perun that represents the E-INFRA ID of the user."""

EINFRA_USER_DISPLAY_NAME_ATTRIBUTE = "urn:perun:user:attribute-def:core:displayName"
"""Attribute on user inside perun that represents the display name of the user."""

EINFRA_USER_ORGANIZATION_ATTRIBUTE = "urn:perun:user:attribute-def:def:organization"
"""Attribute on user inside perun that represents the organization of the user."""

EINFRA_USER_PREFERRED_MAIL_ATTRIBUTE = "urn:perun:user:attribute-def:def:preferredMail"
"""Attribute on user inside perun that represents the preferred mail of the user."""

EINFRA_CAPABILITIES_ATTRIBUTE_NAME = "urn:perun:resource:attribute-def:def:capabilities"
"""Attribute name for resource capabilities in the PERUN dump."""

EINFRA_LAST_DUMP_PATH = "nrp_invenio_export.json"
"""Path to the last dump file in the S3 bucket."""

EINFRA_TOKEN_EXCHANGE_ISSUER = "https://login.e-infra.cz/oidc/"  # noqa S105 not a password
"""Issuer of the token exchange token."""

EINFRA_TOKEN_EXCHANGE_PUBLIC_KEY = None
"""Public key of the token exchange token's issuer.

If not set, EINFRA_RSA_KEY is used instead.
"""

EINFRA_ENTITLEMENTS_PARSER: EntitlementsParser | None = None
"""Parser for entitlements from user info token."""
