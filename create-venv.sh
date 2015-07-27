#!/bin/bash

if grep '^Ubuntu 14.04' /etc/issue
then
  pyvenv-3.4 --without-pip env
  source env/bin/activate
  curl https://bootstrap.pypa.io/get-pip.py | python3.4
  deactivate
else
  pyvenv-3.4 env
fi
source env/bin/activate
pip install -r requirements.txt
