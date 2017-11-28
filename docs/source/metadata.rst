Metadata Modules
================

Metadata modules provide access to metadata about the API. The
:class:`pyramid_jsonapi.metadata` class is responsible for loading the modules
and setting up routes and views under ``/metadata``
(by default - see :mod:`pyramid_jsonapi.settings`).

Built-in Modules
----------------

The ``metadata_modules`` configuration option lists modules which are to be loaded
(see :mod:`pyramid_jsonapi.settings`). If this list is empty, no modules
will be loaded.

*Note*: Some modules are required for core functionality - for example schema
validation requires the ``jsonschema`` module.

The default setting for this option includes the following modules:

.. toctree::
   :glob:

   apidoc/pyramid_jsonapi.metadata.*

Custom Modules
--------------

As well as the built-in modules it is possible to write new metadata modules and add them to
the ``metadata_modules`` list.

Requirements
^^^^^^^^^^^^

Any modules must follow these rules in order to work properly:

* The module MUST contain a class with the same name as the package.
* The clas MUST expect to be passed a reference to the :class:`pyramid_jsonapi.JSONAPI` instance as the first argument.
* The class MAY contain a ``views`` attribute, which contains a list of :class:`pyramid_jsonapi.metadata.VIEWS` namedtuple instances.  These are mapped onto a
  :func:`pyramid.config.add_view` call. (Views are optional - methods may exist in modules to be called by other methods).


For example, to add a custom metadata module called ``Foo``, you need to do the following:

1. Create a ``Foo`` package, and ensure it is available to be imported in the python environment.

2. In ``Foo/__init__.py`` add the following:


.. code-block:: python

   class Foo():

       def __init__(self, api):

           self.views = [
               pyramid_jsonapi.metadata.VIEWS(
                   attr='generate_dict', # The method to associate with the view
                   route_name='',  # The relative route name to attach this method to (defaults to /metadata/Foo)
                   request_method='', # The http request method (defaults to GET)
                   renderer=''  # The pyramid renderer (defaults to json)
               ),
               pyramid_jsonapi.metadata.VIEWS(
                   attr='generate_string',
                   route_name='resource/{endpoint}',
                   request_method='GET',
                   renderer='string'
               ),
           ]

       def generate_dict(self, request):
           return {'foo': 'bar'}

       def generate_string(self, request):
          return "foo: {}".format(request.matchdict['endpoint'])


Note the use of the `Route pattern syntax <https://docs.pylonsproject.org/projects/pyramid/en/latest/narr/urldispatch.html#route-pattern-syntax>`_ in the second example would result in ``generate_string()`` being called for route ``/metadata/Foo/resource/baz`` with endpoint set to ``baz``.
