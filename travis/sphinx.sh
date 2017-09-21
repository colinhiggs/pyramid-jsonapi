#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
  sphinx-apidoc -T -e -o docs/source/apidoc pyramid_jsonapi
  travis-sphinx build
  travis-sphinx deploy
fi
