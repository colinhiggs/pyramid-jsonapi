#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
  # Generate api docs, rmeove modules.rst as we don't
  # Use it and it's xistence raises an error
  sphinx-apidoc -o docs/source pyramid_jsonapi
  rm -f docs/source/modules.rst
  travis-sphinx build
  travis-sphinx deploy
fi
