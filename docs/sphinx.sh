#!/bin/bash

# Try to ensure we're in the project 'root' for relative paths etc to work.
cd "$(dirname $0)/.."

PATH=bin/:$PATH

sphinx-apidoc -f -T -e -o docs/source/apidoc pyramid_jsonapi
# Generate config docs from python method
python -c 'import pyramid_jsonapi.settings as pjs; s = pjs.Settings({}); print(s.sphinx_doc())' >docs/source/apidoc/settings.inc
travis-sphinx build
if [[ $TRAVIS_BRANCH == "master" && -n $TRAVIS_TAG ]]; then
  travis-sphinx deploy
fi
