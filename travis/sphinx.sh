#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
  sphinx-apidoc -T -e -o docs/source/apidoc pyramid_jsonapi
  # Generate config docs from python method
  python -c 'import pyramid_jsonapi.settings as pjs; s = pjs.Settings({}); s.sphinx_doc()' >docs/source/apidoc/settings.inc
  travis-sphinx build
  travis-sphinx deploy
fi
