from setuptools import setup, find_packages

requires = [
    'pyramid',
    'SQLAlchemy',
    'jsonschema',
    ]

setup(
  name = 'pyramid_jsonapi',
  packages = ['pyramid_jsonapi'],
  setup_requires=['setuptools_scm'],
  use_scm_version=True,
  description = 'Auto-build JSON API from sqlalchemy models using the pyramid framework',
  author = 'Colin Higgs',
  author_email = 'colin.higgs70@gmail.com',
  url = 'https://github.com/colinhiggs/pyramid-jsonapi',
  keywords = ['json', 'api', 'API', 'JSON-API', 'pyramid', 'sqlalchemy'],
  classifiers = [],
  package_data={'': ['schema/*.json']}
  )
