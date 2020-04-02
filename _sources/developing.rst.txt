.. _developing:

Developing pyramid-jsonapi
==========================

Development
-----------

This project is set up to use `tox` to create a suitable testing environment.
You must first install `tox` - either system-wide, or in it's own virtualenv:

Set up the `tox` environment as follows:


.. code-block:: bash

  # To install tox
  python3 -mvenv toxenv
  toxenv/bin/pip install tox

  # To run tox and test the project:
  toxenv/bin/tox

*Note*: The `toxenv` virtualenv only exists to deliver `tox`, *NOT* for development.

`tox` creates it's own virtualenvs for testing in `.tox/` which can be used for code testing and development.
These contain all of the dependencies for both the project and testing, as well as the local `pyramid-jsonapi`

You can use these in the usual way for your own testing and development, e.g.:

.. code-block:: bash
  
  source .tox/py3/bin/activate


Contribution
-------------

All contributions are welcome!  You can contribute by making *pull requests* to
the git repo: `<https://github.com/colinhiggs/pyramid-jsonapi>`_

Travis (`<https://travis-ci.org/colinhiggs/pyramid-jsonapi>`_) is run against
all PRs and commits to ensure consistent, high-quality code.

Tests
^^^^^^

``unittest`` tests should be created for all new code. Coverage can be reviewed at:
`<https://coveralls.io/github/colinhiggs/pyramid-jsonapi>`_

PEP8
^^^^

Code should pass PEP8 validation:

  * long lines should be avoided, but not at the expense of readability. (``pycodestyle --ignore=E501`` is used when testing).

pylint
^^^^^^

Code should pass pylint validation:

  * ``# pylint: disable=xxx`` is allowed where there is a clear reason for doing so. Please document as necessary.

Idiomatic Python
^^^^^^^^^^^^^^^^
Is to be preferred wherever possible.

Python Versions
^^^^^^^^^^^^^^^^
Currently pyramid_jsonapi is built and tested against python 3. 3.4 or later is recommended.

Versioning
^^^^^^^^^^^
Semantic versioning should be used, see
`PEP440 - Version Identification and Dependency Specification <https://www.python.org/dev/peps/pep-0440/>`_
for details.


Documentation
-------------

Documentation is built using sphinx. This is done automatically using Travis for
certain builds (e.g. tagged releases) and pushed to the *gh-pages* branch.

Note that the documentation uses the ``sphinx-rtd-theme``

To manually build the documentation:

.. code-block:: bash

  docs/sphinx.sh

Documentation will be written to `docs/build/` (in .gitignore).
