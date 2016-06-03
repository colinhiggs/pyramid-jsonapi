# Getting started

## Clone the repo:
Although you've quite possibly already done that if you're here...
```bash
git clone https://github.com/colinhiggs/pyramid-jsonapi.git
```

## Make a Virtual Env

```bash
./create-venv.sh
```

Which does the equivalent of the following...

Create a venv:
```bash
python3 -m venv env
```

*or*

On my Ubuntu 14.04 box venv is a bit broken. I have to do this first:
```bash
python3 -m venv --without-pip env
source env/bin/activate
curl https://bootstrap.pypa.io/get-pip.py | python3
deactivate
source env/bin/activate
```

Install requirements:
```bash
pip install -r requirements.txt
```

## Install Deps for Test Project

```bash
source env/bin/activate # if not already in virtualenv
cd test_project
python setup.py develop
```
