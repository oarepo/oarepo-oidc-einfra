import click
from flask.cli import with_appcontext
from invenio_accounts.models import User
from oarepo_runtime.cli import oarepo

from oidc_einfra.proxies import current_einfra_oidc
from oidc_einfra.utils import get_authenticated_identity


@oarepo.group()
def perun():
    """OIDC eInfra commands."""


@perun.command(name="groups")
@click.argument("user")
@with_appcontext
def list_groups(user):
    """List groups."""
    user = User.query.filter_by(email=user).one()
    aai_api = current_einfra_oidc.aai_api(user)

    for vo in aai_api.list_vos():
        print(vo)
        for grp in vo.list_groups():
            print(f"  {grp}")


@perun.group("communities")
def communities():
    pass


@communities.command("list")
def list_communities():
    pass


@communities.command("create")
@click.argument("community_id")
@click.argument("community_name")
@click.argument("user")
@with_appcontext
def create_community(community_id, community_name, user):
    """
    Create a new community

    :param community_id:   id of the community
    :param community_name: name of the community
    :param user: user with permissions to create the community and contact perun
    """
    user = User.query.filter_by(email=user).one()
    identity = get_authenticated_identity(user.id)
    communities_aai_api = current_einfra_oidc.communities_aai_api(identity)

    communities_aai_api.create_community(community_id, community_name)


@communities.command("synchronize")
@click.argument("user")
@with_appcontext
def create_community(user):
    """
    Create a new community

    :param community_id:   id of the community
    :param community_name: name of the community
    :param user: user with permissions to create the community and contact perun
    """
    user = User.query.filter_by(email=user).one()
    identity = get_authenticated_identity(user.id)
    communities_aai_api = current_einfra_oidc.communities_aai_api(identity)
    communities_aai_api.synchronize_communities()
