#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
  sphinx-apidoc -T -o docs/source pyramid_jsonapi
  travis-sphinx build
  travis-sphinx deploy
fi
