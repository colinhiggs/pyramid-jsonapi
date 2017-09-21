#!/bin/bash

if [[ $TRAVIS_BRANCH == "master" ]]; then
   travis-sphinx build
   travis-sphinx deploy
fi
