#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
"""Configuration for the E-INFRA OIDC authentication, can be overwritten in invenio.cfg ."""

EINFRA_COMMUNITY_SYNCHRONIZATION = True
"""Synchronize community to E-Infra Perun when community is created."""

EINFRA_COMMUNITY_INVITATION_SYNCHRONIZATION = True
"""Synchronize community membership invitation to E-Infra Perun
    (create perun invitation) when user is invited in repository UI."""

EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION = True
"""Synchronize community membership to E-Infra Perun when user changes role within a community."""

EINFRA_ENTITLEMENT_NAMESPACES = {"geant"}
"""URN prefix for capabilities that can represent community roles."""

EINFRA_ENTITLEMENT_PREFIX = "cesnet.cz"
"""Parts of the entitlement URN name that represent communities."""

EINFRA_API_URL = "https://perun-api.e-infra.cz"
"""URL of the E-INFRA Perun API."""

EINFRA_RSA_KEY = b"-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmho5h/lz6USUUazQaVT3\nPHloIk/Ljs2vZl/RAaitkXDx6aqpl1kGpS44eYJOaer4oWc6/QNaMtynvlSlnkuW\nrG765adNKT9sgAWSrPb81xkojsQabrSNv4nIOWUQi0Tjh0WxXQmbV+bMxkVaElhd\nHNFzUfHv+XqI8Hkc82mIGtyeMQn+VAuZbYkVXnjyCwwa9RmPOSH+O4N4epDXKk1V\nK9dUxf/rEYbjMNZGDva30do0mrBkU8W3O1mDVJSSgHn4ejKdGNYMm0JKPAgCWyPW\nJDoL092ctPCFlUMBBZ/OP3omvgnw0GaWZXxqSqaSvxFJkqCHqLMwpxmWTTAgEvAb\nnwIDAQAB\n-----END PUBLIC KEY-----\n"
"""Public RSA key for verifying the OIDC token signature."""

#
# At least the following should be sent in your invenio.cfg
#

# EINFRA_SERVICE_USERNAME = "username"
# """Username of the service in the E-INFRA Perun."""

# EINFRA_SERVICE_PASSWORD = "password"
# """Password of the service in the E-INFRA Perun."""

# EINFRA_REPOSITORY_VO_ID = 0
# """Internal ID of the VO in the E-INFRA Perun that represents the repository."""

# EINFRA_COMMUNITIES_GROUP_ID = 0
# """Internal ID of the group in the E-INFRA Perun that represents the communities."""

# EINFRA_REPOSITORY_FACILITY_ID = 0
# """Internal ID of the facility in the E-INFRA Perun that represents the repository."""

EINFRA_CAPABILITIES_ATTRIBUTE_NAME = "urn:perun:resource:attribute-def:def:capabilities"
"""urn of the attribute in the E-INFRA Perun that represents the capabilities."""

# EINFRA_SYNC_SERVICE_NAME = "..."
# """name of the service in the E-INFRA Perun that is responsible for synchronization
# (creating and pushing dumps with resources and users)."""

# EINFRA_USER_DUMP_S3_ACCESS_KEY = ""
# """Access key for the S3 bucket where the user dump from PERUN is stored."""
#
# EINFRA_USER_DUMP_S3_SECRET_KEY = ""
# """Secret key for the S3 bucket where the user dump from PERUN is stored."""
#
# EINFRA_USER_DUMP_S3_ENDPOINT = ""
# """Endpoint for the S3 bucket where the user dump from PERUN is stored."""
#
# EINFRA_USER_DUMP_S3_BUCKET = ""
# """Bucket where the user dump from PERUN is stored."""

EINFRA_USER_ID_SEARCH_ATTRIBUTE = (
    "urn:perun:user:attribute-def:def:login-namespace:einfraid-persistent-shadow"
)
"""Attribute on user inside perun that represents the E-INFRA ID of the user."""

EINFRA_USER_ID_DUMP_ATTRIBUTE = (
    "urn:perun:user:attribute-def:virt:login-namespace:einfraid-persistent"
)
"""Attribute on user inside perun that represents the E-INFRA ID of the user."""

EINFRA_USER_DISPLAY_NAME_ATTRIBUTE = "urn:perun:user:attribute-def:core:displayName"
"""Attribute on user inside perun that represents the display name of the user."""

EINFRA_USER_ORGANIZATION_ATTRIBUTE = "urn:perun:user:attribute-def:def:organization"
"""Attribute on user inside perun that represents the organization of the user."""

EINFRA_USER_PREFERRED_MAIL_ATTRIBUTE = "urn:perun:user:attribute-def:def:preferredMail"
"""Attribute on user inside perun that represents the preferred mail of the user."""

EINFRA_DEFAULT_INVITATION_LANGUAGE = "en"
"""Language of the invitation emails that are sent to the users."""

EINFRA_LAST_DUMP_PATH = "nrp_invenio_export.json"
"""Path to the last dump file in the S3 bucket."""
