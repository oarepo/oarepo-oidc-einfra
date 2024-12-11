#!/bin/bash

source .venv/bin/activate

python_files=$(
  ( git status --short| grep '^?' | cut -d\  -f2- && git ls-files ) | egrep ".*[.]py" | sort -u
)

python_files_without_tests=$(
  ( git status --short| grep '^?' | cut -d\  -f2- && git ls-files ) | egrep ".*[.]py" | egrep -v "^tests/" | sort -u
)
top_level_package=$(echo $python_files_without_tests | tr ' ' '\n' | grep '/' | cut -d/ -f1 | sort -u)

# python must not be in directories containing ' ', so no quotes here or inside the variable
ruff format -- $python_files
ruff check --fix $python_files_without_tests
python -m licenseheaders -t .copyright.tmpl -cy -f $python_files#

mypy --enable-incomplete-feature=NewGenericSyntax $top_level_package
