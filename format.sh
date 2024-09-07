#!/bin/bash

files="$( (git status --short| grep '^?' | cut -d\  -f2- && git ls-files ) | egrep ".*[.]py" | sort -u )"

black --target-version py310 "$files"
autoflake -r --in-place --remove-all-unused-imports "$files"
isort "$files" --profile black

python -m licenseheaders -t .copyright.tmpl -cy -f "$files"
