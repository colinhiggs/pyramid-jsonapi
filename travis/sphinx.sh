#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" && -n $TRAVIS_TAG ]]; then
  sphinx-apidoc -T -e -o docs/source/apidoc pyramid_jsonapi
  # Generate config docs from python method
  python -c 'import pyramid_jsonapi.settings as pjs; s = pjs.Settings({}); print(s.sphinx_doc())' >docs/source/apidoc/settings.inc
  travis-sphinx build
  travis-sphinx deploy
fi
