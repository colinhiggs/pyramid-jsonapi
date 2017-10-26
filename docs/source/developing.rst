Developing pyramid-jsonapi
==========================

Development
-----------

This project is set up to use `buildout` to create a suitable testing environment.
Buildout works by installing all python dependencies as eggs to `eggs/` and setting up
scripts in `bin/` which include those eggs in the python path.
You can set up the buildout environment as follows:

.. code-block:: bash

  # Creates the buildout setup script.
  python3 bootstrap.py
  # Installs dependencies, builds documentation etc.
  bin/buildout

  # To run python with all dependencies satisfied:
  bin/python

  # To test the project:
  bin/nosetest


Contribution
-------------

All contributions are welcome!  You can contribute by making *pull requests* to
the git repo: `<https://github.com/colinhiggs/pyramid-jsonapi>`_

Travis (`<https://travis-ci.org/colinhiggs/pyramid-jsonapi>`_) is run against
all PRs and commits to ensure consistent, high-quality code.

Tests
^^^^^^

``unittest`` tests should be created for all new code. Coverage can be reviewd at:
`<https://coveralls.io/github/colinhiggs/pyramid-jsonapi>`_

PEP8
^^^^
Code should pass PEP8 validation:

  * long lines should be avoided, but not at the expense of readability. (``pep8 --ignore=E501`` is used when testing).

pylint
^^^^^^

Code should pass pylint validation.
``# pylint: disable=xxx`` is allowed where there is a clear reason for doing so. Please document as necessary.

Idiomatic Python
^^^^^^^^^^^^^^^^
Is to be preferred wherever possible.

Python Versions
^^^^^^^^^^^^^^^^
Currently pyramid_jsonapi is built and tested against python 3. 3.4 or later is recommended.

Versioning
^^^^^^^^^^^
Semantic versioning should be used, see `<https://semver.org>`_ for details.


Documentation
=============

Docuemntation is built using sphinx. This is done automatically using Travis for
certain builds (e.g. tagged releases) and pushed to the *gh-pages* branch.

Note that the documentation uses the ``sphinx-rtd-theme`` which is installed by buildout.

To manually build the documentation:

.. code-block:: bash

  docs/sphinx.sh

Documentation will be written to `target/doc/build/`
