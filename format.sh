#!/bin/bash

"$(dirname $0)/python_format.sh" $(( git status --short| grep '^?' | cut -d\  -f2- && git ls-files ) | egrep ".*[.]py" | sort -u )
`dirname $0`/python-packages/bin/python -m licenseheaders -t .copyright.tmpl -cy -f $(( git status --short| grep '^?' | cut -d\  -f2- && git ls-files ) | egrep ".*[.]py" | sort -u )
