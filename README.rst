*********************************
pyramid-jsonapi Documentation
*********************************

Create a JSON-API (`<http://jsonapi.org/>`_) standard API from a database using
the sqlAlchemy ORM and pyramid framework.

The core idea behind pyramid-jsonapi is to create a working JSON-API
automatically, starting from the sort of ``models.py`` file shipped with a
typical pyramid + sqlalchemy application.

If you are reading this document directly from the repository on github
(`<https://github.com/colinhiggs/pyramid-jsonapi>`_) you may notice some
oddities. In particular, internal links to things like ``:py:func:`blah``` which
don't work. That's because those directives are designed to be consumed by
sphinx (`<http://www.sphinx-doc.org/>`_). You can view the same document after
it has been run through sphinx, as well as the API documentation, at the
pyramid_jsonapi documentation page
(`<https://colinhiggs.github.io/pyramid-jsonapi/>`_).

Installation
============

There is a test release on testpypi:
`<https://testpypi.python.org/pypi?:action=display&name=pyramid_jsonapi>`_. You
can install it (perhaps into a virtualenv for play purposes) with

.. code-block:: bash

  pip install -i https://testpypi.python.org/pypi pyramid_jsonapi

or, since there is only one file, you can download the development version from
`<https://github.com/colinhiggs/pyramid-jsonapi>`_ and copy the pyramid_jsonapi
directory into your PYTHONPATH or into your project.

Auto-Creating an API
====================

Declare your models somewhere using sqlalchemy's
:py:func:`sqlalchemy.ext.declarative.declarative_base`. In this documentation we
assume that you have done so in a file called ``models.py``:

.. code-block:: python

  class Person(Base):
      __tablename__ = 'people'
      id = Column(BigInteger, primary_key=True, autoincrement=True)
      name = Column(Text)
      blogs = relationship('Blog', backref='owner')
      posts = relationship('Post', backref='author')

  # and the rest...

If you are happy with the defaults, you can get away with the following
additions to the standard pyramid alchemy scaffold's top level ``__init__.py``:

.. code-block:: python

  import pyramid_jsonapi
  # Or 'from . import pyramid_jsonapi' if you copied pyramid_jsonapi directly
  # into your project.

  from . import models # Your models module.

  def main(global_config, **settings):

    # The usual stuff from the pyramid alchemy scaffold.
    engine = engine_from_config(settings, 'sqlalchemy.')
    models.DBSession.configure(bind=engine)
    models.Base.metadata.bind = engine
    config = Configurator(settings=settings)

    # pyramid_jsonapi uses the renderer labeled 'json'. As usual, if you have
    # any types to serialise that the default JSON renderer can't handle, you
    # must alter it. For example:
    renderer = JSON()
    renderer.add_adapter(datetime.date, datetime_adapter)
    config.add_renderer('json', renderer)

    # Create the routes and views automagically:
    pyramid_jsonapi.create_jsonapi_using_magic_and_pixie_dust(
      config, models, lambda view: models.DBSession
    )
    # The third argument above should be a callable which accepts a
    # CollectionView instance as an argument and returns a database session.
    # Notably the request is available as view.request, so if you're doing
    # something like this post
    # https://metaclassical.com/what-the-zope-transaction-manager-means-to-me-and-you
    # you can return the per-request session. In this case we just return the
    # usual DBSession from the models module.

    # Routes and views are added imperatively, so no need for a scan - unless
    # you have defined other routes and views declaratively.

Yes, there really is a method called
:py:func:`pyramid_jsonapi.create_jsonapi_using_magic_and_pixie_dust`. No, you
don't *have* to call it that. If you are feeling more sensible you can use the
synonym :py:func:`pyramid_jsonapi.create_jsonapi`.

Calling :py:func:`pyramid_jsonapi.create_jsonapi`
-------------------------------------------------

Since :py:func:`pyramid_jsonapi.create_jsonapi` (or the one with pixie dust)
sits at the centre of the API creation, we'll spend a little time now explaining
the three mandatory arguments.

* ``config`` is the usual Configurator object used in pyramid.

* ``models`` can either be a module (as in the example above) defining classes
  which inherit from :py:func:`declarative_base` or an iterable of such classes.

* ``get_dbsession`` (to which we passed the lambda function above) should be a
  callable which accepts an instance of
  :py:class:`pyramid_jsonapi.CollectionViewBase` and returns a
  :py:class:`sqlalchemy.orm.session.Session` (or an equivalent, like a
  :py:func:`sqlalchemy.orm.scoped_session`)

Auto-Create Assumptions
-----------------------

#. Your model classes all inherit from a base class returned by sqlalchemy's
   ``declarative-base()``.

#. Each model has a single primary_key column. This will be auto-detected and
   copied to an attribute called ``_jsonapi_id``, so...

#. ...don't create any columns called ``_jsonapi_id``.

#. You are happy to give your collection end-points the same name as the
   corresponding database table (for now).

#. You have defined any relationships to exposed via the API using
   ``sqlalchemy.orm.relationship()`` (or ``backref()``).

#. You are happy to expose any so defined relationship via a relationship URL.

Some of those behaviours can be adjusted, see `Customising the Generated API`_.

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

  $ pserv your_project/development.ini

Using the rather lovely httpie `<https://github.com/jkbrzt/httpie/>`_ to test:

.. code-block:: bash

  $ http http://localhost:6543/people

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
          "self": "http://localhost:6543/people/1"
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

Customising the Generated API
=============================

Selectively Passing Models for API Generation
---------------------------------------------

Your database may have some tables which you do not wish to expose as collections in the generated API. You can be selective by:

* writing a models module with only the model classes you wish to expose; or
* passing an iterable of only the model classes you wish to expose to
  :py:func:`pyramid_jsonapi.create_jsonapi`.

Callbacks
---------

At certain points during the processing of a request, ``pyramid_jsonapi`` will
invoke any callback functions which have been registered. Callback sequences are
currently implemented as ordinary lists: you add your callback functions using
``.append()``, remove them with ``.pop()`` and so on. The functions in each
callback list will be called in order at the appropriate point.

Callback Lists
~~~~~~~~~~~~~~
