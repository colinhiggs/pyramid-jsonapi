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
visible           Boolean       Whether or not to display this column in the API.
===============   ==========    ================================================

Model Relationship Options
--------------------------

The same ``info`` attribute used to specify column options above can be used to
specify relationship options. For example, to make a relationship called
``invisible_comments`` invisible to the API:

.. code-block:: python

  class Person(Base):
    __tablename__ = 'people'
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    invisible_comments = relationship('Comment')
    invisible_comments.info.update({'pyramid_jsonapi': {'visible': False}})

Available relationship options:

===============   ==========    ================================================
Option            Value Type    Description
===============   ==========    ================================================
visible           Boolean       Whether to display this relationship in the API.
===============   ==========    ================================================

Selectively Passing Models for API Generation
---------------------------------------------

Your database may have some tables which you do not wish to expose as collections in the generated API. You can be selective by:

* writing a models module with only the model classes you wish to expose; or
* passing an iterable of only the model classes you wish to expose to
  :func:`pyramid_jsonapi.PyramidJSONAPI`.

URL Paths
---------

There are a number of `prefix` configuration options that can be used to customise the URL path used in the generated API.
These are useful for mixing the API with other pages, adding API versioning etc.

The path is constructed as follows - omitting any variables which are unset.
The separator between fields is `route_pattern_sep` - shown here as the default '/'.
`type` is one of either `api` or `metadata`.

```
/route_pattern_prefix/api_version/route_pattern_<type>_prefix/endpoint
```

These options and their defaults are documented above in `Configuration Options`.


Modifying Endpoints
-------------------

Endpoints are created automatically from a dictionary: :data:`api_object.endpoint_data.endpoints`.

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

Stages and the Workflow
-----------------------

``pyramid_jsonapi`` services requests in stages. These stages are sequences of
functions implemented as a :class:`collections.deque` for each stage on each
method of each view class. For example, the deque for the ``alter_request``
stage of the ``collection_post()`` method for the view class associated with
``models.Person`` could be accessed with

.. code-block:: python

  ar_stage = pj.view_classes[models.Person].collection_post.stages['alter_request']

You can add your own functions
using ``.append()`` or ``.appendleft()``, remove them with ``.pop()`` or
``.popleft()`` and so on. The functions in each stage deque will be called in
order at the appropriate point and should have the following signature:

.. code-block:: python

  def handler_function(view_instance, argument, previous_data):
    # some function definition...
    return same_type_of_thing_as_argument

``argument`` in the ``alter_request`` stage would be a request, for example,
while in ``alter_document`` it would be a document object.

For example, let's say you would like to alter all posts to the people
collection so that a created_on_server attribute is populated automatically.

.. code-block:: python

  def created_on_server_handler(view, request, prev):
    request.json_data['data']

The stages are run in the following order:

* ``alter_request``. Functions in this stage alter the request. For example
  possibly editing any POST or PATCH such that it contains a server defined
  calculated attribute.
* ``validate_request``. Functions in this stage validate the request. For
  example, ensuring that the correct headers are set and that any json validates
  against the schema.
* Any stages defined by a ``workflow`` function from a loadable workflow module.
* ``alter_document``. Functions in this stage alter the ``document``, which is
  to say the dictionary which will be JSON serialised and sent back in the
  response.
* ``validate_response``.

The Loop Workflow
-----------------

The default workflow is the ``loop`` workflow. It defines the following stages:

* ``alter_query``. Alter the :class:`sqlalchemy.orm.query.Query` which will be
  executed (using ``.all()`` or ``.one()``) to fetch the primary result(s).
* ``alter_related_query``. Alter the :class:`sqlalchemy.orm.query.Query` which
  will be executed to fetch related result(s).
* ``alter_result``. Alter a :class:`workflow.ResultObject` object containing
  a database result (a sqlalchemy orm object) from a query of the requested
  collection. This might also involve rejecting the whole object (for example,
  for authorisation purposes).
* ``before_write_item``. Alter a sqlalchemy orm item before it is written
  (flushed) to the database.

Authorisation
-------------

There are stage functions available for stages which handle most of the logic of
authorisation. To use them, you must first load them into the appropriate stage
deque(s). :func:`pyramid_jsonapi.PyramidJSONAPI.enable_permission_handlers` will
do that.

These handlers call permission filters to determine whether or not an action is
permitted. The default permission filters allow everything, which is the same
as not having any permission handlers at all. Permission filters should be
registered with :func:`CollectionView.register_permission_filter`.

Note that you supply the lists of permissions and stages handled by the
permission filter function so you can either write functions that are quite
specific or more general ones. They will have the permission sought and the
current stage passed as arguments to aid in decision making.

Permission filters will be called from within the code like this:

.. code-block:: python

  your_filter(
    object_rep,
    view=view_instance,
    stage=stage_name,
    permission=permission_sought,
  )

Where ``object_rep`` is some representation of the object to be authorised,
``view_instance`` is the current view instance, ``stage_name`` is the name of
the current stage, and ``permission_sought`` is one of ``get``, ``post``,
``patch``, or ``delete``. Different stages imply different representations. For
example the ``alter_request`` stage will pass a dictionary representing an item
from ``data`` from the JSON contained in a pyramid request and the
``alter_document`` stage will pass a similar dictionary representation of an
object taken from the ``document`` to be serialised. The ``alter_result`` stage
from the loop workflow, on the other hand, will pass a
:class:`workflow.ResultObject`, which is a wrapper around a sqlAlchemy ORM
object (which you can get to as ``object_rep.object``).

Note that you can get the current sqlAlchemy session from
``view_instance.dbsession`` (which you might need to make the queries required
for authorisation) and the pyramid request from ``view_instance.request`` which
should give you access to the usual things.

The simplest thing that a permission filter can do is return ``True``
(``permission_sought`` is granted for the whole object) or ``False``
(``permission_sought`` is denied for the whole object). To control permissions
for attributes or relationships, you must use the fuller return representation:

.. code-block:: python

  {
    'id': True|False, # Controls visibility of / action on the whole object.
    'attributes': {'att1', 'att2', ...}, # The set of allowed attribute names.
    'relationships': {'rel1', 'rel2', ...}, # The set of allowed rel names.
  }

Putting that together in some examples:

Let's say you have banned the user 'baddy' and want to authorise GET requests so
that baddy can no longer fetch blogs. Both the ``alter_document`` and
``alter_result`` stages would make sense as places to influence what will
be returned by a GET. We will choose ``alter_result`` here so that we are
authorising results as soon as
they come from the database. You might have something like this in
``__init__.py``:

.. code-block:: python

  pj = pyramid_jsonapi.PyramidJSONAPI(config, models)
  pj.enable_permission_handlers(
    ['get'],
    ['alter_result']
  )
  pj.view_classes[models.Blogs].register_permission_filter(
    ['get'],
    ['alter_result'],
    lambda obj, view, **kwargs:  view.request.remote_user != 'baddy',
  )

Next, you want to do authorisation on PATCH requests and allow only the author
of a blog post to PATCH it. The ``alter_request`` stage is the most obvious
place to do this (you want to alter the request before it is turned into a
database update). You might do something like this in ``__init__.py``:

.. code-block:: python

  pj = pyramid_jsonapi.PyramidJSONAPI(config, models)
  pj.enable_permission_handlers(['PATCH'], ['alter_request'])
  def patch_posts_filter(data, view, **kwargs):
    post_obj = view.db_session.get(models.Posts, data['id']) # sqlalchemy 1.4+
    # post_obj = view.db_session.query(models.Posts).get(data['id']) # sqlalchemy < 1.4
    return view.request.remote_user == post_obj.author.name
  pj.view_classes[models.Posts].register_permission_filter(
    ['patch'],
    ['alter_request'],
    patch_posts_filter
  )

Imagine that ``Person`` objects have an ``age`` attribute. Access to ``age`` is
sensitive so only the person themselves and anyone in the (externally defined)
``age_viewers`` group should be able to see that attribute. Other viewers should
still be able to see the object so we can't just return ``False`` from the
permission filter - we must use the fuller return format.

.. code-block:: python

  pj = pyramid_jsonapi.PyramidJSONAPI(config, models)
  pj.enable_permission_handlers(
    ['get'],
    ['alter_result']
  )

  def get_person_filter(person, view, **kwargs):
    # This could be done in one 'if' but we split it out here for clarity.
    #
    # A person should see the full object for themselves.
    if view.request.remote_user == person.username:
      return True
    #
    # Anyone in the age_viewers group should also see the full object.
    # get_group_members() is an imagined function in this app which gets the
    # members of a named group.
    if view.request.remote_user in get_group_members('age_viewers'):
      return True

    # Everyone else isn't allowed to see age.
    return {
      'id': True, # False would reject the whole object. Missing out the 'id'
                  # key is the same as specifying True.
      'attributes': set(view.all_attributes) - 'age',
      'relationships': True # The same as allowing all attributes.
    }

  pj.view_classes[models.Person].register_permission_filter(
    ['get'],
    ['alter_result'],
    get_person_filter
  )

What Happens With Authorisation Failures
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Authorisation and Relationships
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Authorisation can get quite complicated around relationships. Every operation on
an object with relationships implies other operations on any related objects.
The simplest example is ``GET``: ``get`` permission is required on any object
directly fetched and *also* on any related object fetched. More complicated is
any write based operation. For example, to update the owner of a blog, you need
``patch`` permission on ``blog_x.owner``, ``post`` permission on
``new_owner.blogs`` (to add ``blog_x`` to the reverse relationship) and
``delete`` permission on ``old_owner.blogs`` (to remove ``blog_x`` from the
reverse relationship).
