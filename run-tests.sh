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
pip install "oarepo[tests]==${OAREPO_VERSION}.*" --extra-index-url https://oarepo.github.io/pypi/packages/simple/
pip install -e '.[tests]'

pytest tests
