.. _getting-started:

Getting Started
================

Installation
------------

* Stable releases are uploaded to pypi:
  `<https://pypi.python.org/pypi?:action=display&name=pyramid_jsonapi>`_. You
  can install it in the usual way:

  .. code-block:: bash

    pip install -i pyramid_jsonapi

* Development releases are also uploaded to pypi. These have versions with
  '.devN' appended, where 'N' is the number of commits since the stable tag. You
  can install the latest one (perhaps into a virtualenv for play purposes) with

  .. code-block:: bash

    pip install --pre -i pyramid_jsonapi

* pyramid_jsonapi uses `Buildout <https://github.com/buildout/buildout>`_
  to manage development.  See the :ref:`developing` documentation for details.

* Since pyramid_jsonapi is pure python, You can download the latest code from
  `<https://github.com/colinhiggs/pyramid-jsonapi>`_ and add the directory you
  downloaded/cloned to to your PYTHONPATH.

Generating an API From Your Models
----------------------------------

First import the ``pyramid_jsonapi`` module and any model classes or modules which
you would like to expose as API collection endpoints. In your application's
``__init__.py``:

.. code-block:: python

  import pyramid_jsonapi
  from . import models

Then instantiate an api object:

.. code-block:: python

  pj_api = pyramid_jsonapi.PyramidJSONAPI(config, models, [get_db_session])

This is the class that encapsulates a whole API representing a set of models.
The constructor has two mandatory and one optional arguments:

* ``config`` is the usual Configurator object used in pyramid.

* ``models`` can either be a module (as in the example above) defining classes
  which inherit from :py:func:`declarative_base` or an iterable of such classes.

* ``get_dbsession`` (optional) should be a
  callable which accepts an instance of
  :class:`pyramid_jsonapi.CollectionViewBase` and returns a
  :class:`sqlalchemy.orm.session.Session` (or an equivalent, like a
  :func:`sqlalchemy.orm.scoped_session`)

Once you have an instance of ``PyramidJSONAPI`` you instruct it to build
endpoints (routes and views) with the method
``api.create_jsonapi_using_magic_and_pixie_dust()`` (or ``api.create_jsonapi()``). This
is deliberately a two step affair to give you the chance to manipulate certain
things (like the list of available endpoints) before the endpoints are
constructed:

.. code-block:: python

  pj_api = pyramid_jsonapi.PyramidJSONAPI(config, models)

  # Do something here like add a view for OPTIONS requests.

  pj_api.create_jsonapi_using_magic_and_pixie_dust()

Auto-Create Assumptions
-----------------------
#. Your model classes all inherit from a base class returned by sqlalchemy's
   ``declarative-base()``.

#. Each model has a single primary_key column. This will be auto-detected and
   stored in ``__pyramid_jsonapi__`` dict attr in the model.

#. Use a separate primary key for association objects rather than the
   composite key defined by the left and right referenced foreign keys.

#. You are happy to give your collection end-points the same name as the
   corresponding database table (can be overridden).

#. You have defined any relationships to exposed via the API using
   ``sqlalchemy.orm.relationship()`` (or ``backref()``).

#. You are happy to expose any so defined relationship via a relationship URL.

#. API endpoints will be provided at ``/api/...`` by default.

#. Metadata endpoints will be provided at ``/metadata/...`` by default.

Some of those behaviours can be adjusted, see :ref:`customisation`.

Trying Your API Out
-------------------

You should now have a working JSON-API. A quick test. The following assumes that
you have already created and set up a pyramid project in development mode
(``python setup.py develop`` in pyramid 1.6, ``pip install -e`` in pyramid 1.7).

Make sure you have activated your virtualenv:

.. code-block:: bash

  $ source env/bin/activate

Start the server:

.. code-block:: bash

  $ pserve your_project/development.ini

Assuming you have a collection named 'people' and using the rather lovely
`httpie <https://github.com/jkbrzt/httpie/>`_ to test:

.. code-block:: bash

  $ http http://localhost:6543/api/people

  HTTP/1.1 200 OK
  Content-Length: 1387
  Content-Type: application/vnd.api+json; charset=UTF-8
  Date: Fri, 28 Aug 2015 20:22:46 GMT
  Server: waitress

.. code-block:: json

  {
    "data": [
      {
        "attributes": {
          "name": "alice"
        },
        "id": "1",
        "links": {
          "self": "http://localhost:6543/api/people/1"
        },
        "relationships": {
          "<some_single_relationship>": {
            "data": {"type": "<rel_type>", "id": "<some_id>"}
          }
        }
      },
      {"<another_person>"}
    ]
  }


See ``test_project/test_project/__init__.py`` for a fully working
``__init__.py`` file.

You don't need a ``views.py`` unless you have some other routes and views.
