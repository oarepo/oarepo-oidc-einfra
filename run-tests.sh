#!/bin/bash

export PIP_EXTRA_INDEX_URL=https://gitlab.cesnet.cz/api/v4/projects/1408/packages/pypi/simple
export UV_EXTRA_INDEX_URL=https://gitlab.cesnet.cz/api/v4/projects/1408/packages/pypi/simple

PYTHON=python3

set -e

OAREPO_VERSION="${OAREPO_VERSION:-12}"

VENV=".venv"

if test -d $VENV ; then
  rm -rf $VENV
fi

$PYTHON -m venv $VENV
source $VENV/bin/activate

pip install -U setuptools pip wheel
pip install "oarepo[rdm,tests]==${OAREPO_VERSION}.*"
pip install -e '.[tests]'

pytest tests
