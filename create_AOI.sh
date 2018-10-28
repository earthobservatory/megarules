#!/bin/bash
set -x
source $HOME/verdi/bin/activate

BASE_PATH=$(dirname "${BASH_SOURCE}")

# create AOI action
echo "##########################################" 1>&2
echo -n "create AOI job: " 1>&2
date 1>&2
python $BASE_PATH/create_AOI.py > create-AOI.log 2>&1
STATUS=$?

echo -n "Finished creating AOI: " 1>&2
date 1>&2
if [ $STATUS -ne 0 ]; then
  echo "Failed to create AOI." 1>&2
  cat create-AOI.log 1>&2
  echo "{}"
  exit $STATUS
fi

exit 0
