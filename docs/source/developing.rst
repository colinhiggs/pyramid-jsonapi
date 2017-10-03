Developing pyramid-jsonapi
==========================

Contribution
-------------

All contributions are welcome!  You can contribute by making *pull requests* to the git repo:
`<https://github.com/colinhiggs/pyramid-jsonapi>`_

Travis is run against all PRs and commits to ensure consistent, high-quality code.

Tests
^^^^^^

`unittest` tests should be created for all new code. Coverage can be reviewd at:
`<https://coveralls.io/github/colinhiggs/pyramid-jsonapi>`_

PEP8
^^^^
Code should pass PEP8 validation:
* long lines should be avoided, but not at the expense of readability. (pep8 --ignore=E501).

pylint
^^^^^^

Code should pass pylint validation.
# pylint: disable=xxx is allowed where there is a clear reason for doing so. Please document as necessary.

Idiomatic Python
^^^^^^^^^^^^^^^^
Is to be preferred wherever possible.

Python Versions
^^^^^^^^^^^^^^^^
Currently authomatic is built and tested against python 3. 3.4 or later is recommended.

Versioning
^^^^^^^^^^^
Semantic versioning should be used, see `<https://semver.org>`_ for details.


Documentation
=============

Docuemntation is built using sphinx. This is done automatically using Travis for
certain builds (e.g. tagged releases) and pushed to the *gh-pages* branch.

Note that the documentation uses the *sphinx-rtd-theme* which may need to be installed
before the documentation can be built.

To manually build the documentation:

.. code-block:: bash

  # Generate package documentation automatically
  sphinx-apidoc -T -e -o docs/source/apidoc pyramid_jsonapi

  # Generate documentation of configuration options (pyramid inifile)
  python -c 'import pyramid_jsonapi.settings as pjs; s = pjs.Settings({}); print(s.sphinx_doc())' >docs/source/apidoc/settings.inc

  # Build sphinx documentation
  cd doc
  make html # or some other supported target.
