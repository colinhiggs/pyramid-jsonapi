pyramid-jsonapi project
=======================

.. image:: https://travis-ci.org/colinhiggs/pyramid-jsonapi.svg?branch=master
  :target: https://travis-ci.org/colinhiggs/pyramid-jsonapi

.. image:: https://coveralls.io/repos/github/colinhiggs/pyramid-jsonapi/badge.svg?branch=master
  :target: https://coveralls.io/github/colinhiggs/pyramid-jsonapi?branch=master

Create a JSON-API (`<http://jsonapi.org/>`_) standard API from a database using
the sqlAlchemy ORM and pyramid framework.

The core idea behind pyramid-jsonapi is to create a working JSON-API
automatically, starting from the sort of ``models.py`` file shipped with a
typical pyramid + sqlalchemy application.


Documentation
-------------

Documentation is available at: `<https://colinhiggs.github.io/pyramid-jsonapi/>`_

Installation
------------

* Stable releases are now uploaded to pypi:
  `<https://pypi.python.org/pypi?:action=display&name=pyramid_jsonapi>`_. You
  can install it in the usual way:

  .. code-block:: bash

    pip install -i pyramid_jsonapi

* Development releases are also uploaded to pypi. These have versions with
  '.devN' appended, where 'N' is the number of commits since the stable tag. You
  can install the latest one (perhaps into a virtualenv for play purposes) with

  .. code-block:: bash

    pip install --pre -i pyramid_jsonapi

* You can download the development version from
  `<https://github.com/colinhiggs/pyramid-jsonapi>`_ and add the directory you
  downloaded/cloned to to your PYTHONPATH.

Auto-Creating an API
--------------------

Declare your models somewhere using sqlalchemy's
:func:`sqlalchemy.ext.declarative.declarative_base`. In this documentation we
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

    # The usual stuff from the pyramid alchemy setup.
    config = Configurator(settings=settings)

    # pyramid_jsonapi uses the renderer labeled 'json'. As usual, if you have
    # any types to serialise that the default JSON renderer can't handle, you
    # must alter it. For example:
    renderer = JSON()
    renderer.add_adapter(datetime.date, datetime_adapter)
    config.add_renderer('json', renderer)

    # Instantiate a PyramidJSONAPI class instance
    # The third argument is optional, and should be a callable which accepts a
    # CollectionView instance as an argument and returns a database session.
    # This is only needed if you are using the 'old-style' pyramid approach
    # of passing around a single dbsession object.
    # If this argument is unused, pyramid_jsonapi will use the dbsession
    # object contained in the pyramid view.request.
    pj = pyramid_jsonapi.PyramidJSONAPI(config, models, lambda view: models.DBSession)

    # Create the routes and views automagically:
    pj.create_jsonapi_using_magic_and_pixie_dust()

    # Routes and views are added imperatively, so no need for a scan - unless
    # you have defined other routes and views declaratively.
    return config.make_wsgi_app()

Yes, there really is a method called
:func:`pyramid_jsonapi.PyramidJSONAPI.create_jsonapi_using_magic_and_pixie_dust`. No, you
don't *have* to call it that. If you are feeling more sensible you can use the
synonym :func:`pyramid_jsonapi.PyramidJSONAPI.create_jsonapi`.
