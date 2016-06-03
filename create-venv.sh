#!/bin/bash

if grep '^Ubuntu 14.04' /etc/issue
then
  python3 -m venv --without-pip env
  source env/bin/activate
  curl https://bootstrap.pypa.io/get-pip.py | python3
  deactivate
else
  python3 -m venv env
fi
source env/bin/activate
pip install -r requirements.txt
