#!/bin/bash

use_syspackage=0
while getopts "fth" opt; do
  case $opt in
  f)
    echo "changed not to use sys package. See venv/pyvenv.cfg"
    use_syspackage=0
    ;;
  t)
    echo "changed to use sys package. See venv/pyvenv.cfg"
    use_syspackage=1
    ;;
  h)
    printf "Usage: bash ${0} [-t|-f]\nOption: -t: uses syspackage, -f: does not\n"
    ;;
  esac
done

if [[ "$use_syspackage" == 1 ]]; then
  sed -i -e 's/false/true/' venv/pyvenv.cfg
else
  sed -i -e 's/true/false/' venv/pyvenv.cfg
fi
