.. _customisation:

Customising the Generated API
=============================

Configuration Options
---------------------

Configuration options are managed by :mod:`pyramid_settings_wrapper.Settings`.
This provides default values as class attributes.

.. include:: apidoc/settings.inc

Model Class Options
-------------------

The behaviour of classes (and, by extension, collections) is controlled via a special
class attribute, ``__pyramid_jsonapi__``. The value of this attribute should be
a dictionary with each key representing an option name and each value
representing the option value. For example, the following will create a
``Person`` class with a table name ``people`` in the database but a collection
name ``humans`` in the resulting API:

.. code-block:: python

  class Person(Base):
      __tablename__ = 'people'
      id = Column(BigInteger, primary_key=True, autoincrement=True)
      name = Column(Text)
      __pyramid_jsonapi__ = {
        'collection_name': 'humans'
      }

The available options are:

===============   ==========    ================================================
Option            Value Type    Description
===============   ==========    ================================================
collection_name   string        Name of collection in the API.
id_col_name       string        Used internally to track id column - do not use.
===============   ==========    ================================================

Model Column Options
--------------------

Some behaviours can be controlled on a column by column basis. SQLAlchemy uses
the special column attribute ``info`` to carry information (as a dictionary)
from third party modules (like pyramid_jsonapi). The pyramid_jsonapi module
expects column options as a dictionary stored in the ``pyramid_jsonapi`` key of
the ``info`` dictionary. For example, to make a column called
``invisible_column`` invisible to the API:

.. code-block:: python

  class Person(Base):
      __tablename__ = 'people'
      id = Column(BigInteger, primary_key=True, autoincrement=True)
      invisible_column = Column(Text)
      invisible_column.info.update({'pyramid_jsonapi': {'visible': False}})

Available column options:

===============   ==========    ================================================
Option            Value Type    Description
===============   ==========    ================================================
visible           Boolean       Whether or not to display this colum in the API.
===============   ==========    ================================================

Selectively Passing Models for API Generation
---------------------------------------------

Your database may have some tables which you do not wish to expose as collections in the generated API. You can be selective by:

* writing a models module with only the model classes you wish to expose; or
* passing an iterable of only the model classes you wish to expose to
  :func:`pyramid_jsonapi.PyramidJSONAPI`.

Modifying Endpoints
-------------------

Endpoints are created automatically from a dictionary: :data:`pyramid_jsonapi.EndpointsData.endpoints`.

This takes the following format:

.. code-block:: python

  {
    'query_parameters': {
      'fields': '',
      'filter': '',
      'page': ['limit', 'offset'],
      'sort': '',
    },
    'responses': {HTTPOK: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']}},
    'endpoints': {
      'item': {
        'request_schema': False,
        'route_pattern': '{'fields': ['id'], 'pattern': '{{{}}}'}',
        'http_methods': {
          'DELETE': {
            'function': 'delete',
            'responses'': { HTTPOk: {'reason': ['A server MUST return a 200 OK status code if a deletion request is successful']}},
          },
          'GET': {
            'function': 'get',
          },
          'PATCH': {
            'function': 'patch',
          },
        },
      },
    ... # other endpoints omitted
    }
  }

The ``endpoints`` and ``methods`` are the parts you are most likely to want to modify.

* There are 4 ``endpoints`` defined: ``collection``, ``item``, ``relationships`` and ``related``.
* Each ``endpoint`` may have ``route_pattern`` defined. This is a list of fields, and the format string used to join them. (``{sep}`` will be replaced with ``route_name_sep``)
* Each ``endpoint`` may have 0 or more ``http_methods`` defined. (``GET``, ``POST``, etc).
* Each ``endpoint`` may have ``responses`` defined. This is a dictionary of ``pyramid.httpexceptions`` keys, the value is a dict with ``reason``
  containing list of reasons for returning this response.
* ``request_schema`` defines whether or not this endpoint expects a request body (for jsonschema generation/validation).
* Each ``method`` must have ``function`` defined. This is the name (string) of the view function to call for this endpoint.
* Each ``method`` may have a ``renderer`` defined (if omitted, this defaults to ``'json'``).

Additionally, the following keys are provided (though are less likely to be modified).

* ``query_parameters`` defines the http query parameters that endpoints expect.
* ``responses`` defines the various http responses (keyed by ``pyramid.httpexceptions`` objects )
  that may be returned, and the reason(s) why.
* ``responses`` are used in the code to validate responses, and provide schema information.
* responses can be defined at a 'global', endpoint, or method level, and will be merged together as appropriate.
* you may wish to modify ``responses`` if your app wishes to return statuses outside of the schema,
  to prevent them being flagged as errors.

For example, to extend this structure to handle the ``OPTIONS`` ``http_method`` for all endpoints (e.g. for `CORS <https://enable-cors.org>`_):

.. code-block:: python

  ...

  # Create a view class method.
  def options_view(self):
      return ''

  # Instantiate the class
  pj = pyramid_jsonapi.PyramidJSONAPI(config, models, dbsession)

  # Update all endpoints to handle OPTIONS http_method requests
  for endpoint in pj.EndpointData.endpoints:
      pj.EndpointData.endpoints[endpoint]['http_methods']['OPTIONS'] = {'function': 'options_view',
                                                                        'renderer': 'string'}

  # Create the view_classes
  pj.create_jsonapi()

  # Bind the custom options method (defined above) to each view_class
  for vc in pj.view_classes.values():
          vc.options_view = options_view

.. _search_filter_operators:

Search (Filter) Operators
-------------------------

Search filters are on collection get operations are specified with URL paramaters of the form filter[attribute:op]=value. A number of search/filter operators are supported out of the box. The list currently includes the following for all column types:

* ``eq``
* ``ne``
* ``startswith``
* ``endswith``
* ``contains``
* ``lt``
* ``gt``
* ``le``
* ``ge``
* ``like`` or ``ilike``. Note that both of these use '*' in place of '%' to
  avoid much URL escaping.

plus these for JSONB columns:

* ``contains``
* ``contained_by``
* ``has_all``
* ``has_any``
* ``has_key``

You can add support for new filters using the :attr:`PyramidJSONAPI.filter_registry` (which is an instance of :py:class:`FilterRegistry`):

.. code-block:: python

  pj_api.filter_registry.register('my_comparator')

The above would register the sqlalchemy column comparator ``my_comparator`` (which should exist as a valid sqlalchemy comparator function) as valid for all column types and also create a URL filter op called ``my_comparator``. Any instances of ``__`` (double underscore) are stripped from the comparator name to create the filter name, so if we had called the comparator ``__my_comparator__`` it would still become the filter operator ``my_comparator``. For example, the sqlalachemy comparator ``__eq__`` is registered with:

.. code-block:: python

  pj_api.filter_registry.register('__eq__')

But has a filter name of ``eq``.

You can override the autogenerated name by providing one as an argument:

.. code-block:: python

  pj_api.filter_registry.register('my_comparator', filter_name='my_filter')

The comparator/filter combination is valid for all column types by default, which is the same as specifying:

.. code-block:: python

  pj_api.filter_registry.register('my_comparator', column_type='__ALL__')

Comparators can be registered as valid for individual column types by passing a column type:

.. code-block:: python

  from sqlalchemy.dialects.postgresql import JSONB
  pj_api.filter_registry.register('my_comparator', column_type=JSONB)

It's also possible to specify a value transformation function to change the paramter value before it is passed to the comparator. For example the ``like`` filter swaps all '*' characters for '%' before calling the associated ``like`` comparator. It is registered like this:

.. code-block:: python

  pj_api.filter_registry.register(
    'like',
    value_transform=lambda val: re.sub(r'\*', '%', val)
  )

Callbacks
---------

At certain points during the processing of a request, ``pyramid_jsonapi`` will
invoke any callback functions which have been registered. Callback sequences are
currently implemented as ``collections.deque``: you add your callback functions
using ``.append()`` or ``.appendleft()``, remove them with ``.pop()`` or
``.popleft()`` and so on. The functions in each callback list will be called in
order at the appropriate point.

Getting the Callback Deque
--------------------------

Every view class (subclass of CollectionViewBase) has its own dictionary of
callback deques (``view_class.callbacks``). That dictionary is keyed by callback
deque name. For example, if you have a view_class and you would like to append
your ``my_after_get`` function to the ``after_get`` deque:

.. code-block:: python

  view_class.callbacks['after_get'].append(my_after_get)

If you don't currently have a view class, you can get one from a model class
(for example, ``models.Person``) with:

.. code-block:: python

  person_view_class = pyramid_jsonapi.PyramidJSONAPI.view_classes[models.Person]

Available Callback Deques
-------------------------

The following is a list of available callbacks. Note that each item in the list
has a name like ``pyramid_jsonapi.callbacks_doc.<callback_name>``. That's so
that sphinx will link to auto-built documentation from the module
``pyramid_jsonapi.callbacks_doc``. In practice you should use only the name
after the last '.' to get callback deques.

* :func:`pyramid_jsonapi.callbacks_doc.after_serialise_object`

* :func:`pyramid_jsonapi.callbacks_doc.after_serialise_identifier`

* :func:`pyramid_jsonapi.callbacks_doc.after_get`

* :func:`pyramid_jsonapi.callbacks_doc.before_patch`

* :func:`pyramid_jsonapi.callbacks_doc.before_delete`

* :func:`pyramid_jsonapi.callbacks_doc.after_collection_get`

* :func:`pyramid_jsonapi.callbacks_doc.before_collection_post`

* :func:`pyramid_jsonapi.callbacks_doc.after_related_get`

* :func:`pyramid_jsonapi.callbacks_doc.after_relationships_get`

* :func:`pyramid_jsonapi.callbacks_doc.before_relationships_post`

* :func:`pyramid_jsonapi.callbacks_doc.before_relationships_patch`

* :func:`pyramid_jsonapi.callbacks_doc.before_relationships_delete`


Canned Callbacks
----------------

Using the callbacks above, you could, in theory, do things like implement a
permissions system, generalised call-outs to other data sources, or many other
things. However, some of those would entail quite a lot of work as well as being
potentially generally useful. In the interests of reuse, pyramid_jsonapi
maintains sets of self consistent callbacks which cooperate towards one goal.

So far there is only one such set: ``access_control_serialised_objects``. This
set of callbacks implements an access control system based on the inspection of
serialised (as dictionaries) objects before POST, PATCH and DELETE operations
and after serialisation and GET operations.

Registering Canned Callbacks
----------------------------

Given a callback set name, you can register callback sets on each view class:

.. code-block:: python

  view_class.append_callback_set('access_control_serialised_objects')

or on all view classes:

.. code-block:: python

  pyramid_jsonapi.PyramidJSONAPI.append_callback_set_to_all_views(
    'access_control_serialised_objects'
  )

Callback Sets
-------------

``access_control_serialised_objects``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These callbacks will allow, deny, or manipulate the results of actions
dependent upon the return values of two methods of the calling view class:
:func:`pyramid_jsonapi.CollectionViewBase.allowed_object` and
:func:`pyramid_jsonapi.CollectionViewBase.allowed_fields`.

The default implementations allow everything. To do anything else, you need to
replace those methods with your own implementations.

* :func:`pyramid_jsonapi.CollectionViewBase.allowed_object` will be given two
  arguments: an instance of a view class, and the serialised object (so far). It
  should return ``True`` if the operation (available from view.request) is
  allowed on the object, or ``False`` if not.

* :func:`pyramid_jsonapi.CollectionViewBase.allowed_fields` will be given one
  argument: an instance of a view class. It should return the set of fields
  (attributes and relationships) on which the current operation is allowed.
