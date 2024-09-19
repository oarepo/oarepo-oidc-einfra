#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#

EINFRA_COMMUNITY_SYNCHRONIZATION = True
"""Synchronize community to E-Infra Perun when community is created."""

EINFRA_COMMUNITY_INVITATION_SYNCHRONIZATION = True
"""Synchronize community membership invitation to E-Infra Perun
    (create perun invitation) when user is invited in repository UI."""

EINFRA_ENTITLEMENT_NAMESPACES = ["geant"]
"""URN prefix for capabilities that can represent community roles."""

EINFRA_ENTITLEMENT_PREFIX = "cesnet.cz"
"""Parts of the entitlement URN name that represent communities."""

EINFRA_DUMP_DATA_URL = "s3://einfra-dump-bucket"
"""A place where the e-infra dump data will be stored when uploaded."""

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

# EINFRA_SERVICE_ID = 0
# """Internal ID of the service (whose username and password are above) in the E-INFRA Perun."""

# EINFRA_REPOSITORY_VO_ID = 0
# """Internal ID of the VO in the E-INFRA Perun that represents the repository."""

# EINFRA_COMMUNITIES_GROUP_ID = 0
# """Internal ID of the group in the E-INFRA Perun that represents the communities."""

# EINFRA_REPOSITORY_FACILITY_ID = 0
# """Internal ID of the facility in the E-INFRA Perun that represents the repository."""

# EINFRA_CAPABILITIES_ATTRIBUTE_ID = 0
# """Internal ID of the attribute in the E-INFRA Perun that represents the capabilities."""

# EINFRA_SYNC_SERVICE_ID = 0
# """Internal ID of the service in the E-INFRA Perun that is responsible for synchronization
# (creating and pushing dumps with resources and users)."""

EINFRA_USER_EINFRAID_ATTRIBUTE = "urn:perun:user:attribute-def:def:login-namespace:einfraid-persistent-shadow"
"""Attribute on user inside perun that represents the E-INFRA ID of the user."""
