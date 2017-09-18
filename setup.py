from setuptools import setup, find_packages
from version import get_version

requires = [
    'alchemyjsonschema',
    'jsonschema',
    'pyramid',
    'SQLAlchemy',
    ]

setup(
  name = 'pyramid_jsonapi',
  packages = ['pyramid_jsonapi'],
  install_requires=requires,
  version=get_version(),
  description = 'Auto-build JSON API from sqlalchemy models using the pyramid framework',
  author = 'Colin Higgs',
  author_email = 'colin.higgs70@gmail.com',
  url = 'https://github.com/colinhiggs/pyramid-jsonapi',
  keywords = ['json', 'api', 'API', 'JSON-API', 'pyramid', 'sqlalchemy'],
  classifiers = [],
  package_data={'': ['schema/*.json']}
  )
