#!/bin/bash

# Try to ensure we're in the project 'root' for relative paths etc to work.
cd "$(dirname $0)/.."

PATH=bin/:$PATH
SOURCE=docs/source
TARGET=docs/build

sphinx-apidoc -f -T -e -o ${SOURCE}/apidoc pyramid_jsonapi
# Generate config docs from python method
python -c 'import pyramid_jsonapi.settings as pjs; s = pjs.Settings({}); print(s.sphinx_doc())' >docs/source/apidoc/settings.inc
travis-sphinx build --source=${SOURCE} --outdir=${TARGET}
# Get a pylint badge
wget https://mperlet.de/pybadge/badges/$(pylint pyramid_jsonapi |grep "rated at" |awk '{print $7}' |cut -f 1 -d '/').svg -O ${TARGET}/pylint-badge.svg
if [[ $TRAVIS_BRANCH == "master" && -n $TRAVIS_TAG ]]; then
  echo "Deploying docs to gh-pages..."
  travis-sphinx deploy --outdir=${TARGET}
fi
