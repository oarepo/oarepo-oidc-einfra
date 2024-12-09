#
# Copyright (C) 2024 CESNET z.s.p.o.
#
# oarepo-oidc-einfra  is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.
#
import contextlib
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Generator

import pytest
import yaml

from oarepo_oidc_einfra.perun import PerunLowLevelAPI

logging.basicConfig(level=logging.INFO)
opensearch_logger = logging.getLogger("opensearch")
opensearch_logger.setLevel(logging.ERROR)


@pytest.fixture(scope="module")
def create_app(instance_path, entry_points):
    """Application factory fixture."""
    from invenio_app.factory import create_app

    return create_app


@pytest.fixture(scope="module")
def app_config(app_config):
    app_config["CELERY_TASK_ALWAYS_EAGER"] = True
    app_config["CELERY_TASK_EAGER_PROPAGATES"] = True

    # do not automatically run community synchronization in tests
    app_config["EINFRA_COMMUNITY_SYNCHRONIZATION"] = False
    app_config["EINFRA_COMMUNITY_MEMBER_SYNCHRONIZATION"] = False

    app_config["EINFRA_API_URL"] = "https://perun-api.acc.aai.e-infra.cz"
    app_config["COMMUNITIES_ROLES"] = [
        dict(
            name="curator",
            title="Curator",
            description="Can curate records.",
            can_manage=True,
            is_owner=True,
            can_manage_roles=["member"],
        ),
        dict(
            name="member",
            title="Member",
            description="Community member with read permissions.",
        ),
    ]

    password_path = Path(__file__).parent.parent / ".perun_passwd"
    if password_path.exists():
        app_config["EINFRA_SERVICE_PASSWORD"] = password_path.read_text().strip()
    else:
        app_config["EINFRA_SERVICE_PASSWORD"] = "dummy"

    app_config["EINFRA_SERVICE_ID"] = 143975
    app_config["EINFRA_SERVICE_USERNAME"] = "nrp-fa-devrepo"

    # test communities group
    # Note: you need to have templates & notifications set up on this group
    app_config["EINFRA_COMMUNITIES_GROUP_ID"] = 16460

    app_config["EINFRA_REPOSITORY_VO_ID"] = 4003
    app_config["EINFRA_REPOSITORY_FACILITY_ID"] = 4662
    app_config["EINFRA_CAPABILITIES_ATTRIBUTE_ID"] = 3585
    app_config["EINFRA_SYNC_SERVICE_ID"] = 1020
    app_config["EINFRA_SYNC_SERVICE_NAME"] = "test-sync"
    app_config["EINFRA_RSA_KEY"] = (
        b"-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmho5h/lz6USUUazQaVT3\nPHloIk/Ljs2vZl/RAaitkXDx6aqpl1kGpS44eYJOaer4oWc6/QNaMtynvlSlnkuW\nrG765adNKT9sgAWSrPb81xkojsQabrSNv4nIOWUQi0Tjh0WxXQmbV+bMxkVaElhd\nHNFzUfHv+XqI8Hkc82mIGtyeMQn+VAuZbYkVXnjyCwwa9RmPOSH+O4N4epDXKk1V\nK9dUxf/rEYbjMNZGDva30do0mrBkU8W3O1mDVJSSgHn4ejKdGNYMm0JKPAgCWyPW\nJDoL092ctPCFlUMBBZ/OP3omvgnw0GaWZXxqSqaSvxFJkqCHqLMwpxmWTTAgEvAb\nnwIDAQAB\n-----END PUBLIC KEY-----\n"
    )
    app_config["EINFRA_DUMP_DATA_URL"] = "/tmp"

    from oarepo_oidc_einfra import EINFRA_LOGIN_APP

    app_config["OAUTHCLIENT_REMOTE_APPS"] = {"e-infra": EINFRA_LOGIN_APP}

    app_config["JSONSCHEMAS_HOST"] = "localhost"
    app_config["RECORDS_REFRESOLVER_CLS"] = (
        "invenio_records.resolver.InvenioRefResolver"
    )
    app_config["RECORDS_REFRESOLVER_STORE"] = (
        "invenio_jsonschemas.proxies.current_refresolver_store"
    )
    app_config["RATELIMIT_AUTHENTICATED_USER"] = "200 per second"
    app_config["SEARCH_HOSTS"] = [
        {
            "host": os.environ.get("OPENSEARCH_HOST", "localhost"),
            "port": os.environ.get("OPENSEARCH_PORT", "9200"),
        }
    ]
    # disable redis cache
    app_config["CACHE_TYPE"] = "SimpleCache"  # Flask-Caching related configs
    app_config["CACHE_DEFAULT_TIMEOUT"] = 300
    app_config["FILES_REST_STORAGE_CLASS_LIST"] = {
        "L": "Local",
        "F": "Fetch",
        "R": "Remote",
    }
    app_config["FILES_REST_DEFAULT_STORAGE_CLASS"] = "L"

    app_config["APP_THEME"] = ["oarepo", "semantic-ui"]

    app_config["SERVER_NAME"] = "127.0.0.1:5000"

    app_config["EINFRA_CONSUMER_KEY"] = os.environ.get("INVENIO_EINFRA_CONSUMER_KEY")
    app_config["EINFRA_CONSUMER_SECRET"] = os.environ.get(
        "INVENIO_EINFRA_CONSUMER_SECRET"
    )

    app_config["EINFRA_USER_DUMP_S3_ACCESS_KEY"] = "tests"
    app_config["EINFRA_USER_DUMP_S3_SECRET_KEY"] = "teststests"
    app_config["EINFRA_USER_DUMP_S3_ENDPOINT"] = "http://localhost:19000"
    app_config["EINFRA_USER_DUMP_S3_BUCKET"] = "einfra-user-dumps"

    return app_config


@pytest.fixture()
def s3_dump_bucket(app):
    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client(
        "s3",
        aws_access_key_id=app.config["EINFRA_USER_DUMP_S3_ACCESS_KEY"],
        aws_secret_access_key=app.config["EINFRA_USER_DUMP_S3_SECRET_KEY"],
        endpoint_url=app.config["EINFRA_USER_DUMP_S3_ENDPOINT"],
    )
    # create bucket
    try:
        client.create_bucket(Bucket=app.config["EINFRA_USER_DUMP_S3_BUCKET"])
    except ClientError:
        pass


@pytest.fixture(scope="module", autouse=True)
def location(location):
    return location


@pytest.fixture()
def perun_api_url(app):
    return app.config["EINFRA_API_URL"]


@pytest.fixture()
def perun_service_username(app):
    return app.config["EINFRA_SERVICE_USERNAME"]


@pytest.fixture()
def perun_service_password(app):
    return app.config["EINFRA_SERVICE_PASSWORD"]


@pytest.fixture()
def perun_sync_service_id(app):
    return app.config["EINFRA_SYNC_SERVICE_ID"]


@pytest.fixture()
def test_vo_id(app):
    return app.config["EINFRA_REPOSITORY_VO_ID"]


@pytest.fixture()
def test_facility_id(app):
    return app.config["EINFRA_REPOSITORY_FACILITY_ID"]


@pytest.fixture()
def test_capabilities_attribute_id(app):
    return app.config["EINFRA_CAPABILITIES_ATTRIBUTE_ID"]


@pytest.fixture()
def test_repo_communities_id(app):
    return app.config["EINFRA_COMMUNITIES_GROUP_ID"]


@pytest.fixture()
def low_level_perun_api(perun_api_url, perun_service_username, perun_service_password):
    return PerunLowLevelAPI(
        base_url=perun_api_url,
        service_username=perun_service_username,
        service_password=perun_service_password,
    )


@pytest.fixture()
def constants_template():
    constants_file = Path(__file__).parent / "constants_template.yaml"
    with constants_file.open() as f:
        return SimpleNamespace(**{k: str(v) for k, v in yaml.safe_load(f).items()})


@pytest.fixture()
def constants(constants_template):
    constants_file = Path(__file__).parent.parent / ".perun_constants.yaml"
    if not constants_file.exists():
        return constants_template
    with constants_file.open() as f:
        return SimpleNamespace(**{k: str(v) for k, v in yaml.safe_load(f).items()})


@pytest.fixture()
def smart_record(perun_api_url, low_level_perun_api, constants, constants_template):
    import responses
    from responses._recorder import Recorder

    @contextlib.contextmanager
    def smart_record(fname) -> Generator[SimpleNamespace, None, None]:
        file_path = Path(__file__).parent / "request_data" / fname
        if not file_path.exists():
            print(f"Could not find recorded data at path {file_path}, recording ...")
            with Recorder() as recorder:
                yield constants
                messages = recorder.get_registry().registered
                for r in messages:
                    replace_in_response(
                        r,
                        source_constants=constants,
                        target_constants=constants_template,
                    )
                recorder.dump_to_file(file_path=file_path, registered=messages)
        else:
            print(f"Using recorded data from path {file_path}")
            low_level_perun_api._auth = (
                None  # reset the auth just to make sure we use the recorded data
            )
            with responses.RequestsMock() as rsps:
                rsps._add_from_file(file_path=file_path)
                yield constants_template

    return smart_record


def replace_in_response(resp, source_constants, target_constants):
    if not resp.body:
        return
    content = json.loads(resp.body)

    replacement_map = {
        getattr(source_constants, k): getattr(target_constants, k)
        for k in dir(source_constants)
        if not k.startswith("_")
    }

    def replace_recursively(data):
        if isinstance(data, dict):
            return {k: replace_recursively(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [replace_recursively(v) for v in data]
        if data in (True, False, None):
            return data
        data = str(data)
        return replacement_map.get(data, data)

    content = replace_recursively(content)
    resp.body = json.dumps(content)


@pytest.fixture(scope="function")
def test_group_id():
    with (
        Path(__file__).parent / "request_data" / "test_create_group.yaml"
    ).open() as f:
        data = yaml.safe_load(f)
        payload = json.loads(data["responses"][1]["response"]["body"])
        return payload["id"]


@pytest.fixture()
def test_ui_pages(app):
    python_path = Path(sys.executable)
    invenio_instance_path = python_path.parent.parent / "var" / "instance"
    manifest_path = invenio_instance_path / "static" / "dist"
    manifest_path.mkdir(parents=True, exist_ok=True)
    shutil.copy(
        Path(__file__).parent / "manifest.json", manifest_path / "manifest.json"
    )

    app.jinja_loader.searchpath.append(str(Path(__file__).parent / "templates"))
