# Getting started

## Make a virtual env

```bash
./create-venv.sh
```

Which does the following...

Clone the repo:
```bash
git clone https://github.com/colinhiggs/pyramid-jsonapi.git
```

Create a venv:
```bash
pyvenv env
```

On my Ubuntu 14.04 box pyvenv is a bit broken. I have to do this first:
```bash
pyvenv-3.4 --without-pip env
source env/bin/activate
curl https://bootstrap.pypa.io/get-pip.py | python3.4
deactivate
source env/bin/activate
```

Install requirements:
```bash
pip install -r requirements.txt
```
