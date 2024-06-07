#!/bin/bash

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
pip install "oarepo[tests]==${OAREPO_VERSION}.*"
pip install -e .
pip install pytest-invenio

pytest tests
