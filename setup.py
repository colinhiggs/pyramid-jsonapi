from setuptools import setup, find_packages
from pyramid_jsonapi.version import get_version

requires = [
    'alchemyjsonschema',
    'jsonschema',
    'pyramid',
    'SQLAlchemy',
    ]

setup(
  name = 'pyramid_jsonapi',
  packages = find_packages(),
  install_requires=requires,
  version=get_version(),
  description = 'Auto-build JSON API from sqlalchemy models using the pyramid framework',
  author = 'Colin Higgs',
  author_email = 'colin.higgs70@gmail.com',
  url = 'https://github.com/colinhiggs/pyramid-jsonapi',
  keywords = ['json', 'api', 'json-api', 'jsonapi', 'pyramid', 'sqlalchemy'],
  classifiers = [],
  package_data={'': ['schema/*.json']}
  )
