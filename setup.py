import sys
from setuptools import setup, find_packages
# Append project to sys.path so that we can import version 'directly'.
# Importing as 'from pyramid_jsonapi import version' needs the deps we
# haven't installed yet!
sys.path.append("pyramid_jsonapi")
from version import get_version

requires = [
    'alchemyjsonschema',
    'jsonschema',
    'pkginfo',
    'pyramid',
    'pyramid_mako',
    'pyramid_settings_wrapper',
    'pyyaml',
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
  license = 'GNU Affero General Public License v3 or later (AGPLv3+)',
  url = 'https://github.com/colinhiggs/pyramid-jsonapi',
  keywords = ['json', 'api', 'json-api', 'jsonapi', 'jsonschema', 'openapi', 'pyramid', 'sqlalchemy'],
  classifiers = [
      'Development Status :: 5 - Production/Stable',
      'Framework :: Pyramid',
      'Intended Audience :: Developers',
      'License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)',
      'Programming Language :: Python :: 3',
      'Programming Language :: Python :: 3.4',
      'Programming Language :: Python :: 3.5',
      'Programming Language :: Python :: 3.6',
      'Topic :: Internet :: WWW/HTTP',
      'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
      'Topic :: Software Development :: Libraries :: Application Frameworks',
      'Topic :: Software Development :: Libraries :: Python Modules',
  ],
  package_data={'': ['schema/*.json',
                     'metadata/OpenAPI/swagger-ui/*.mako']}
  )
