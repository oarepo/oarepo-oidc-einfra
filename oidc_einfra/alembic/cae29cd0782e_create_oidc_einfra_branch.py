#
# This file is part of Invenio.
# Copyright (C) 2016-2018 CERN.
#
# Invenio is free software; you can redistribute it and/or modify it
# under the terms of the MIT License; see LICENSE file for more details.

"""Create oidc-einfra branch."""


# revision identifiers, used by Alembic.
revision = "cae29cd0782e"
down_revision = None
branch_labels = ("oidc_einfra",)
depends_on = "72b37bb4119c"


def upgrade():
    """Upgrade database."""


def downgrade():
    """Downgrade database."""
