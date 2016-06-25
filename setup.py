from distutils.core import setup

version = '0.2'

requires = [
    'pyramid',
    'SQLAlchemy',
    ]

setup(
  name = 'pyramid_jsonapi',
  packages = ['pyramid_jsonapi'],
  version = version,
  description = 'Auto-build JSON API from sqlalchemy models using the pyramid framework',
  author = 'Colin Higgs',
  author_email = 'colin.higgs70@gmail.com',
  url = 'https://github.com/colinhiggs/pyramid-jsonapi',
  download_url =\
    'https://github.com/colinhiggs/pyramid-jsonapi/tarball/{}'.format(version),
  keywords = ['json', 'api', 'API', 'JSON-API', 'pyramid', 'sqlalchemy'],
  classifiers = [],
)
