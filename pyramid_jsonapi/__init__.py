"""Tools for constructing a JSON-API from sqlalchemy models in Pyramid."""

# pylint:disable=line-too-long

import copy
import functools
import importlib
import itertools
import logging
import re
import types
from collections import deque, Sequence, Mapping

import jsonschema
from pyramid.view import (
    view_config,
    notfound_view_config,
    forbidden_view_config
)
from pyramid.httpexceptions import (
    exception_response,
    HTTPException,
    HTTPNotFound,
    HTTPForbidden,
    HTTPUnauthorized,
    HTTPClientError,
    HTTPBadRequest,
    HTTPConflict,
    HTTPUnsupportedMediaType,
    HTTPNotAcceptable,
    HTTPNotImplemented,
    HTTPError,
    HTTPFailedDependency,
    HTTPInternalServerError,
    status_map,
)
import sqlalchemy
from sqlalchemy.orm import load_only
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.ext.declarative.api import DeclarativeMeta
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.dialects.postgresql import JSONB

import pyramid_jsonapi.endpoints
import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.metadata
import pyramid_jsonapi.settings
import pyramid_jsonapi.version

__version__ = pyramid_jsonapi.version.get_version()

ONETOMANY = sqlalchemy.orm.interfaces.ONETOMANY
MANYTOMANY = sqlalchemy.orm.interfaces.MANYTOMANY
MANYTOONE = sqlalchemy.orm.interfaces.MANYTOONE


class PyramidJSONAPI():
    """Class encapsulating an API.

    Arguments:
        config (pyramid.config.Configurator): pyramid config object from app.
        models (module or iterable): a models module or iterable of models.

    Keyword Args:
        get_dbsession (callable): function accepting an instance of
            CollectionViewBase and returning a sqlalchemy database session.
    """

    view_classes = {}

    def __init__(self, config, models, get_dbsession=None):
        self.config = config
        self.settings = pyramid_jsonapi.settings.Settings(config.registry.settings)
        self.models = models
        self.get_dbsession = get_dbsession
        self.endpoint_data = pyramid_jsonapi.endpoints.EndpointData(self)
        self.filter_registry = FilterRegistry()
        self.metadata = pyramid_jsonapi.metadata.MetaData(self)
        self.schemas = None
        # Register standard supported filter operators
        for comparator_name in (
                '__eq__',
                '__ne__',
                'startswith',
                'endswith',
                'contains',
                '__lt__',
                '__gt__',
                '__le__',
                '__ge__'
        ):
            self.filter_registry.register(comparator_name)
        # Transform '%' to '*' for like and ilike
        for comparator_name in (
                'like',
                'ilike'
        ):
            self.filter_registry.register(
                comparator_name,
                value_transform=lambda val: re.sub(r'\*', '%', val)
            )
        # JSONB specific operators
        for comparator_name in (
                'contains',
                'contained_by',
                'has_all',
                'has_any',
                'has_key'
        ):
            self.filter_registry.register(
                comparator_name,
                column_type=JSONB
            )

        # Add schema if pyramid_jsonapi.schema_validation is not 'false'
        if self.settings.schema_validation:
            schema = self.metadata.JSONSchema.template()
            # POST uses full schema, may omit 'id'
            post_schema = copy.deepcopy(schema)
            post_schema['definitions']['resource']['required'].remove('id')
            self.schemas = {
                'full': schema,
                'post': post_schema
            }

    @staticmethod
    def error(exc, request):
        """Error method to return jsonapi compliant errors."""
        request.response.content_type = 'application/vnd.api+json'
        request.response.status_code = exc.code
        return {
            'errors': [
                {
                    'code': str(exc.code),
                    'detail': exc.detail,
                    'title': exc.title,
                }
            ]
        }

    def create_jsonapi(self, engine=None, test_data=None):
        """Auto-create jsonapi from module or iterable of sqlAlchemy models.

        Keyword Args:
            engine: a sqlalchemy.engine.Engine instance. Only required if using the
                debug view.
            test_data: a module with an ``add_to_db()`` method which will populate
                the database.
        """

        self.config.add_notfound_view(self.error, renderer='json')
        self.config.add_forbidden_view(self.error, renderer='json')
        self.config.add_view(self.error, context=HTTPError, renderer='json')

        # Build a list of declarative models to add as collections.
        if isinstance(self.models, types.ModuleType):
            model_list = []
            for attr in self.models.__dict__.values():
                if isinstance(attr, DeclarativeMeta):
                    try:
                        sqlalchemy.inspect(attr).primary_key
                    except sqlalchemy.exc.NoInspectionAvailable:
                        # Trying to inspect the declarative_base() raises this
                        # exception. We don't want to add it to the API.
                        continue
                    model_list.append(attr)
        else:
            model_list = list(self.models)

        # Add the debug endpoints if required.
        if self.settings.debug_endpoints:
            DebugView.engine = engine or model_list[0].metadata.bind
            DebugView.metadata = model_list[0].metadata
            DebugView.test_data = test_data or importlib.import_module(
                str(self.settings.debug_test_data_module)
            )
            self.config.add_route('debug', '/debug/{action}')
            self.config.add_view(
                DebugView,
                attr='drop',
                route_name='debug',
                match_param='action=drop',
                renderer='json'
            )
            self.config.add_view(
                DebugView,
                attr='populate',
                route_name='debug',
                match_param='action=populate',
                renderer='json'
            )
            self.config.add_view(
                DebugView,
                attr='reset',
                route_name='debug',
                match_param='action=reset',
                renderer='json'
            )

        # Loop through the models list. Create resource endpoints for these and
        # any relationships found.
        for model_class in model_list:
            self.create_resource(model_class)

    create_jsonapi_using_magic_and_pixie_dust = create_jsonapi  # pylint:disable=invalid-name

    def create_resource(self, model, collection_name=None, expose_fields=None):
        """Produce a set of resource endpoints.

        Arguments:
            model: a model class derived from DeclarativeMeta.

        Keyword Args:
            collection_name: string name of collection. Passed through to
                ``collection_view_factory()``
            expose_fields: set of field names to be exposed. Passed through to
                ``collection_view_factory()``
        """

        # Find the primary key column from the model and use as 'id_col_name'
        try:
            keycols = sqlalchemy.inspect(model).primary_key
        except sqlalchemy.exc.NoInspectionAvailable:
            # Trying to inspect the declarative_base() raises this exception. We
            # don't want to add it to the API.
            return
        # Only deal with one primary key column.
        if len(keycols) > 1:
            raise Exception(
                'Model {} has more than one primary key.'.format(
                    model.__name__
                )
            )

        if not hasattr(model, '__pyramid_jsonapi__'):
            model.__pyramid_jsonapi__ = {}
        if 'id_col_name' not in model.__pyramid_jsonapi__:
            model.__pyramid_jsonapi__['id_col_name'] = keycols[0].name

        # Create a view class for use in the various add_view() calls below.
        view = self.collection_view_factory(model,
                                            collection_name or
                                            getattr(
                                                model, '__pyramid_jsonapi__', {}
                                            ).get('collection_name') or
                                            sqlalchemy.inspect(model).tables[-1].name,
                                            expose_fields=expose_fields)

        self.view_classes[model] = view

        view.default_limit = int(self.settings.paging_default_limit)
        view.max_limit = int(self.settings.paging_max_limit)

        self.endpoint_data.add_routes_views(view)

    def collection_view_factory(self, model, collection_name=None, expose_fields=None):
        """Build a class to handle requests for model.

        Arguments:
            model: a model class derived from DeclarativeMeta.

        Keyword Args:
            collection_name: string name of collection.
            expose_fields: set of field names to expose.
        """

        class_attrs = {}
        class_attrs['api'] = self
        class_attrs['model'] = model
        class_attrs['key_column'] = sqlalchemy.inspect(model).primary_key[0]
        class_attrs['collection_name'] = collection_name or model.__tablename__
        class_attrs['exposed_fields'] = expose_fields
        # atts is ordinary attributes of the model.
        # hybrid_atts is any hybrid attributes defined.
        # fields is atts + hybrid_atts + relationships
        atts = {}
        hybrid_atts = {}
        fields = {}
        for key, col in sqlalchemy.inspect(model).mapper.columns.items():
            if key == class_attrs['key_column'].name or col.foreign_keys:
                continue
            if expose_fields is None or key in expose_fields:
                atts[key] = col
                fields[key] = col
        class_attrs['attributes'] = atts
        for item in sqlalchemy.inspect(model).all_orm_descriptors:
            if isinstance(item, hybrid_property):
                if expose_fields is None or item.__name__ in expose_fields:
                    hybrid_atts[item.__name__] = item
                    fields[item.__name__] = item
        class_attrs['hybrid_attributes'] = hybrid_atts
        rels = {}
        for key, rel in sqlalchemy.inspect(model).mapper.relationships.items():
            if expose_fields is None or key in expose_fields:
                rels[key] = rel
        class_attrs['relationships'] = rels
        fields.update(rels)
        class_attrs['fields'] = fields

        # All callbacks have the current view as the first argument. The comments
        # below detail subsequent args.
        class_attrs['callbacks'] = {
            'after_serialise_identifier': deque(),  # args: identifier(dict)
            'after_serialise_object': deque(),      # args: object(dict)
            'after_get': deque(),                   # args: document(dict)
            'before_patch': deque(),                # args: partial_object(dict)
            'before_delete': deque(),               # args: item(sqlalchemy)
            'after_collection_get': deque(),        # args: document(dict)
            'before_collection_post': deque(),      # args: object(dict)
            'after_related_get': deque(),           # args: document(dict)
            'after_relationships_get': deque(),     # args: document(dict)
            'before_relationships_post': deque(),   # args: object(dict)
            'before_relationships_patch': deque(),  # args: partial_object(dict)
            'before_relationships_delete':
                deque(),                            # args: parent_item(sqlalchemy)
        }

        return type(
            'CollectionView<{}>'.format(collection_name),
            (CollectionViewBase, ),
            class_attrs
        )

    def append_callback_set_to_all_views(self, set_name):  # pylint:disable=invalid-name
        """Append a named set of callbacks to all view classes.

        Args:
            set_name (str): key in ``callback_sets``.
        """
        for view_class in self.view_classes.values():
            view_class.append_callback_set(set_name)


class CollectionViewBase:
    """Base class for all view classes.

    Arguments:
        request (pyramid.request): passed by framework.
    """

    # Define class attributes
    # Callable attributes use lambda to keep pylint happy
    api = None
    attributes = None
    callbacks = None
    collection_name = None
    default_limit = None
    exposed_fields = None
    fields = None
    dbsession = None
    hybrid_attributes = None
    key_column = None
    max_limit = None
    model = lambda: None
    request = None
    relationships = None
    view_classes = None
    schemas = None
    settings = None

    def __init__(self, request):
        self.request = request
        if self.api.get_dbsession:
            self.dbsession = self.api.get_dbsession(self)
        else:
            self.dbsession = self.request.dbsession
        self.views = {}

    @staticmethod
    def id_col(item):
        """Return the column holding an item's id."""
        return getattr(item, item.__pyramid_jsonapi__['id_col_name'])

    def jsonapi_view(func):  # pylint: disable=no-self-argument
        """Decorator for view functions. Adds jsonapi boilerplate,
        and tests response validity."""

        def view_exceptions(func):
            """Decorator to intercept all exceptions raised by wrapped view methods.

            If the exception is 'valid' according to the schema, raise it.
            Else raise a generic 4xx or 5xx error and log the real one.
            """
            @functools.wraps(func)
            def new_func(self, *args):  # pylint: disable=missing-docstring
                ep_dict = self.api.endpoint_data.endpoints
                # Get route_name from route
                _, _, endpoint = self.request.matched_route.name.split(':')
                method = self.request.method
                responses = set(
                    ep_dict['responses'].keys() |
                    ep_dict['endpoints'][endpoint]['responses'].keys() |
                    ep_dict['endpoints'][endpoint]['http_methods'][method]['responses'].keys()
                )
                try:
                    result = func(self, *args)  # pylint: disable=not-callable
                    response_class = status_map[self.request.response.status_code]
                    if response_class not in responses:
                        logging.error(
                            "Invalid response: %s for route_name: %s path: %s",
                            response_class,
                            self.request.matched_route.name,
                            self.request.current_route_path()
                        )
                    return result
                except Exception as exc:
                    if exc.__class__ not in responses:
                        logging.exception(
                            "Invalid exception raised: %s for route_name: %s path: %s",
                            exc.__class__,
                            self.request.matched_route.name,
                            self.request.current_route_path()
                        )
                        if hasattr(exc, 'code'):
                            if 400 <= exc.code < 500:  # pylint:disable=no-member
                                raise HTTPBadRequest("Unexpected client error: {}".format(exc))
                        else:
                            raise HTTPInternalServerError("Unexpected server error.")
                    raise
            return new_func

        @functools.lru_cache()
        def get_jsonapi_accepts(request):
            """Return a set of all 'application/vnd.api' parts of the accept
            header.
            """
            accepts = re.split(
                r',\s*',
                request.headers.get('accept', '')
            )
            return {
                a for a in accepts
                if a.startswith('application/vnd.api')
            }

        def check_request_headers(request, jsonapi_accepts):
            """Check that request headers comply with spec.

            Raises:
                HTTPUnsupportedMediaType
                HTTPNotAcceptable
            """
            # Spec says to reject (with 415) any request with media type
            # params.
            if len(request.headers.get('content-type', '').split(';')) > 1:
                raise HTTPUnsupportedMediaType(
                    'Media Type parameters not allowed by JSONAPI ' +
                    'spec (http://jsonapi.org/format).'
                )
            # Spec says throw 406 Not Acceptable if Accept header has no
            # application/vnd.api+json entry without parameters.
            if jsonapi_accepts and\
                    'application/vnd.api+json' not in jsonapi_accepts:
                raise HTTPNotAcceptable(
                    'application/vnd.api+json must appear with no ' +
                    'parameters in Accepts header ' +
                    '(http://jsonapi.org/format).'
                )

        def check_request_valid_json(request):
            """Check that the body of any request is valid JSON.

            Raises:
                HTTPBadRequest
            """
            if request.content_length:
                try:
                    request.json_body
                except ValueError:
                    raise HTTPBadRequest("Body is not valid JSON.")

        def check_request_against_schema(request, schema):
            """Check that request validates against appropriate schema.

            Raises:
                HTTPBadRequest
            """
            if request.content_length and request.method != 'PATCH':
                try:
                    jsonschema.validate(request.json_body, schema)
                except jsonschema.exceptions.ValidationError as exc:
                    raise HTTPBadRequest(exc.message)

        @view_exceptions
        @functools.wraps(func)
        def view_wrapper(self, *args):
            """jsonapi boilerplate function to wrap decorated functions."""
            check_request_headers(self.request, get_jsonapi_accepts(self.request))
            check_request_valid_json(self.request)
            if self.api.schemas:
                # Validate request JSON against the JSONAPI jsonschema
                check_request_against_schema(self.request, self.api.schemas['post'])

            # Spec says throw BadRequest if any include paths reference non
            # existent attributes or relationships.
            if self.bad_include_paths:
                raise HTTPBadRequest(
                    "Bad include paths {}".format(
                        self.bad_include_paths
                    )
                )

            # Spec says set Content-Type to application/vnd.api+json.
            self.request.response.content_type = 'application/vnd.api+json'

            # Update the dictionary with the reults of the wrapped method.
            ret = (func(self, *args))  # pylint:disable=not-callable
            if ret:
                # Include a self link unless the method is PATCH.
                if self.request.method != 'PATCH':
                    selfie = {'self': self.request.url}
                    if hasattr(ret, 'links'):
                        ret.links.update(selfie)
                    else:
                        ret.links = selfie

                # Potentially add some debug information.
                if self.api.settings.debug_meta:
                    debug = {
                        'accept_header': {
                            a: None for a in get_jsonapi_accepts(self.request)
                        },
                        'qinfo_page':
                            self.collection_query_info(self.request)['_page'],
                        'atts': {k: None for k in self.attributes.keys()},
                        'includes': {
                            k: None for k in self.requested_include_names()
                        }
                    }
                    ret.meta.update({'debug': debug})
                return ret.as_dict()
            else:
                return {}
        return view_wrapper

    @jsonapi_view
    def get(self):
        """Handle GET request for a single item.

        Get a single item from the collection, referenced by id.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound

        Example:

            Get person 1:

            .. parsed-literal::

                http GET http://localhost:6543/people/1
        """
        try:
            ret = self.single_return(
                self.single_item_query,
                'No id {} in collection {}'.format(
                    self.request.matchdict['id'],
                    self.collection_name
                )
            )
        except (sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            # DataError is caused by e.g. id (int) = cat
            # StatementError is caused by e.g. id (uuid) = 1
            raise HTTPNotFound(
                'Cannot find resource ({}/{})'.format(
                    self.collection_name, self.request.matchdict['id']
                )
            )

        for callback in self.callbacks['after_get']:
            ret = callback(self, ret)
        return ret

    def patch_check_request(self):
        """Perform initial checks on a PATCH request."""
        if not self.object_exists(self.request.matchdict['id']):
            raise HTTPNotFound(
                'Cannot PATCH a non existent resource ({}/{})'.format(
                    self.collection_name, self.request.matchdict['id']
                )
            )

        try:
            data = self.request.json_body['data']
        except KeyError:
            raise HTTPBadRequest('data attribute required in PATCHes.')

        if self.collection_name != data.get('type'):
            raise HTTPConflict(
                'JSON type ({}) does not match URL type ({}).'.format(
                    data.get('type'), self.collection_name
                )
            )

        req_id = self.request.matchdict['id']
        data_id = data.get('id')
        if data_id != req_id:
            raise HTTPConflict(
                'JSON id ({}) does not match URL id ({}).'.format(
                    data_id, req_id
                )
            )

    def patch_gen_attributes(self, data):
        """Return ({dict of attribute name/val}, {dict of hybrid att name/val})."""
        atts = {}
        hybrid_atts = {}
        for key, value in data.get('attributes', {}).items():
            if key in self.attributes:
                atts[key] = value
            elif key in self.hybrid_attributes:
                hybrid_atts[key] = value
            else:
                raise HTTPNotFound(
                    'Collection {} has no attribute {}'.format(
                        self.collection_name, key
                    )
                )
        atts[self.key_column.name] = data['id']
        return (atts, hybrid_atts)

    def patch_update_item(self, atts, hybrid_atts):
        """Update database item with information in atts and hybrid_atts."""
        item = self.dbsession.merge(self.model(**atts))
        for att, value in hybrid_atts.items():
            try:
                setattr(item, att, value)
            except AttributeError:
                raise HTTPConflict(
                    'Attribute {} is read only.'.format(
                        att
                    )
                )
        return item

    def patch_update_relationships(self, item, rels):
        """Update database with any relationship changes."""
        data = self.request.json_body['data']
        for relname, reldict in rels.items():
            if relname not in self.relationships:
                raise HTTPNotFound(
                    'Collection {} has no relationship {}'.format(
                        self.collection_name, relname
                    )
                )
            rel = self.relationships[relname]
            rel_class = rel.mapper.class_
            rel_view = self.view_instance(rel_class)
            try:
                data = reldict['data']
            except KeyError:
                raise HTTPBadRequest(
                    "Relationship '{}' has no 'data' member.".format(relname)
                )
            except TypeError:
                raise HTTPBadRequest(
                    "Relationship '{}' is not a dictionary with a data member.".format(relname)
                )
            if data is None:
                setattr(item, relname, None)
            elif isinstance(data, dict):
                if data.get('type') != rel_view.collection_name:
                    raise HTTPConflict(
                        'Type {} does not match relationship type {}'.format(
                            data.get('type', None), rel_view.collection_name
                        )
                    )
                if data.get('id') is None:
                    raise HTTPBadRequest(
                        'An id is required in a resource identifier.'
                    )
                rel_item = self.dbsession.query(
                    rel_class
                ).options(
                    load_only(rel_view.key_column.name)
                ).get(data['id'])
                if not rel_item:
                    raise HTTPNotFound('{}/{} not found'.format(
                        rel_view.collection_name, data['id']
                    ))
                setattr(item, relname, rel_item)
            elif isinstance(data, list):
                rel_items = []
                for res_ident in data:
                    rel_item = self.dbsession.query(
                        rel_class
                    ).options(
                        load_only(rel_view.key_column.name)
                    ).get(res_ident['id'])
                    if not rel_item:
                        raise HTTPNotFound('{}/{} not found'.format(
                            rel_view.collection_name, res_ident['id']
                        ))
                    rel_items.append(rel_item)
                setattr(item, relname, rel_items)

    def patch_construct_document(self, atts, hybrid_atts, rels):
        """Construct JSON response document for PATCH request."""
        doc = pyramid_jsonapi.jsonapi.Document()
        doc.meta = {
            'updated': {
                'attributes': [
                    att for att in itertools.chain(atts, hybrid_atts)
                    if att != self.key_column.name
                ],
                'relationships': [r for r in rels]
            }
        }
        # if an update is successful ... the server
        # responds only with top-level meta data
        doc.filter_keys = {'meta': {}}
        return doc

    @jsonapi_view
    def patch(self):
        """Handle PATCH request for a single item.

        Update an existing item from a partially defined representation.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        **Request Body**

            **Partial resource object** (*json*)

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    'meta': {
                        'updated': [
                            <attribute_name>,
                            <attribute_name>
                        ]
                    }
                }

        Raises:
            HTTPNotFound

        Todo:
            Currently does not deal with relationships.

        Example:
            PATCH person 1, changing name to alicia:

            .. parsed-literal::

                http PATCH http://localhost:6543/people/1 data:='
                {
                    "type":"people", "id": "1",
                    "attributes": {
                        "name": "alicia"
                    }
                }' Content-Type:application/vnd.api+json

            Change the author of posts/1 to people/2:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1 data:='
                {
                    "type":"posts", "id": "1",
                    "relationships": {
                        "author": {"type": "people", "id": "2"}
                    }
                }' Content-Type:application/vnd.api+json

            Set the comments on posts/1 to be [comments/4, comments/5]:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1 data:='
                {
                    "type":"posts", "id": "1",
                    "relationships": {
                        "comments": [
                            {"type": "comments", "id": "4"},
                            {"type": "comments", "id": "5"}
                        ]
                    }
                }' Content-Type:application/vnd.api+json
        """
        self.patch_check_request()

        data = self.request.json_body['data']
        for callback in self.callbacks['before_patch']:
            data = callback(self, data)

        atts, hybrid_atts = self.patch_gen_attributes(data)
        item = self.patch_update_item(atts, hybrid_atts)
        rels = data.get('relationships', {})
        self.patch_update_relationships(item, rels)
        self.dbsession.flush()

        return self.patch_construct_document(atts, hybrid_atts, rels)

    @jsonapi_view
    def delete(self):
        """Handle DELETE request for single item.

        Delete the referenced item from the collection.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            jsonapi.Document: Resource Identifier for deleted object.

        Raises:
            HTTPFailedDependency: if a database constraint would be broken by
            deleting the specified resource from the relationship.

        Example:
            delete person 1:

            .. parsed-literal::

                http DELETE http://localhost:6543/people/1
        """

        doc = pyramid_jsonapi.jsonapi.Document()
        try:
            item = self.dbsession.query(
                self.model
            ).options(
                load_only(self.key_column.name)
            ).get(
                self.request.matchdict['id']
            )
        except (sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            raise HTTPNotFound(
                'Cannot DELETE a non existent resource ({}/{})'.format(
                    self.collection_name, self.request.matchdict['id']
                )
            )

        if item:
            for callback in self.callbacks['before_delete']:
                callback(self, item)
            try:
                self.dbsession.delete(item)
                self.dbsession.flush()
            except sqlalchemy.exc.IntegrityError as exc:
                raise HTTPFailedDependency(str(exc))
            doc.update({
                'data': self.serialise_resource_identifier(
                    self.request.matchdict['id']
                )})
            return doc

        else:
            raise HTTPNotFound(
                'Cannot DELETE a non existent resource ({}/{})'.format(
                    self.collection_name, self.request.matchdict['id']
                )
            )

    @jsonapi_view
    def collection_get(self):
        """Handle GET requests for the collection.

        Get a set of items from the collection, possibly matching search/filter
        parameters. Optionally sort the results, page them, return only certain
        fields, and include related resources.

        **Query Parameters**

            **include:** comma separated list of related resources to include
            in the include section.

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

            **sort:** comma separated list of sort keys.

            **page[limit]:** number of results to return per page.

            **page[offset]:** starting index for current page.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": [ list of resource objects ],
                    "links": { links object },
                    "include": [ optional list of included resource objects ],
                    "meta": { implementation specific information }
                }

        Raises:
            HTTPBadRequest

        Examples:
            Get up to default page limit people resources:

            .. parsed-literal::

                http GET http://localhost:6543/people

            Get the second page of two people, reverse sorted by name and
            include the related posts as included documents:

            .. parsed-literal::

                http GET http://localhost:6543/people?page[limit]=2&page[offset]=2&sort=-name&include=posts
        """
        # Set up the query
        query = self.dbsession.query(
            self.model
        ).options(
            load_only(*self.allowed_requested_query_columns.keys())
        )
        query = self.query_add_sorting(query)
        query = self.query_add_filtering(query)
        qinfo = self.collection_query_info(self.request)
        try:
            count = query.count()
        except sqlalchemy.exc.ProgrammingError:
            raise HTTPInternalServerError(
                'An error occurred querying the database. Server logs may have details.'
            )
        query = query.offset(qinfo['page[offset]'])
        query = query.limit(qinfo['page[limit]'])

        ret = self.collection_return(query, count=count)

        # Alter return dict with any callbacks.
        for callback in self.callbacks['after_collection_get']:
            ret = callback(self, ret)
        return ret

    @jsonapi_view
    def collection_post(self):
        """Handle POST requests for the collection.

        Create a new object in collection.

        **Request Body**

            **resource object** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": { resource object }
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPForbidden: if an id is presented in "data" and client ids are
            not supported.

            HTTPConflict: if type is not present or is different from the
            collection name.

            HTTPNotFound: if a non existent relationship is referenced in the
            supplied resource object.

            HTTPConflict: if creating the object would break a database
            constraint (most commonly if an id is supplied by the client and
            an item with that id already exists).

            HTTPBadRequest: if the request is malformed in some other way.

        Examples:
            Create a new person with name 'monty' and let the server pick the
            id:

            .. parsed-literal::

                http POST http://localhost:6543/people data:='
                {
                    "type":"people",
                    "attributes": {
                        "name": "monty"
                    }
                }' Content-Type:application/vnd.api+json
        """
        try:
            data = self.request.json_body['data']
        except KeyError:
            raise HTTPBadRequest('data attribute required in POSTs.')

        if not isinstance(data, dict):
            raise HTTPBadRequest('data attribute must contain a single resource object.')

        # Alter data with any callbacks.
        for callback in self.callbacks['before_collection_post']:
            data = callback(self, data)

        # Check to see if we're allowing client ids
        if not self.api.settings.allow_client_ids and 'id' in data:
            raise HTTPForbidden('Client generated ids are not supported.')
        # Type should be correct or raise 409 Conflict
        datatype = data.get('type')
        if datatype != self.collection_name:
            raise HTTPConflict("Unsupported type '{}'".format(datatype))
        try:
            atts = data['attributes']
        except KeyError:
            atts = {}
        if 'id' in data:
            atts[self.model.__pyramid_jsonapi__['id_col_name']] = data['id']
        item = self.model(**atts)
        mapper = sqlalchemy.inspect(self.model).mapper
        with self.dbsession.no_autoflush:
            for relname, reldict in data.get('relationships', {}).items():
                try:
                    reldata = reldict['data']
                except KeyError:
                    raise HTTPBadRequest(
                        'relationships within POST must have data member'
                    )
                try:
                    rel = mapper.relationships[relname]
                except KeyError:
                    raise HTTPNotFound(
                        'No relationship {} in collection {}'.format(
                            relname,
                            self.collection_name
                        )
                    )
                rel_class = rel.mapper.class_
                rel_type = self.api.view_classes[rel_class].collection_name
                if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
                    # reldata should be a list/array
                    if not isinstance(reldata, Sequence) or isinstance(reldata, str):
                        raise HTTPBadRequest(
                            'Relationship data should be an array for TOMANY relationships.'
                        )
                    rel_items = []
                    for rel_identifier in reldata:
                        if rel_identifier.get('type') != rel_type:
                            raise HTTPConflict(
                                'Relationship identifier has type {} and should be {}'.format(
                                    rel_identifier.get('type'), rel_type
                                )
                            )
                        try:
                            rid_id = rel_identifier['id']
                        except KeyError:
                            raise HTTPBadRequest(
                                'Relationship identifier must have an id member'
                            )
                        rel_items.append(self.dbsession.query(rel_class).get(rid_id))
                    setattr(item, relname, rel_items)
                else:
                    try:
                        related_id = reldata['id']
                    except Exception:
                        raise HTTPBadRequest(
                            'No id member in relationship data.'
                        )
                    setattr(
                        item,
                        relname,
                        self.dbsession.query(rel_class).get(related_id)
                    )
        try:
            self.dbsession.add(item)
            self.dbsession.flush()
        except sqlalchemy.exc.IntegrityError as exc:
            raise HTTPConflict(exc.args[0])
        self.request.response.status_code = 201
        self.request.response.headers['Location'] = self.request.route_url(
            self.api.endpoint_data.make_route_name(self.collection_name, suffix='item'),
            **{'id': self.id_col(item)}
        )
        doc = pyramid_jsonapi.jsonapi.Document()
        doc.update({'data': self.serialise_db_item(item, {})})
        return doc

    @jsonapi_view
    def related_get(self):
        """Handle GET requests for related URLs.

        Get object(s) related to a specified object.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            For a TOONE relationship (return one object):

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

            For a TOMANY relationship (return multiple objects):

            .. parsed-literal::

                {
                    "data": [ { resource object }, ... ]
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if `relname` is not found as a relationship.

            HTTPBadRequest: if a bad filter is used.

        Examples:
            Get the author of post 1:

            .. parsed-literal::

                http GET http://localhost:6543/posts/1/author
        """
        obj_id = self.request.matchdict['id']
        relname = self.request.matchdict['relationship']
        mapper = sqlalchemy.inspect(self.model).mapper
        try:
            rel = mapper.relationships[relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                relname,
                self.collection_name
            ))
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)

        # Check that the original resource exists.
        if not self.object_exists(obj_id):
            raise HTTPNotFound('Object {} not found in collection {}'.format(
                obj_id,
                self.collection_name
            ))

        # Set up the query
        query = self.related_query(obj_id, rel)

        if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
            query = rel_view.query_add_sorting(query)
            query = rel_view.query_add_filtering(query)
            qinfo = rel_view.collection_query_info(self.request)
            try:
                count = query.count()
            except sqlalchemy.exc.ProgrammingError:
                raise HTTPInternalServerError(
                    'An error occurred querying the database. Server logs may have details.'
                )
            query = query.offset(qinfo['page[offset]'])
            query = query.limit(qinfo['page[limit]'])
            ret = rel_view.collection_return(query, count=count)
        else:
            ret = rel_view.single_return(query)

        # Alter return dict with any callbacks.
        for callback in self.callbacks['after_related_get']:
            ret = callback(self, ret)
        return ret

    @jsonapi_view
    def relationships_get(self):
        """Handle GET requests for relationships URLs.

        Get object identifiers for items referred to by a relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            For a TOONE relationship (return one identifier):

            .. parsed-literal::

                {
                    "data": { resource identifier },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

            For a TOMANY relationship (return multiple identifiers):

            .. parsed-literal::

                {
                    "data": [ { resource identifier }, ... ]
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPBadRequest: if a bad filter is used.

        Examples:
            Get an identifer for the author of post 1:

            .. parsed-literal::

                http GET http://localhost:6543/posts/1/relationships/author
        """
        obj_id = self.request.matchdict['id']
        relname = self.request.matchdict['relationship']
        mapper = sqlalchemy.inspect(self.model).mapper
        try:
            rel = mapper.relationships[relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                relname,
                self.collection_name
            ))
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)

        # Check that the original resource exists.
        if not self.object_exists(obj_id):
            raise HTTPNotFound('Object {} not found in collection {}'.format(
                obj_id,
                self.collection_name
            ))

        # Set up the query
        query = self.related_query(obj_id, rel, full_object=False)

        if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
            query = rel_view.query_add_sorting(query)
            query = rel_view.query_add_filtering(query)
            qinfo = rel_view.collection_query_info(self.request)
            try:
                count = query.count()
            except sqlalchemy.exc.ProgrammingError:
                raise HTTPInternalServerError(
                    'An error occurred querying the database. Server logs may have details.'
                )
            query = query.offset(qinfo['page[offset]'])
            query = query.limit(qinfo['page[limit]'])
            ret = rel_view.collection_return(
                query,
                count=count,
                identifiers=True
            )
        else:
            ret = rel_view.single_return(query, identifier=True)

        # Alter return dict with any callbacks.
        for callback in self.callbacks['after_relationships_get']:
            ret = callback(self, ret)
        return ret

    @jsonapi_view
    def relationships_post(self):
        """Handle POST requests for TOMANY relationships.

        Add the specified member to the relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPNotFound: if an attempt is made to modify a TOONE relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Add comments/1 as a comment of posts/1

            .. parsed-literal::

                http POST http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        """
        obj_id = self.request.matchdict['id']
        relname = self.request.matchdict['relationship']
        mapper = sqlalchemy.inspect(self.model).mapper
        try:
            rel = mapper.relationships[relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                relname,
                self.collection_name
            ))
        if rel.direction is MANYTOONE:
            raise HTTPForbidden('Cannot POST to TOONE relationship link.')

        # Alter data with any callbacks
        data = self.request.json_body['data']
        for callback in self.callbacks['before_relationships_post']:
            data = callback(self, data)

        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        obj = self.dbsession.query(self.model).get(obj_id)
        items = []
        for resid in data:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(
                        resid['type'], rel_view.collection_name
                    )
                )
            try:
                items.append(self.dbsession.query(rel_class).get(resid['id']))
            except sqlalchemy.exc.DataError as exc:
                raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        getattr(obj, relname).extend(items)
        try:
            self.dbsession.flush()
        except sqlalchemy.exc.IntegrityError as exc:
            raise HTTPFailedDependency(str(exc))
        except sqlalchemy.orm.exc.FlushError as exc:
            if str(exc).startswith("Can't flush None value"):
                raise HTTPFailedDependency("One or more objects POSTed to this relationship do not exist.")
            else:
                # Catch-all. Shouldn't reach here.
                raise  # pragma: no cover
        return {}

    @jsonapi_view
    def relationships_patch(self):
        """Handle PATCH requests for relationships (TOMANY or TOONE).

        Completely replace the relationship membership.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            TOONE relationship:

            .. parsed-literal::

                {
                    "data": { resource identifier }
                }

            TOMANY relationship:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Replace comments list of posts/1:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" },
                    { "type": "comments", "id": "2" }
                ]' Content-Type:application/vnd.api+json
        """
        obj_id = self.request.matchdict['id']
        relname = self.request.matchdict['relationship']
        mapper = sqlalchemy.inspect(self.model).mapper
        try:
            rel = mapper.relationships[relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                relname,
                self.collection_name
            ))

        # Alter data with any callbacks
        data = self.request.json_body['data']
        for callback in self.callbacks['before_relationships_patch']:
            data = callback(self, data)

        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        obj = self.dbsession.query(self.model).get(obj_id)
        if rel.direction is MANYTOONE:
            local_col, _ = rel.local_remote_pairs[0]
            resid = data
            if resid is None:
                setattr(obj, relname, None)
            else:
                if resid['type'] != rel_view.collection_name:
                    raise HTTPConflict(
                        "Resource identifier type '{}' does not match relationship type '{}'.".format(
                            resid['type'],
                            rel_view.collection_name
                        )
                    )
                setattr(
                    obj,
                    local_col.name,
                    resid['id']
                )
                try:
                    self.dbsession.flush()
                except sqlalchemy.exc.IntegrityError as exc:
                    raise HTTPFailedDependency(
                        'Object {}/{} does not exist.'.format(resid['type'], resid['id'])
                    )
                except sqlalchemy.exc.DataError as exc:
                    raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
            return {}
        items = []
        for resid in self.request.json_body['data']:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(
                        resid['type'],
                        rel_view.collection_name
                    )
                )
            try:
                items.append(self.dbsession.query(rel_class).get(resid['id']))
            except sqlalchemy.exc.DataError as exc:
                raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        setattr(obj, relname, items)
        try:
            self.dbsession.flush()
        except sqlalchemy.exc.IntegrityError as exc:
            raise HTTPFailedDependency(str(exc))
        except sqlalchemy.orm.exc.FlushError as exc:
            if str(exc).startswith("Can't flush None value"):
                raise HTTPFailedDependency("One or more objects PATCHed to this relationship do not exist.")
            else:
                # Catch-all. Shouldn't reach here.
                raise  # pragma: no cover
        return {}

    @jsonapi_view
    def relationships_delete(self):
        """Handle DELETE requests for TOMANY relationships.

        Delete the specified member from the relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPNotFound: if an attempt is made to modify a TOONE relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Delete comments/1 from posts/1 comments:

            .. parsed-literal::

                http DELETE http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        """
        self.dbsession = self.dbsession()
        obj_id = self.request.matchdict['id']
        relname = self.request.matchdict['relationship']
        mapper = sqlalchemy.inspect(self.model).mapper
        try:
            rel = mapper.relationships[relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                relname,
                self.collection_name
            ))
        if rel.direction is MANYTOONE:
            raise HTTPForbidden('Cannot DELETE to TOONE relationship link.')
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        obj = self.dbsession.query(self.model).get(obj_id)

        # Call callbacks
        for callback in self.callbacks['before_relationships_delete']:
            callback(self, obj)

        for resid in self.request.json_body['data']:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(
                        resid['type'], rel_view.collection_name
                    )
                )
            try:
                item = self.dbsession.query(rel_class).get(resid['id'])
            except sqlalchemy.exc.DataError as exc:
                raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
            if item is None:
                raise HTTPFailedDependency("One or more objects DELETEd from this relationship do not exist.")
            try:
                getattr(obj, relname).remove(item)
            except ValueError as exc:
                if exc.args[0].endswith(': x not in list'):
                    # The item we were asked to remove is not there.
                    pass
                else:
                    raise
        try:
            self.dbsession.flush()
        except sqlalchemy.exc.IntegrityError as exc:
            raise HTTPFailedDependency(str(exc))
        return {}

    @property
    def single_item_query(self):
        """A query representing the single item referenced by the request.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch item with id
            'id'.
        """
        return self.dbsession.query(
            self.model
        ).options(
            load_only(*self.allowed_requested_query_columns.keys())
        ).filter(
            self.id_col(self.model) == self.request.matchdict['id']
        )

    def single_return(self, query, not_found_message=None, identifier=False):
        """Populate return dictionary for a single item.

        Arguments:
            query (sqlalchemy.orm.query.Query): query designed to return one item.

        Keyword Arguments:
            not_found_message (str or None): if an item is not found either:

                * raise 404 with ``not_found_message`` if it is a str;

                * or return ``{"data": None}`` if ``not_found_message`` is None.

            identifier: return identifier if True, object if false.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object }

                    optionally...
                    "included": [ included objects ]
                }

            or

            .. parsed-literal::

                { resource identifier }

        Raises:
            HTTPNotFound: if the item is not found.
        """
        included = {}
        doc = pyramid_jsonapi.jsonapi.Document()
        try:
            item = query.one()
        except NoResultFound:
            if not_found_message:
                raise HTTPNotFound(not_found_message)
            else:
                return doc
        if identifier:
            doc.data = self.serialise_resource_identifier(self.id_col(item))
        else:
            doc.data = self.serialise_db_item(item, included)
            if self.requested_include_names():
                doc.included = [obj for obj in included.values()]
        return doc

    def collection_return(self, query, count=None, identifiers=False):
        """Populate return document for collections.

        Arguments:
            query (sqlalchemy.orm.query.Query): query designed to return multiple
            items.

        Keyword Arguments:
            count(int): Number of items the query will return (if known).

            identifiers(bool): return identifiers if True, objects if false.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": [ resource objects ]

                    optionally...
                    "included": [ included objects ]
                }

            or

            .. parsed-literal::

                [ resource identifiers ]

        Raises:
            HTTPBadRequest: If a count was not supplied and an attempt to call
            q.count() failed.
        """
        # Get info for query.
        qinfo = self.collection_query_info(self.request)

        # Add information to the return dict
        doc = pyramid_jsonapi.jsonapi.Document(collection=True)
        results = {}

        try:
            count = count or query.count()
        except sqlalchemy.exc.ProgrammingError:
            raise HTTPInternalServerError(
                'An error occurred querying the database. Server logs may have details.'
            )

        results['available'] = count

        # Pagination links
        doc.links = self.pagination_links(
            count=results['available']
        )
        results['limit'] = qinfo['page[limit]']
        results['offset'] = qinfo['page[offset]']

        # Primary data
        try:
            if identifiers:
                data = [
                    self.serialise_resource_identifier(self.id_col(dbitem))
                    for dbitem in query.all()
                ]
            else:
                included = {}
                data = [
                    self.serialise_db_item(dbitem, included)
                    for dbitem in query.all()
                ]
                # Included objects
                if self.requested_include_names():
                    doc.included = [obj for obj in included.values()]
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest(str(exc.orig))
        for item in data:
            res = pyramid_jsonapi.jsonapi.Resource()
            res.update(item)
            doc.resources.append(res)
        results['returned'] = len(doc.data)

        doc.meta = {'results': results}
        return doc

    def query_add_sorting(self, query):
        """Add sorting to query.

        Use information from the ``sort`` query parameter (via
        :py:func:`collection_query_info`) to contruct an ``order_by`` clause on
        the query.

        See Also:
            ``_sort`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **sort:** comma separated list of sort keys.

        Parameters:
            query (sqlalchemy.orm.query.Query): query

        Returns:
            sqlalchemy.orm.query.Query: query with ``order_by`` clause.
        """
        # Get info for query.
        qinfo = self.collection_query_info(self.request)

        # Sorting.
        for key_info in qinfo['_sort']:
            sort_keys = key_info['key'].split('.')
            # We are using 'id' to stand in for the key column, whatever that
            # is.
            main_key = sort_keys[0]
            if main_key == 'id':
                main_key = self.key_column.name
            order_att = getattr(self.model, main_key)
            # order_att will be a sqlalchemy.orm.properties.ColumnProperty if
            # sort_keys[0] is the name of an attribute or a
            # sqlalchemy.orm.relationships.RelationshipProperty if sort_keys[0]
            # is the name of a relationship.
            if isinstance(order_att.property, RelationshipProperty):
                # If order_att is a relationship then we need to add a join to
                # the query and order_by the sort_keys[1] column of the
                # relationship's target. The default target column is 'id'.
                query = query.join(order_att)
                rel = order_att.property
                try:
                    sub_key = sort_keys[1]
                except IndexError:
                    # Use the relationship
                    sub_key = self.view_instance(
                        rel.mapper.class_
                    ).key_column.name
                order_att = getattr(rel.mapper.entity, sub_key)
            if key_info['ascending']:
                query = query.order_by(order_att)
            else:
                query = query.order_by(order_att.desc())

        return query

    def query_add_filtering(self, query):
        """Add filtering clauses to query.

        Use information from the ``filter`` query parameter (via
        :py:func:`collection_query_info`) to filter query results.

        Filter parameter structure:

            ``filter[<attribute>:<op>]=<value>``

        where:

            ``attribute`` is an attribute of the queried object type.

            ``op`` is the comparison operator.

            ``value`` is the value the comparison operator should compare to.

        Valid comparison operators:
            Only operators added via self.api.filter_registry.register() are
            considered valid. Get a list of filter names with
            self.api.filter_registry.valid_filter_names()

        See Also:
            ``_filters`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **filter[<attribute>:<op>]:** filter operation.

        Parameters:
            query (sqlalchemy.orm.query.Query): query

        Returns:
            sqlalchemy.orm.query.Query: filtered query.

        Examples:

            Get people whose name is 'alice'

            .. parsed-literal::

                http GET http://localhost:6543/people?filter[name:eq]=alice

            Get posts published after 2015-01-03:

            .. parsed-literal::

                http GET http://localhost:6543/posts?filter[published_at:gt]=2015-01-03

        Todo:
            Support dotted (relationship) attribute specifications.
        """
        qinfo = self.collection_query_info(self.request)
        # Filters
        for finfo in qinfo['_filters'].values():
            val = finfo['value']
            colspec = finfo['colspec']
            operator = finfo['op']
            try:
                prop = getattr(self.model, colspec[0])
            except AttributeError:
                raise HTTPBadRequest(
                    "Collection '{}' has no attribute '{}'".format(
                        self.collection_name, '.'.join(colspec)
                    )
                )
            if isinstance(prop.property, RelationshipProperty):
                # The property indicated is on the other side of a relationship
                query = query.join(prop)
                prop = getattr(prop.property.mapper.class_, colspec[1])
            try:
                filtr = self.api.filter_registry.get_filter(type(prop.type), operator)
            except KeyError:
                raise HTTPBadRequest(
                    "No such filter operator: '{}'".format(operator)
                )
            val = filtr['value_transform'](val)
            try:
                comparator = getattr(prop, filtr['comparator_name'])
            except AttributeError:
                raise HTTPInternalServerError(
                    "Operator '{}' is registered but has no implementation on attribute '{}'.".format(
                        operator, '.'.join(colspec)
                    )
                )
            query = query.filter(comparator(val))

        return query

    def related_limit(self, relationship):
        """Paging limit for related resources.

        **Query Parameters**

            **page[limit:relationships:<relname>]:** number of results to
            return per page for related resource <relname>.

        Parameters:
            relationship(sqlalchemy.orm.relationships.RelationshipProperty):
                the relationship to get the limit for.

        Returns:
            int: paging limit for related resources.
        """
        limit_comps = ['limit', 'relationships', relationship.key]
        limit = self.default_limit
        qinfo = self.collection_query_info(self.request)
        while limit_comps:
            if '.'.join(limit_comps) in qinfo['_page']:
                limit = int(qinfo['_page']['.'.join(limit_comps)])
                break
            limit_comps.pop()
        return min(limit, self.max_limit)

    def related_query(self, obj_id, relationship, full_object=True):
        """Construct query for related objects.

        Parameters:
            obj_id (str): id of an item in this view's collection.

            relationship (sqlalchemy.orm.relationships.RelationshipProperty):
                the relationships to get related objects from.

            full_object (bool): if full_object is ``True``, query for all
                requested columns (probably to build resource objects). If
                full_object is False, only query for the key column (probably
                to build resource identifiers).

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch related
            object(s).
        """
        rel = relationship
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        local_col, rem_col = rel.local_remote_pairs[0]
        query = self.dbsession.query(rel_class)
        if full_object:
            query = query.options(
                load_only(*rel_view.allowed_requested_query_columns.keys())
            )
        else:
            query = query.options(load_only(rel_view.key_column.name))
        if rel.direction is ONETOMANY:
            query = query.filter(obj_id == rem_col)
        elif rel.direction is MANYTOMANY:
            query = query.filter(
                obj_id == rel.primaryjoin.right
            ).filter(
                self.id_col(rel_class) == rel.secondaryjoin.right
            )
        elif rel.direction is MANYTOONE:
            query = query.filter(
                local_col == self.id_col(rel_class)
            ).filter(
                self.id_col(self.model) == obj_id
            )
        else:
            raise HTTPError('Unknown relationships direction, "{}".'.format(
                rel.direction.name
            ))

        return query

    def object_exists(self, obj_id):
        """Test if object with id obj_id exists.

        Args:
            obj_id (str): object id

        Returns:
            bool: True if object exists, False if not.
        """
        try:
            item = self.dbsession.query(
                self.model
            ).options(
                load_only(self.key_column.name)
            ).get(obj_id)
        except (sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            item = False
        return bool(item)

    def column_info_from_name(self, name, model=None):
        """Get the pyramid_jsonapi info dictionary for a column.

        Parameters:
            name (str): name of column.

            model (sqlalchemy.ext.declarative.declarative_base): model to
                inspect. Defaults to self.model.

        """
        return sqlalchemy.inspect(model or self.model).all_orm_descriptors.get(
            name
        ).info.get('pyramid_jsonapi', {})

    def serialise_resource_identifier(self, obj_id):
        """Return a resource identifier dictionary for id "obj_id"

        """
        ret = {
            'type': self.collection_name,
            'id': str(obj_id)
        }

        for callback in self.callbacks['after_serialise_identifier']:
            ret = callback(self, ret)

        return ret

    def serialise_db_item(
            self, item,
            included, include_path=None,
    ):
        """Serialise an individual database item to JSON-API.

        Arguments:
            item: item to serialise.

        Keyword Arguments:
            included (dict): dictionary to be filled with included resource
                objects.
            include_path (list): list tracking current include path for
                recursive calls.

        Returns:
            jsonapi.Resource:
        """

        include_path = include_path or []

        # Item's id and type are required at the top level of json-api
        # objects.
        # The item's id.
        item_id = self.id_col(item)
        # JSON API type.
        item_url = self.request.route_url(
            self.api.endpoint_data.make_route_name(self.collection_name, suffix='item'),
            **{'id': item_id}
        )

        atts = {
            key: getattr(item, key)
            for key in self.requested_attributes.keys()
            if self.column_info_from_name(key).get('visible', True)
        }

        rels = {}
        for key, rel in self.relationships.items():
            rel_path_str = '.'.join(include_path + [key])
            if key not in self.requested_relationships and\
                    rel_path_str not in self.requested_include_names():
                continue
            rel_dict = {
                'links': {
                    'self': '{}/relationships/{}'.format(item_url, key),
                    'related': '{}/{}'.format(item_url, key)
                },
                'meta': {
                    'direction': rel.direction.name,
                    'results': {}
                }
            }
            rel_class = rel.mapper.class_
            rel_view = self.view_instance(rel_class)
            is_included = False
            if rel_path_str in self.requested_include_names():
                is_included = True
            query = self.related_query(
                item_id, rel, full_object=is_included
            )
            if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
                limit = self.related_limit(rel)
                rel_dict['meta']['results']['limit'] = limit
                rel_dict['meta']['results']['available'] = query.count()
                query = query.limit(limit)
                rel_dict['data'] = []
                for ritem in query.all():
                    rel_dict['data'].append(
                        rel_view.serialise_resource_identifier(
                            self.id_col(ritem)
                        )
                    )
                    if is_included:
                        included[
                            (rel_view.collection_name, self.id_col(ritem))
                        ] = rel_view.serialise_db_item(
                            ritem,
                            included, include_path + [key]
                        )
                rel_dict['meta']['results']['returned'] =\
                    len(rel_dict['data'])
            else:
                if is_included:
                    ritem = None
                    try:
                        ritem = query.one()
                    except sqlalchemy.orm.exc.NoResultFound:
                        rel_dict['data'] = None
                    if ritem:
                        included[
                            (rel_view.collection_name, self.id_col(ritem))
                        ] = rel_view.serialise_db_item(
                            ritem,
                            included, include_path + [key]
                        )

                else:
                    rel_id = getattr(
                        item,
                        rel.local_remote_pairs[0][0].name
                    )
                    if rel_id is None:
                        rel_dict['data'] = None
                    else:
                        rel_dict[
                            'data'
                        ] = rel_view.serialise_resource_identifier(
                            rel_id
                        )
            if key in self.requested_relationships:
                rels[key] = rel_dict

        resource_json = pyramid_jsonapi.jsonapi.Resource(self)

        resource_json.id = str(item_id)
        resource_json.attributes = atts
        resource_json.links = {'self': item_url}
        resource_json.relationships = rels

        for callback in self.callbacks['after_serialise_object']:
            callback(self, resource_json)

        return resource_json.as_dict()

    @classmethod
    @functools.lru_cache()
    def collection_query_info(cls, request):
        """Return dictionary of information used during DB query.

        Args:
            request (pyramid.request): request object.

        Returns:
            dict: query info in the form::

                {
                    'page[limit]': maximum items per page,
                    'page[offset]': offset for current page (in items),
                    'sort': sort param from request,
                    '_sort': [
                        {
                            'key': sort key ('field' or 'relationship.field'),
                            'ascending': sort ascending or descending (bool)
                        },
                        ...
                    },
                    '_filters': {
                        filter_param_name: {
                            'colspec': list of columns split on '.',
                            'op': filter operator,
                            'value': value of filter param,
                        }
                    },
                    '_page': {
                        paging_param_name: value,
                        ...
                    }
                }

            Keys beginning with '_' are derived.
        """
        info = {}

        # Paging by limit and offset.
        # Use params 'page[limit]' and 'page[offset]' to comply with spec.
        info['page[limit]'] = min(
            cls.max_limit,
            int(request.params.get('page[limit]', cls.default_limit))
        )
        info['page[offset]'] = int(request.params.get('page[offset]', 0))

        # Sorting.
        # Use param 'sort' as per spec.
        # Split on '.' to allow sorting on columns of relationship tables:
        #   sort=name -> sort on the 'name' column.
        #   sort=owner.name -> sort on the 'name' column of the target table
        #     of the relationship 'owner'.
        # The default sort column is 'id'.
        sort_param = request.params.get('sort', cls.key_column.name)
        info['sort'] = sort_param

        # Break sort param down into components and store in _sort.
        info['_sort'] = []
        for sort_key in sort_param.split(','):
            key_info = {}
            # Check to see if it starts with '-', which indicates a reverse
            # sort.
            ascending = True
            if sort_key.startswith('-'):
                ascending = False
                sort_key = sort_key[1:]
            key_info['key'] = sort_key
            key_info['ascending'] = ascending
            info['_sort'].append(key_info)

        # Find all parametrised parameters ( :) )
        info['_filters'] = {}
        info['_page'] = {}
        for param in request.params.keys():
            match = re.match(r'(.*?)\[(.*?)\]', param)
            if not match:
                continue
            val = request.params.get(param)

            # Filtering.
            # Use 'filter[<condition>]' param.
            # Format:
            #   filter[<column_spec>:<operator>] = <value>
            #   where:
            #     <column_spec> is either:
            #       <column_name> for an attribute, or
            #       <relationship_name>.<column_name> for a relationship.
            # Examples:
            #   filter[name:eq]=Fred
            #      would find all objects with a 'name' attribute of 'Fred'
            #   filter[author.name:eq]=Fred
            #      would find all objects where the relationship author pointed
            #      to an object with 'name' 'Fred'
            #
            # Find all the filters.
            if match.group(1) == 'filter':
                colspec, operator = match.group(2).split(':')
                colspec = colspec.split('.')
                info['_filters'][param] = {
                    'colspec': colspec,
                    'op': operator,
                    'value': val
                }

            # Paging.
            elif match.group(1) == 'page':
                info['_page'][match.group(2)] = val

        return info

    def pagination_links(self, count=0):
        """Return a dictionary of pagination links.

        Args:
            count (int): total number of results available.

        Returns:
            dict: dictionary of named links.
        """
        links = {}
        req = self.request
        route_name = req.matched_route.name
        qinfo = self.collection_query_info(req)
        _query = {'page[{}]'.format(k): v for k, v in qinfo['_page'].items()}
        _query['sort'] = qinfo['sort']
        for filtr in sorted(qinfo['_filters']):
            _query[filtr] = qinfo['_filters'][filtr]['value']

        # First link.
        _query['page[offset]'] = 0
        links['first'] = req.route_url(
            route_name, _query=_query, **req.matchdict
        )

        # Next link.
        next_offset = qinfo['page[offset]'] + qinfo['page[limit]']
        if count is None or next_offset < count:
            _query['page[offset]'] = next_offset
            links['next'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Previous link.
        if qinfo['page[offset]'] > 0:
            prev_offset = qinfo['page[offset]'] - qinfo['page[limit]']
            if prev_offset < 0:
                prev_offset = 0
            _query['page[offset]'] = prev_offset
            links['prev'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Last link.
        if count is not None:
            _query['page[offset]'] = (
                max((count - 1), 0) //
                qinfo['page[limit]']
            ) * qinfo['page[limit]']
            links['last'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )
        return links

    @property
    def allowed_fields(self):
        """Set of fields to which current action is allowed.

        Returns:
            set: set of allowed field names.
        """
        return set(self.fields)

    def allowed_object(self, obj):  # pylint:disable=no-self-use,unused-argument
        """Whether or not current action is allowed on object.

        Returns:
            bool:
        """
        return True

    @property
    @functools.lru_cache()
    def requested_field_names(self):
        """Get the sparse field names from request.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            set: set of field names.
        """
        param = self.request.params.get(
            'fields[{}]'.format(self.collection_name)
        )
        if param is None:
            return set(self.attributes.keys()).union(
                self.hybrid_attributes.keys()
            ).union(
                self.relationships.keys()
            )
        elif param == '':
            return set()
        return set(param.split(','))

    @property
    def requested_attributes(self):
        """Return a dictionary of attributes.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <colname>: <column_object>,
                        ...
                    }
        """
        return {
            k: v for k, v in itertools.chain(
                self.attributes.items(), self.hybrid_attributes.items()
            )
            if k in self.requested_field_names
        }

    @property
    def requested_relationships(self):
        """Return a dictionary of relationships.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <relname>: <relationship_object>,
                        ...
                    }
        """
        return {
            k: v for k, v in self.relationships.items()
            if k in self.requested_field_names
        }

    @property
    def requested_fields(self):
        """Union of attributes and relationships.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <colname>: <column_object>,
                        ...
                        <relname>: <relationship_object>,
                        ...
                    }

        """
        ret = self.requested_attributes
        ret.update(
            self.requested_relationships
        )
        return ret

    @property
    def allowed_requested_relationships_local_columns(self):  # pylint:disable=invalid-name
        """Finds all the local columns for allowed MANYTOONE relationships.

        Returns:
            dict: local columns indexed by column name.
        """
        return {
            pair[0].name: pair[0]
            for k, rel in self.requested_relationships.items()
            for pair in rel.local_remote_pairs
            if rel.direction is MANYTOONE and k in self.allowed_fields
        }

    @property
    def allowed_requested_query_columns(self):
        """All columns required in query to fetch allowed requested fields from
        db.

        Returns:
            dict: Union of allowed requested_attributes and
            allowed_requested_relationships_local_columns
        """
        ret = {
            k: v for k, v in self.requested_attributes.items()
            if k in self.allowed_fields and k not in self.hybrid_attributes
        }
        ret.update(
            self.allowed_requested_relationships_local_columns
        )
        return ret

    @functools.lru_cache()
    def requested_include_names(self):
        """Parse any 'include' param in http request.

        Returns:
            set: names of all requested includes.

        Default:
            set: names of all direct relationships of self.model.
        """
        inc = set()
        param = self.request.params.get('include')

        if param:
            for item in param.split(','):
                curname = []
                for name in item.split('.'):
                    curname.append(name)
                    inc.add('.'.join(curname))
        return inc

    @property
    def bad_include_paths(self):
        """Return a set of invalid 'include' parameters.

        **Query Parameters**

            **include:** comma separated list of related resources to include
            in the include section.

        Returns:
            set: set of requested include paths with no corresponding
            attribute.
        """
        param = self.request.params.get('include')
        bad = set()
        if param:
            for item in param.split(','):
                curname = []
                curview = self
                tainted = False
                for name in item.split('.'):
                    curname.append(name)
                    if tainted:
                        bad.add('.'.join(curname))
                    else:
                        if name in curview.relationships.keys():
                            curview = curview.view_instance(
                                curview.relationships[name].mapper.class_
                            )
                        else:
                            tainted = True
                            bad.add('.'.join(curname))
        return bad

    @functools.lru_cache()
    def view_instance(self, model):
        """(memoised) get an instance of view class for model.

        Args:
            model (DeclarativeMeta): model class.

        Returns:
            class: subclass of CollectionViewBase providing view for ``model``.
        """
        return self.api.view_classes[model](self.request)

    @classmethod
    def append_callback_set(cls, set_name):
        """Append a named set of callbacks from ``callback_sets``.

        Args:
            set_name (str): key in ``callback_sets``.
        """
        for cb_name, callback in cls.callback_sets[set_name].items():
            cls.callbacks[cb_name].append(callback)

    def acso_after_serialise_object(view, obj):  # pylint:disable=no-self-argument
        """Standard callback altering object to take account of permissions.

        Args:
            obj (dict): the object immediately after serialisation.

        Returns:
            dict: the object, possibly with some fields removed, or meta
            information indicating permission was denied to the whole object.
        """
        if view.allowed_object(obj):
            # Remove any forbidden fields that have been added by other
            # callbacks. Those from the model won't have been added in the first
            # place.

            # Keep track so we can tell the caller which ones were forbidden.
            forbidden = set()
            if hasattr(obj, 'attributes'):
                atts = {}
                for name, val in obj.attributes.items():
                    if name in view.allowed_fields:
                        atts[name] = val
                    else:
                        forbidden.add(name)
                obj.attributes = atts
            if hasattr(obj, 'relationships'):
                rels = {}
                for name, val in obj.relationships.items():
                    if name in view.allowed_fields:
                        rels[name] = val
                    else:
                        forbidden.add(name)
                obj.relationships = rels
            # Now add all the forbidden fields from the model to the forbidden
            # list. They don't need to be removed from the serialised object
            # because they should not have been added in the first place.
            for field in view.requested_field_names:
                if field not in view.allowed_fields:
                    forbidden.add(field)
            if not hasattr(obj, 'meta'):
                obj.meta = {}
            obj.meta['forbidden_fields'] = list(forbidden)
        else:
            obj.meta = {
                'errors': [
                    {
                        'code': 403,
                        'title': 'Forbidden',
                        'detail': 'No permission to view {}/{}.'.format(
                            obj.type, obj.id
                        )
                    }
                ]
            }
        return obj

    def acso_after_get(view, ret):  # pylint:disable=unused-argument, no-self-argument, no-self-use
        """Standard callback throwing 403 (Forbidden) based on information in meta.

        Args:
            ret (jsonapi.Document): object which would have been returned from get().

        Returns:
            jsonapi.Document: the same object if an error has not been raised.

        Raises:
            HTTPForbidden
        """
        obj = ret
        errors = []
        try:
            errors = obj.meta['errors']
        except KeyError:
            return ret
        for error in errors:
            if error['code'] == 403:
                raise HTTPForbidden(error['detail'])
        return ret

    callback_sets = {
        'access_control_serialised_objects': {
            'after_serialise_object': acso_after_serialise_object,
            'after_get': acso_after_get
        }
    }


class FilterRegistry:
    """Registry of allowed filter operators.

    Attributes:
        data (dict): data store for filter op information.
    """

    def __init__(self):
        self.data = {}

    def register(
            self,
            comparator_name,
            filter_name=None,
            value_transform=lambda val: val,
            column_type='__ALL__'
    ):
        """ Register a new filter operator.

        Args:
            comparator_name (str): name of sqlalchemy comparator method.
            filter_name(str): name of filter param in URL. Defaults to
                comparator_name with any occurrences of '__' removed (so '__eq__'
                defaults to 'eq', for example).
            value_transform (func): function taking the filter value as the only
                argument and returning a transformed value. Defaults to a
                function returning an unmodified value.
            column_type (class): type (class object, not name) for which this
                operator is to be registered. Defaults to '__ALL__' (the string)
                which makes the operator valid for all column types.
        """
        try:
            registry = self.data[column_type]
        except KeyError:
            registry = self.data[column_type] = {}
        registry[filter_name or comparator_name.replace('__', '')] = {
            'comparator_name': comparator_name,
            'value_transform': value_transform
        }

    def get_filter(self, column_type, filter_name):
        """Get dictionary of filter information.

        Args:
            column_type (class): type (class object, not name) of a Column.
            filter_name(str): name of filter param in URL.

        Returns:
            dict: information dictionary for filter. Type specific entry if it
                exists, entry from '__ALL__' if it does not.

        Raises:
            KeyError: if filter_name is not in the type specific or ALL sections.
        """
        try:
            return self.data[column_type][filter_name]
        except KeyError:
            return self.data['__ALL__'][filter_name]

    def valid_filter_names(self, column_types=None):
        """Return set of supported filter operator names."""
        ops = set()
        column_types = set(column_types or {k for k in self.data})
        column_types.add('__ALL__')
        for ctype in column_types:
            ops |= self.data[ctype].keys()
        return ops


class DebugView:
    """Pyramid view class defining a debug API.

    These are available as ``/debug/{action}`` if
    ``pyramid_jsonapi.debug_endpoints == 'true'``.

    Attributes:
        engine: sqlalchemy engine with connection to the db.
        metadata: sqlalchemy model metadata
        test_data: module with an ``add_to_db()`` method which will populate
            the database
    """
    def __init__(self, request):
        self.request = request

    def drop(self):
        """Drop all tables from the database!!!
        """
        self.metadata.drop_all(self.engine)
        return 'dropped'

    def populate(self):
        """Create tables and populate with test data.
        """
        # Create or update tables and schema. Safe if tables already exist.
        self.metadata.create_all(self.engine)
        # Add test data. Safe if test data already exists.
        self.test_data.add_to_db()
        return 'populated'

    def reset(self):
        """The same as 'drop' and then 'populate'.
        """
        self.drop()
        self.populate()
        return "reset"
