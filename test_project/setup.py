import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.txt')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    'openapi_spec_validator',
    'psycopg2',
    'pyramid',
    'pyramid_debugtoolbar',
    'pyramid_jsonapi',
    'pyramid_tm',
    'SQLAlchemy',
    'testing.postgresql',
    'transaction',
    'waitress',
    'webtest',
    'zope.sqlalchemy',
    'parameterized',
    ]

setup(name='test_project',
      version='1.0',
      description='test_project',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='',
      author_email='',
      url='',
      keywords='web wsgi bfg pylons pyramid',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      test_suite='test_project',
      install_requires=requires,
      entry_points="""\
      [paste.app_factory]
      main = test_project:main
      [console_scripts]
      initialize_test_project_db = test_project.scripts.initializedb:main
      """,
      )
