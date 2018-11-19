#!/bin/bash
set -x
source $HOME/verdi/bin/activate

BASE_PATH=$(dirname "${BASH_SOURCE}")

echo "##########################################" 1>&2
echo -n "create MegaRules job: " 1>&2
date 1>&2
python $BASE_PATH/megarules.py > megarules.log 2>&1
STATUS=$?

echo -n "Finished creating Megarules: " 1>&2
date 1>&2
if [ $STATUS -ne 0 ]; then
  echo "Failed to create Megarules." 1>&2
  cat megarules.log 1>&2
  echo "{}"
  exit $STATUS
fi

exit 0
