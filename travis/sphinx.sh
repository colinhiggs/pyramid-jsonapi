#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
   sphinx-apidoc -o docs/source pyramid_jsonapi
   travis-sphinx build
   travis-sphinx deploy
fi
