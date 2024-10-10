from datetime import datetime, UTC

import click

from oarepo_oidc_einfra.perun.dump import import_dump_file
from oarepo_oidc_einfra.tasks import update_from_perun_dump

from flask.cli import with_appcontext
from werkzeug.local import LocalProxy
from flask import current_app
from invenio_accounts.models import User, UserIdentity
import boto3
from io import BytesIO
import json

from invenio_db import db


@click.group()
def einfra():
    """EInfra commands."""
    pass

@einfra.command("import_dump")
@click.argument("dump_file")
@with_appcontext
def import_dump(dump_file):
    """
    Import a dump file.

    :param dump_file: Path to the dump file to import.
    """
    click.echo(f"Importing dump file {dump_file}")

    with open(dump_file, "rb") as f:
        path = import_dump_file(f.read())

    update_from_perun_dump.delay(path)

@einfra.command("update_from_dump")
@click.argument("dump-name")
@click.option("--on-background/--on-foreground", default=False)
@click.option('--fix-communities-in-perun/--no-fix-communities-in-perun', default=True)
@with_appcontext
def update_from_dump(dump_name, on_background, fix_communities_in_perun):
    """Update the data from the last imported dump."""
    if on_background:
        update_from_perun_dump.delay(dump_name, fix_communities_in_perun=fix_communities_in_perun)
    else:
        update_from_perun_dump(dump_name, fix_communities_in_perun=fix_communities_in_perun)


@einfra.command("add_einfra_user")
@click.argument("email")
@click.argument("einfra_id")
@with_appcontext
def add_einfra_user(email, einfra_id):
    _add_einfra_user(email, einfra_id)


def _add_einfra_user(email, einfra_id):
    _datastore = LocalProxy(lambda: current_app.extensions["security"].datastore)

    email = email.lower()
    user = User.query.filter_by(email=email).first()
    if not user:
        kwargs = {
            "email": email,
            "password": None,
            "active": True,
            "confirmed_at": datetime.now(UTC),
        }
        created = _datastore.create_user(**kwargs)
        db.session.commit()

        user = User.query.filter_by(email=email).first()
        assert user is not None

    identity = UserIdentity.query.filter_by(
        method="e-infra", id=einfra_id, id_user=user.id
    ).first()
    if not identity:
        UserIdentity.create(
            user=user,
            method="e-infra",
            external_id=einfra_id,
        )
        db.session.commit()


@einfra.command("import_dump_users")
@click.argument("dump_path")
@with_appcontext
def import_dump_users(dump_path):
    client = boto3.client(
        's3',
        aws_access_key_id=current_app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=current_app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )

    with BytesIO() as obj:
        client.download_fileobj(
            Bucket=current_app.config["EINFRA_USER_DUMP_S3_BUCKET"],
            Key=dump_path,
            Fileobj=obj)
        obj.seek(0)
        data = json.loads(obj.getvalue().decode("utf-8"))

    for user_data in data['users'].values():
        einfra_id = user_data["attributes"].get(
            "urn:perun:user:attribute-def:virt:login-namespace:einfraid-persistent"
        )
        email = user_data["attributes"].get(
            "urn:perun:user:attribute-def:def:preferredMail"
        )
        if not email or not einfra_id:
            continue
        print("Fixing user", email, einfra_id)
        _add_einfra_user(email, einfra_id)
