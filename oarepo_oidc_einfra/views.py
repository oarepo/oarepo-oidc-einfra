from flask import Blueprint

# Blueprint for the oarepo-oidc-einfra templates
blueprint = Blueprint(
    "oarepo_oidc_einfra_views",
    __name__,
    url_prefix="/oarepo-oidc-einfra",
    template_folder="templates",
)
