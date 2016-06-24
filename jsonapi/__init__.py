'''Tools for constructing a JSON-API from sqlalchemy models in Pyramid.'''
import json
#from sqlalchemy import inspect
import transaction
import sqlalchemy
from pyramid.view import view_config, notfound_view_config, forbidden_view_config
from pyramid.renderers import JSON
from pyramid.httpexceptions import exception_response, HTTPException, HTTPNotFound, HTTPForbidden, HTTPUnauthorized, HTTPClientError, HTTPBadRequest, HTTPConflict, HTTPUnsupportedMediaType, HTTPNotAcceptable, HTTPNotImplemented, HTTPError, HTTPFailedDependency
import pyramid
import sys
import inspect
import re
from collections import namedtuple
import psycopg2
import pprint
import functools
import types
import importlib

from zope.sqlalchemy import ZopeTransactionExtension
from sqlalchemy.orm import sessionmaker, scoped_session, load_only
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.ext.declarative.api import DeclarativeMeta

ONETOMANY = sqlalchemy.orm.interfaces.ONETOMANY
MANYTOMANY = sqlalchemy.orm.interfaces.MANYTOMANY
MANYTOONE = sqlalchemy.orm.interfaces.MANYTOONE

#DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))
route_prefix = 'jsonapi'
view_classes = {}

def error(e, request):
    request.response.content_type = 'application/vnd.api+json'
    request.response.status_code = e.code
    return {
        'errors': [
            {
                'code': str(e.code),
                'detail': e.detail,
                'title': e.title,
            }
        ]
    }

def create_jsonapi(config, models, get_dbsession,
    engine = None, test_data = None):
    '''Auto-create jsonapi from module or iterable of sqlAlchemy models.

    Arguments:
        config: ``pyramid.config.Configurator`` object from current app.
        models: an iterable (or module) of model classes derived
            from DeclarativeMeta.
        get_dbsession: a callable shich returns a
            sqlalchemy.orm.session.Session or equivalent.

    Keyword Args:
        engine: a sqlalchemy.engine.Engine instance. Only required if using the
            debug view.
        test_data: a module with an ``add_to_db()`` method which will populate
            the database.
    '''

    config.add_notfound_view(error, renderer='json')
    config.add_forbidden_view(error, renderer='json')
    config.add_view(error, context=HTTPError, renderer='json')

    # Build a list of declarative models to add as collections.
    if isinstance(models, types.ModuleType):
        model_list = []
        for attr in models.__dict__.values():
            if isinstance(attr, DeclarativeMeta):
                try:
                    keycols = sqlalchemy.inspect(attr).primary_key
                except sqlalchemy.exc.NoInspectionAvailable:
                    # Trying to inspect the declarative_base() raises this
                    # exception. We don't want to add it to the API.
                    continue
                model_list.append(attr)
    else:
        model_list = list(models)

    settings = config.registry.settings

    # Add the debug endpoints if required.
    if settings.get('jsonapi.debug.debug_endpoints', 'false') == 'true':
        if engine is None:
            DebugView.engine = model_list[0].metadata.bind
        else:
            DebugView.engine = engine
        DebugView.metadata = model_list[0].metadata
        if test_data is None:
            test_data = importlib.import_module(
                settings.get('jsonapi.debug.test_data_module', 'test_data')
            )
        DebugView.test_data = test_data
        config.add_route('debug', '/debug/{action}')
        config.add_view(DebugView, attr='drop',
            route_name='debug', match_param='action=drop', renderer='json')
        config.add_view(DebugView, attr='populate',
            route_name='debug', match_param='action=populate', renderer='json')
        config.add_view(DebugView, attr='reset',
            route_name='debug', match_param='action=reset', renderer='json')

    # Loop through the models list. Create resource endpoints for these and
    # any relationships found.
    for model_class in model_list:
        create_resource(config, model_class, get_dbsession = get_dbsession)

create_jsonapi_using_magic_and_pixie_dust = create_jsonapi

def create_resource(config, model, get_dbsession,
        collection_name = None,
        allowed_fields = None,
    ):
    '''Produce a set of resource endpoints.

    Arguments:
        config: ``pyramid.config.Configurator`` object from current app.
        model: a model class derived from DeclarativeMeta.
        get_dbsession: a callable shich returns a
            sqlalchemy.orm.session.Session or equivalent.

    Keyword Args:
        collection_name: string name of collection. Passed through to
            ``collection_view_factory()``
        allowed_fields: set of allowed field names. Passed through to
            ``collection_view_factory()``
    '''

    # Find the primary key column from the model and add it as _jsonapi_id.
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
                model_class.__name__
            )
        )
    model._jsonapi_id = getattr(model, keycols[0].name)

    # Figure out what table model is from
    info = ModelInfo.construct(model)

    if collection_name is None:
        collection_name = info.table_name

    # Create a view class for use in the various add_view() calls below.
    view = collection_view_factory(model, get_dbsession, collection_name,
        allowed_fields = allowed_fields)
    view_classes['collection_name'] = view
    view_classes[model] = view

    view.default_limit =\
        int(config.registry.settings.get('jsonapi.paging.default_limit', 10))
    view.max_limit =\
        int(config.registry.settings.get('jsonapi.paging.max_limit', 100))

    # individual item
    config.add_route(view.item_route_name, view.item_route_pattern)
    # GET
    config.add_view(view, attr='get', request_method='GET',
        route_name=view.item_route_name, renderer='json')
    # DELETE
    config.add_view(view, attr='delete', request_method='DELETE',
        route_name=view.item_route_name, renderer='json')
    # PATCH
    config.add_view(view, attr='patch', request_method='PATCH',
        route_name=view.item_route_name, renderer='json')

    # collection
    config.add_route(view.collection_route_name, view.collection_route_pattern)
    # GET
    config.add_view(view, attr='collection_get', request_method='GET',
        route_name=view.collection_route_name, renderer='json')
    # POST
    config.add_view(view, attr='collection_post', request_method='POST',
        route_name=view.collection_route_name, renderer='json')

    # related
    config.add_route(view.related_route_name, view.related_route_pattern)
    # GET
    config.add_view(view, attr='related_get', request_method='GET',
        route_name=view.related_route_name, renderer='json')

    # relationships
    config.add_route(
        view.relationships_route_name,
        view.relationships_route_pattern
    )
    # GET
    config.add_view(view, attr='relationships_get', request_method='GET',
        route_name=view.relationships_route_name, renderer='json')
    # POST
    config.add_view(view, attr='relationships_post', request_method='POST',
        route_name=view.relationships_route_name, renderer='json')
    # PATCH
    config.add_view(view, attr='relationships_patch', request_method='PATCH',
        route_name=view.relationships_route_name, renderer='json')
    # DELETE
    config.add_view(view, attr='relationships_delete', request_method='DELETE',
        route_name=view.relationships_route_name, renderer='json')

def collection_view_factory(
        model,
        get_dbsession,
        collection_name = None,
        allowed_fields = None
    ):
    '''Build a class to handle requests for model.

    Arguments:
        model: a model class derived from DeclarativeMeta.
        get_dbsession: a callable shich returns a
            sqlalchemy.orm.session.Session or equivalent.

    Keyword Args:
        collection_name: string name of collection.
        allowed_fields: set of allowed field names.
    '''
    if collection_name is None:
        collection_name = model.__tablename__

    CollectionView = type(
        'CollectionView<{}>'.format(collection_name),
        (CollectionViewBase, ),
        {}
    )

    CollectionView.model = model
    CollectionView.key_column = sqlalchemy.inspect(model).primary_key[0]
    CollectionView.collection_name = collection_name
    CollectionView.get_dbsession = get_dbsession

    CollectionView.collection_route_name =\
        ':'.join((route_prefix, collection_name))
    CollectionView.collection_route_pattern = collection_name

    CollectionView.item_route_name =\
        CollectionView.collection_route_name + ':item'
    CollectionView.item_route_pattern = collection_name + '/{id}'

    CollectionView.related_route_name =\
        CollectionView.collection_route_name + ':related'
    CollectionView.related_route_pattern =\
        collection_name + '/{id}/{relationship}'

    CollectionView.relationships_route_name =\
        CollectionView.collection_route_name + ':relationships'
    CollectionView.relationships_route_pattern =\
        collection_name + '/{id}/relationships/{relationship}'

    CollectionView.class_allowed_fields = allowed_fields
    atts = {}
    for key, col in sqlalchemy.inspect(model).mapper.columns.items():
        if key == CollectionView.key_column.name:
            continue
        if len(col.foreign_keys) > 0:
            continue
        if allowed_fields is None or key in allowed_fields:
            atts[key] = col
    CollectionView.attributes = atts
    rels = {}
    for key, rel in sqlalchemy.inspect(model).mapper.relationships.items():
        if allowed_fields is None or key in allowed_fields:
            rels[key] = rel
    CollectionView.relationships = rels

    return CollectionView

class CollectionViewBase:
    '''Base class for all view classes.

    Arguments:
        request (pyramid.request): passed by framework.
    '''
    def __init__(self, request):
        self.request = request
        self.views = {}

    def jsonapi_view(f):
        '''Decorator for view functions. Adds jsonapi boilerplate.'''
        @functools.wraps(f)
        def new_f(self, *args):
            # Spec says to reject (with 415) any request with media type
            # params.
            cth = self.request.headers.get('content-type','').split(';')
            content_type = cth[0]
            params = None
            if len(cth) > 1:
                raise HTTPUnsupportedMediaType(
                    'Media Type parameters not allowed by JSONAPI ' +
                    'spec (http://jsonapi.org/format).'
                )
                params = cth[1].lstrip();

            # Spec says throw 406 Not Acceptable if Accept header has no
            # application/vnd.api+json entry without parameters.
            accepts = re.split(
                r',\s*',
                self.request.headers.get('accept','')
            )
            jsonapi_accepts = {
                a for a in accepts
                if a.startswith('application/vnd.api')
            }
            if jsonapi_accepts and\
                'application/vnd.api+json' not in jsonapi_accepts:
                raise HTTPNotAcceptable(
                    'application/vnd.api+json must appear with no ' +
                    'parameters in Accepts header ' +
                    '(http://jsonapi.org/format).'
                )

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

            # Eventually each method will return a dictionary to be rendered
            # using the JSON renderer.
            ret = {
                'meta': {}
            }

            # Update the dictionary with the reults of the wrapped method.
            ret.update(f(self, *args))

            # Include a self link unless the method is PATCH.
            if self.request.method != 'PATCH':
                selfie = {'self': self.request.url}
                if 'links' in ret:
                    ret['links'].update(selfie)
                else:
                    ret['links'] = selfie

            # Potentially add some debug information.
            if self.request.registry.settings.get(
                'jsonapi.debug.meta', 'false'
            ) == 'true':
                debug = {
                    'accept_header': {
                            a:None for a in jsonapi_accepts
                        },
                    'qinfo_page':\
                        self.collection_query_info(self.request)['_page'],
                    'atts': { k: None for k in self.attributes.keys() },
                    'includes': {
                        k:None for k in self.requested_include_names()
                    }
                }
                ret['meta'].update({'debug': debug})

            return ret
        return new_f


    @jsonapi_view
    def get(self):
        '''Handle GET request for a single item.

        Get a single item from the collection, referenced by id.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            dict: dict in the form:

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
        '''
        return self.single_return(
            self.single_item_query,
            'No id {} in collection {}'.format(
                self.request.matchdict['id'],
                self.collection_name
            )
        )

    @jsonapi_view
    def patch(self):
        '''Handle PATCH request for a single item.

        Update an existing item from a partially defined representation.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        **Request Body**

            **Partial resource object** (*json*)

        Returns:
            dict: dict in the form:

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
        '''
        try:
            self.single_item_query.one()
        except NoResultFound:
            raise HTTPNotFound(
                'Cannot PATCH a non existent resource ({}/{})'.format(
                    self.collection_name, self.request.matchdict['id']
                )
            )
        DBSession = self.get_dbsession()
        data = self.request.json_body['data']
        req_id = self.request.matchdict['id']
        data_id = data.get('id')
        if self.collection_name != data.get('type'):
            raise HTTPConflict('JSON type ({}) does not match URL type ({}).'.
            format(data.get('type'), self.collection_name))
        if data_id != req_id:
            raise HTTPConflict('JSON id ({}) does not match URL id ({}).'.
            format(data_id, req_id))
        atts = data.get('attributes',{})
        atts[self.key_column.name] = req_id
        item = DBSession.merge(self.model(**atts))

        rels = data.get('relationships', {})
        for relname, data in rels.items():
            if relname not in self.relationships:
                raise HTTPNotFound(
                    'Collection {} has no relationship {}'.format(
                        self.collection_name, relname
                    )
                )
            rel = self.relationships[relname]
            rel_class = rel.mapper.class_
            rel_view = self.view_instance(rel_class)
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
                try:
                    rel_item = DBSession.query(
                        rel_class
                    ).options(
                        load_only(rel_view.key_column.name)
                    ).filter(
                        rel_view.key_column == data['id']
                    ).one()
                except NoResultFound:
                    raise HTTPNotFound('{}/{} not found'.format(
                        rel_view.collection_name, data['id']
                    ))
                setattr(item, relname, rel_item)
            elif isinstance(data, list):
                rel_items = []
                for res_ident in data:
                    try:
                        rel_item = DBSession.query(
                            rel_class
                        ).options(
                            load_only(rel_view.key_column.name)
                        ).filter(
                            rel_view.key_column == res_ident['id']
                        ).one()
                    except NoResultFound:
                        raise HTTPNotFound('{}/{} not found'.format(
                            rel_view.collection_name, res_ident['id']
                        ))
                    rel_items.append(rel_item)
                setattr(item, relname, rel_items)

        DBSession.flush()
        return {
            'meta': {
                'updated': {
                    'attributes': [
                        att for att in atts
                            if att != self.key_column.name
                    ],
                    'relationships': [r for r in rels]
                }
            }
        }

    @jsonapi_view
    def delete(self):
        '''Handle DELETE request for single item.

        Delete the referenced item from the collection.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            dict: Resource Identifier for deleted object.

        Raises:
            HTTPFailedDependency: if collection/id does not exist

        Example:
            delete person 1:

            .. parsed-literal::

                http DELETE http://localhost:6543/people/1
        '''
        DBSession = self.get_dbsession()
        item = DBSession.query(self.model).get(self.request.matchdict['id'])
        if item:
            try:
                DBSession.delete(item)
                DBSession.flush()
            except sqlalchemy.exc.IntegrityError as e:
                raise HTTPFailedDependency(str(e))
            return {'data': {
                'type': self.collection_name,
                'id': self.request.matchdict['id'] }
            }
        else:
            return {'data': None}

    @jsonapi_view
    def collection_get(self):
        '''Handle GET requests for the collection.

        Get a set of items from the collection, possibly matching search/filter
        parameters. Optionally sort the results, page them, return only certain
        fields, and include related resources.

        **Query Parameters**

            **include:** comma separated list of related resources to include in
            the include section.

            **fields[<collection>]:** comma separated list of fields (attributes
            or relationships) to include in data.

            **sort:** comma separated list of sort keys.

            **page[limit]:** number of results to return per page.

            **page[offset]:** starting index for current page.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            dict: dict in the form:

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
        '''
        DBSession = self.get_dbsession()

        # Set up the query
        q = DBSession.query(
            self.model
        ).options(
            load_only(*self.requested_query_columns.keys())
        )
        q = self.query_add_sorting(q)
        q = self.query_add_filtering(q)
        qinfo = self.collection_query_info(self.request)
        try:
            count = q.count()
        except sqlalchemy.exc.ProgrammingError as e:
            raise HTTPBadRequest(
                "Could not use operator '{}' with field '{}'".format(
                    op, prop.name
                )
            )
        q = q.offset(qinfo['page[offset]'])
        q = q.limit(qinfo['page[limit]'])

        return self.collection_return(q, count=count)

    @jsonapi_view
    def collection_post(self):
        '''Handle POST requests for the collection.

        Create a new object in collection.

        **Request Body**

            **resource object** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": { resource object }
                }

        Returns:
            dict: dict in the form:

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
        '''
        DBSession = self.get_dbsession()
        data = self.request.json_body['data']
        # Check to see if we're allowing client ids
        if self.request.registry.settings.get('jsonapi.allow_client_ids', 'false') != 'true' and 'id' in data:
            raise HTTPForbidden('Client generated ids are not supported.')
        # Type should be correct or raise 409 Conflict
        datatype = data.get('type')
        if datatype != self.collection_name:
            raise HTTPConflict("Unsupported type '{}'".format(datatype))
        atts = data['attributes']
        if 'id' in data:
            atts['id'] = data['id']
        item = self.model(**atts)
        mapper = sqlalchemy.inspect(self.model).mapper
        with DBSession.no_autoflush:
            for relname, reldata in data.get('relationships', {}).items():
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
                if rel.direction is ONETOMANY\
                    or rel.direction is MANYTOMANY:
                    setattr(item, relname, [
                        DBSession.query(rel_class).get(rel_identifier['id'])
                            for rel_identifier in reldata['data']
                    ])
                else:
                    setattr(
                        item,
                        relname,
                        DBSession.query(rel_class).get(
                            reldata['data']['id'])
                        )
        try:
            DBSession.add(item)
            DBSession.flush()
        except sqlalchemy.exc.IntegrityError as e:
            raise HTTPConflict(e.args[0])
        self.request.response.status_code = 201
        self.request.response.headers['Location'] = self.request.route_url(
            self.item_route_name,
            **{'id': item._jsonapi_id}
        )
        return {
            'data': self.serialise_db_item(item, {})
        }

    @jsonapi_view
    def related_get(self):
        '''Handle GET requests for related URLs.

        Get object(s) related to a specified object.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            dict: dict in the form:

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
        '''
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

        # Set up the query
        q = self.related_query(obj_id, rel)

        if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
            q = rel_view.query_add_sorting(q)
            q = rel_view.query_add_filtering(q)
            qinfo = rel_view.collection_query_info(self.request)
            try:
                count = q.count()
            except sqlalchemy.exc.ProgrammingError as e:
                raise HTTPBadRequest(
                    "Could not use operator '{}' with field '{}'".format(
                        op, prop.name
                    )
                )
            q = q.offset(qinfo['page[offset]'])
            q = q.limit(qinfo['page[limit]'])
            return rel_view.collection_return(q, count=count)
        else:
            return rel_view.single_return(q)

    @jsonapi_view
    def relationships_get(self):
        '''Handle GET requests for relationships URLs.

        Get object identifiers for items referred to by a relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            dict: dict in the form:

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
        '''
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

        # Check that the original resource exists. The following will raise an
        # exception for us if it doesn't
        self.get()

        # Set up the query
        q = self.related_query(obj_id, rel, id_only = True)

        if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
            q = rel_view.query_add_sorting(q)
            q = rel_view.query_add_filtering(q)
            qinfo = rel_view.collection_query_info(self.request)
            try:
                count = q.count()
            except sqlalchemy.exc.ProgrammingError as e:
                raise HTTPBadRequest(
                    "Could not use operator '{}' with field '{}'".format(
                        op, prop.name
                    )
                )
            q = q.offset(qinfo['page[offset]'])
            q = q.limit(qinfo['page[limit]'])
            return rel_view.collection_return(
                q,
                count=count,
                identifiers = True
            )
        else:
            return rel_view.single_return(q, identifier = True)

    @jsonapi_view
    def relationships_post(self):
        '''Handle POST requests for TOMANY relationships.

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
            dict: dict in the form:

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

            HTTPConflict: if a resource identifier is specified with a different
            type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Add comments/1 as a comment of posts/1

            .. parsed-literal::

                http POST http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        '''
        DBSession = self.get_dbsession()
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
            raise HTTPNotFound('Cannot POST to TOONE relationship link.')
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        obj = DBSession.query(self.model).get(obj_id)
        items = []
        for resid in self.request.json_body['data']:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(resid['type'], rel_view.collection_name)
                )
            items.append(DBSession.query(rel_class).get(resid['id']))
        getattr(obj, relname).extend(items)
        try:
            DBSession.flush()
        except sqlalchemy.exc.IntegrityError as e:
            raise HTTPFailedDependency(str(e))
        return {}

    @jsonapi_view
    def relationships_patch(self):
        '''Handle PATCH requests for relationships (TOMANY or TOONE).

        Completely replace the raltionship membership.

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
            dict: dict in the form:

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

            HTTPConflict: if a resource identifier is specified with a different
            type than that which the collection holds.

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
        '''
        DBSession = self.get_dbsession()
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
        obj = DBSession.query(self.model).get(obj_id)
        if rel.direction is MANYTOONE:
            resid = self.request.json_body['data']
            if resid is None:
                setattr(obj, relname, None)
            else:
                if resid['type'] != rel_view.collection_name:
                    raise HTTPConflict(
                        "Resource identifier type '{}' does not match relationship type '{}'.".format(resid['type'], rel_view.collection_name)
                    )
                setattr(
                    obj,
                    relname,
                    DBSession.query(rel_class).get(resid['id'])
                )
            return {}
        items = []
        for resid in self.request.json_body['data']:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(resid['type'], rel_view.collection_name)
                )
            items.append(DBSession.query(rel_class).get(resid['id']))
        setattr(obj, relname, items)
        try:
            DBSession.flush()
        except sqlalchemy.exc.IntegrityError as e:
            raise HTTPFailedDependency(str(e))
        return {}

    @jsonapi_view
    def relationships_delete(self):
        '''Handle DELETE requests for TOMANY relationships.

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
            dict: dict in the form:

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

            HTTPConflict: if a resource identifier is specified with a different
            type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Delete comments/1 from posts/1 comments:

            .. parsed-literal::

                http DELETE http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        '''
        DBSession = self.get_dbsession()
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
            raise HTTPNotFound('Cannot DELETE to TOONE relationship link.')
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        obj = DBSession.query(self.model).get(obj_id)
        for resid in self.request.json_body['data']:
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(resid['type'], rel_view.collection_name)
                )
            try:
                getattr(obj, relname).\
                    remove(DBSession.query(rel_class).get(resid['id']))
            except ValueError as e:
                if e.args[0].endswith(': x not in list'):
                    # The item we were asked to remove is not there.
                    pass
                else:
                    raise
        try:
            DBSession.flush()
        except sqlalchemy.exc.IntegrityError as e:
            raise HTTPFailedDependency(str(e))
        return {}

    @property
    def single_item_query(self):
        '''A query representing the single item referenced by the request.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch item with id
            'id'.
        '''
        DBSession = self.get_dbsession()
        q = DBSession.query(
            self.model
        ).options(
            load_only(*self.requested_query_columns.keys())
        ).filter(
            self.model._jsonapi_id == self.request.matchdict['id']
        )
        return q

    def single_return(self, q, not_found_message = None, identifier = False):
        '''Populate return dictionary for a single item.

        Arguments:
            q (sqlalchemy.orm.query.Query): query designed to return one item.

        Keyword Arguments:
            not_found_message (str or None): if an item is not found either:

                * raise 404 with ``not_found_message`` if it is a str;

                * or return ``{"data": None}`` if ``not_found_message`` is None.

            identifier: return identifier if True, object if false.

        Returns:
            dict: dict in the form:

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
        '''
        included = {}
        ret = {}
        try:
            item = q.one()
        except NoResultFound:
            if not_found_message:
                raise HTTPNotFound(not_found_message)
            else:
                return {'data': None}
        if identifier:
            ret['data'] = {
                'type': self.collection_name,
                'id': str(item._jsonapi_id)
            }
        else:
            ret['data'] = self.serialise_db_item(item, included)
            if self.requested_include_names():
                ret['included'] = [obj for obj in included.values()]
        return ret

    def collection_return(self, q, count = None, identifiers = False):
        '''Populate return dictionary for collections.

        Arguments:
            q (sqlalchemy.orm.query.Query): query designed to return multiple items.

        Keyword Arguments:
            count(int): Number of items the query will return (if known).

            identifiers(bool): return identifiers if True, objects if false.

        Returns:
            dict: dict in the form:

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
        '''
        # Get info for query.
        qinfo = self.collection_query_info(self.request)

        # Add information to the return dict
        ret = { 'meta': {'results': {} } }

        if count is None:
            try:
                count = q.count()
            except sqlalchemy.exc.ProgrammingError as e:
                raise HTTPBadRequest(
                    "Could not use operator '{}' with field '{}'".format(
                        op, prop.name
                    )
                )
        ret['meta']['results']['available'] = count

        # Pagination links
        ret['links'] = self.pagination_links(
            count=ret['meta']['results']['available']
        )
        ret['meta']['results']['limit'] = qinfo['page[limit]']
        ret['meta']['results']['offset'] = qinfo['page[offset]']

        # Primary data
        if identifiers:
            ret['data'] = [
                { 'type': self.collection_name, 'id': str(dbitem._jsonapi_id) }
                for dbitem in q.all()
            ]
        else:
            included = {}
            ret['data'] = [
                self.serialise_db_item(dbitem, included)
                for dbitem in q.all()
            ]
            # Included objects
            if self.requested_include_names():
                ret['included'] = [obj for obj in included.values()]

        ret['meta']['results']['returned'] = len(ret['data'])
        return ret

    def query_add_sorting(self, q):
        '''Add sorting to query.

        Use information from the ``sort`` query parameter (via
        :py:func:`collection_query_info`) to contruct an ``order_by`` clause on
        the query.

        See Also:
            ``_sort`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **sort:** comma separated list of sort keys.

        Parameters:
            q (sqlalchemy.orm.query.Query): query

        Returns:
            sqlalchemy.orm.query.Query: query with ``order_by`` clause.
        '''
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
                q = q.join(order_att)
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
                q = q.order_by(order_att)
            else:
                q = q.order_by(order_att.desc())

        return q

    def query_add_filtering(self, q):
        '''Add filtering clauses to query.

        Use information from the ``filter`` query parameter (via
        :py:func:`collection_query_info`) to filter query results.

        Filter parameter structure:

            ``filter[<attribute>:<op>]=<value>``

        where:

            ``attribute`` is an attribute of the queried object type.

            ``op`` is the comparison operator.

            ``value`` is the value the comparison operator should compare to.

        Valid comparison operators:

            * ``eq`` as sqlalchemy ``__eq__``
            * ``ne`` as sqlalchemy ``__ne__``
            * ``startswith`` as sqlalchemy ``startswith``
            * ``endswith`` as sqlalchemy ``endswith``
            * ``contains`` as sqlalchemy ``contains``
            * ``lt`` as sqlalchemy ``__lt__``
            * ``gt`` as sqlalchemy ``__gt__``
            * ``le`` as sqlalchemy ``__le__``
            * ``ge`` as sqlalchemy ``__ge__``
            * ``like`` or ``ilike`` as sqlalchemy ``like`` or ``ilike``, except
              replace any '*' with '%' (so that '*' acts as a wildcard)

        See Also:
            ``_filters`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **filter[<attribute>:<op>]:** filter operation.

        Parameters:
            q (sqlalchemy.orm.query.Query): query

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
        '''
        qinfo = self.collection_query_info(self.request)
        # Filters
        for p, finfo in qinfo['_filters'].items():
            val = finfo['value']
            colspec = finfo['colspec']
            op = finfo['op']
            prop = getattr(self.model, colspec[0])
            if isinstance(prop.property, RelationshipProperty):
                # TODO(Colin): deal with relationships properly.
                pass
            if op == 'eq':
                op_func = getattr(prop, '__eq__')
            elif op == 'ne':
                op_func = getattr(prop, '__ne__')
            elif op == 'startswith':
                op_func = getattr(prop, 'startswith')
            elif op == 'endswith':
                op_func = getattr(prop, 'endswith')
            elif op == 'contains':
                op_func = getattr(prop, 'contains')
            elif op == 'lt':
                op_func = getattr(prop, '__lt__')
            elif op == 'gt':
                op_func = getattr(prop, '__gt__')
            elif op == 'le':
                op_func = getattr(prop, '__le__')
            elif op == 'ge':
                op_func = getattr(prop, '__ge__')
            elif op == 'like' or op == 'ilike':
                op_func = getattr(prop, op)
                val = re.sub(r'\*', '%', val)
            else:
                raise HTTPBadRequest("No such filter operator: '{}'".format(op))
            q = q.filter(op_func(val))

        return q


    def related_limit(self, relationship):
        '''Paging limit for related resources.

        **Query Parameters**

            **page[limit:relationships:<relname>]:** number of results to return
            per page for related resource <relname>.

        Parameters:
            relationship(sqlalchemy.orm.relationships.RelationshipProperty):
                the relationship to get the limit for.

        Returns:
            int: paging limit for related resources.
        '''
        limit_comps = [ 'limit', 'relationships', relationship.key ]
        limit = self.default_limit
        qinfo = self.collection_query_info(self.request)
        while limit_comps:
            if '.'.join(limit_comps) in qinfo['_page']:
                limit = int(qinfo['_page']['.'.join(limit_comps)])
                break
            limit_comps.pop()
        return min(limit, self.max_limit)


    def related_query(self, obj_id, relationship, id_only = False):
        '''Construct query for related objects.

        Parameters:
            obj_id (str): id of an item in this view's collection.

            relationship (sqlalchemy.orm.relationships.RelationshipProperty):
                the relationships to get related objects from.

            id_only (bool): if id_only is ``True``, only query for the key
                column (probably in order to build resource identifiers). If
                id_only is False, query for all requested columns.

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch related
            object(s).
        '''
        DBSession = self.get_dbsession()
        rel = relationship
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        local_col, rem_col = rel.local_remote_pairs[0]
        q = DBSession.query(rel_class)
        if id_only:
            q = q.options(load_only())
        else:
            q = q.options(
                load_only(*rel_view.requested_query_columns.keys())
            )
        if rel.direction is ONETOMANY:
            q = q.filter(obj_id == rem_col)
        elif rel.direction is MANYTOMANY:
            q = q.filter(
                obj_id == rel.primaryjoin.right
            ).filter(
                rel_class._jsonapi_id == rel.secondaryjoin.right
            )
        elif rel.direction is MANYTOONE:
            q = q.filter(
                local_col == rel_class._jsonapi_id
            ).filter(
                self.model._jsonapi_id == obj_id
            )
        else:
            raise HTTPError('Unknown relationships direction, "{}".'.format(
                rel.direction.name
            ))

        return q

    def serialise_db_item(
        self, item,
        included, include_path = None,
        ):
        '''Serialise an individual database item to JSON-API.

        Arguments:
            item: item to serialise.

        Keyword Arguments:
            included (dict): dictionary to be filled with included resource
                objects.
            include_path (list): list tracking current include path for
                recursive calls.

        Returns:
            dict: resource object dictionary.
        '''
        DBSession = self.get_dbsession()
        if include_path is None:
            include_path = []
        model = self.model
        # Required for some introspection.
        mapper = sqlalchemy.inspect(model).mapper
        ispector = self.request.registry.introspector

        # Item's id and type are required at the top level of json-api
        # objects.
        # The item's id.
        item_id = item._jsonapi_id
        # JSON API type.
        type_name = self.collection_name
        item_url = self.request.route_url(
            self.item_route_name,
            **{'id': item._jsonapi_id}
        )

        atts = { key: getattr(item, key)
            for key in self.requested_attributes.keys() }

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
            rel_view = None
            if rel_path_str in self.requested_include_names():
                rel_view = self.view_instance(rel_class)
            local_col, rem_col = rel.local_remote_pairs[0]
            if rel.direction is ONETOMANY\
                or rel.direction is MANYTOMANY:
                qinfo = self.collection_query_info(self.request)
                limit_comps = [ 'limit', 'relationships', key ]
                limit = self.default_limit
                while limit_comps:
                    if '.'.join(limit_comps) in qinfo['_page']:
                        limit = int(qinfo['_page']['.'.join(limit_comps)])
                        break
                    limit_comps.pop()
                limit = min(limit, self.max_limit)
                rel_dict['meta']['results']['limit'] = limit
                if rel_view:
                    q = DBSession.query(
                        rel_class
                    ).options(
                        load_only(*rel_view.requested_query_columns.keys())
                    )
                else:
                    q = DBSession.query(
                        rel_class
                    ).options(load_only())
                if rel.direction is ONETOMANY:
                    q = q.filter(item._jsonapi_id == rem_col)
                else:
                    q = q.filter(
                        item_id == rel.primaryjoin.right
                    ).filter(
                        rel_class._jsonapi_id == rel.secondaryjoin.right
                    )
                rel_dict['meta']['results']['available'] = q.count()
                q = q.limit(limit)
                rel_dict['data'] = []
                for ritem in q.all():
                    rel_dict['data'].append(
                        {
                            'type': rel_class.__tablename__,
                            'id': str(ritem._jsonapi_id)
                        }
                    )
                    if rel_view:
                        included[(rel_view.collection_name, ritem._jsonapi_id)] =\
                            rel_view.serialise_db_item(
                                ritem,
                                included, include_path + [key]
                            )
                rel_dict['meta']['results']['returned'] =\
                    len(rel_dict['data'])
            else:
                if rel_view:
                    q = DBSession.query(
                        rel_class
                    ).options(
                        load_only(*rel_view.requested_query_columns.keys())
                    )
                    q = q.filter(rel_class._jsonapi_id == getattr(item, local_col.name))
                    ritem = None
                    try:
                        ritem = q.one()
                    except sqlalchemy.orm.exc.NoResultFound:
                        rel_dict['data'] = None
                    if ritem:
                        included[(rel_view.collection_name, ritem._jsonapi_id)] =\
                            rel_view.serialise_db_item(
                                ritem,
                                included, include_path + [key]
                            )

                else:
                    rel_id = getattr(item, local_col.name)
                    if rel_id is None:
                        rel_dict['data'] = None
                    else:
                        rel_dict['data'] = {
                            'type': rel_class.__tablename__,
                            'id': str(rel_id)
                        }
            if key in self.requested_relationships:
                rels[key] = rel_dict

        ret = {
            'id': str(item_id),
            'type': type_name,
            'attributes': atts,
            'links': {
                'self': item_url
            },
            'relationships': rels
        }

        return ret

    @classmethod
    @functools.lru_cache(maxsize=128)
    def collection_query_info(cls, request):
        '''Return dictionary of information used during DB query.

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
        '''
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
        for p in request.params.keys():
            match = re.match(r'(.*?)\[(.*?)\]', p)
            if not match:
                continue
            val = request.params.get(p)

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
                colspec, op = match.group(2).split(':')
                colspec = colspec.split('.')
                info['_filters'][p] = {
                    'colspec': colspec,
                    'op': op,
                    'value': val
                }

            # Paging.
            elif match.group(1) == 'page':
                info['_page'][match.group(2)] = val

        return info

    def pagination_links(self, count=0):
        '''Return a dictionary of pagination links.

        Args:
            count (int): total number of results available.

        Returns:
            dict: dictionary of named links.
        '''
        links = {}
        req = self.request
        route_name = req.matched_route.name
        qinfo = self.collection_query_info(req)
        _query = { 'page[{}]'.format(k): v for k,v in qinfo['_page'].items() }
        _query['sort'] = qinfo['sort']
        for f in sorted(qinfo['_filters']):
            _query[f] = qinfo['_filters'][f]['value']

        # First link.
        _query['page[offset]'] = 0
        links['first'] = req.route_url(route_name,_query=_query, **req.matchdict)

        # Next link.
        next_offset = qinfo['page[offset]'] + qinfo['page[limit]']
        if count is None or next_offset < count:
            _query['page[offset]'] = next_offset
            links['next'] = req.route_url(route_name,_query=_query,**req.matchdict)

        # Previous link.
        if qinfo['page[offset]'] > 0:
            prev_offset = qinfo['page[offset]'] - qinfo['page[limit]']
            if prev_offset < 0:
                prev_offset = 0
            _query['page[offset]'] = prev_offset
            links['prev'] = req.route_url(route_name, _query=_query, **req.matchdict)

        # Last link.
        if count is not None:
            _query['page[offset]'] =\
                (max((count - 1),0) // qinfo['page[limit]'])\
                * qinfo['page[limit]']
            links['last'] = req.route_url(route_name,_query=_query, **req.matchdict)
        return links

    @property
    @functools.lru_cache(maxsize=128)
    def requested_field_names(self):
        '''Get the sparse field names from req params for type_name.

        Return None if there was no sparse field param.
        '''
        param = self.request.params.get(
            'fields[{}]'.format(self.collection_name)
        )
        if param is None:
            return self.attributes.keys() | self.relationships.keys()
        if param == '':
            return set()
        return set(param.split(','))

    @property
    def requested_attributes(self):
        '''Return a dictionary of attributes.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields (attributes
            or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <colname>: <column_object>,
                        ...
                    }
        '''
        return { k:v for k,v in self.attributes.items()
            if k in self.requested_field_names}

    @property
    def requested_relationships(self):
        '''Return a dictionary of relationships.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields (attributes
            or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <relname>: <relationship_object>,
                        ...
                    }
        '''
        return { k:v for k,v in self.relationships.items()
            if k in self.requested_field_names}

    @property
    def requested_fields(self):
        '''Union of attributes and relationships.
        '''
        ret = self.requested_attributes
        ret.update(
            self.requested_relationships
        )
        return ret

    @property
    def requested_relationships_local_columns(self):
        '''Finds all the local columns for MANYTOONE relationships.

        Returns:
            dict: local columns indexed by column name.
        '''
        return { pair[0].name: pair[0]
            for rel in self.requested_relationships.values()
                for pair in rel.local_remote_pairs
                    if rel.direction is MANYTOONE
        }

    @property
    def requested_query_columns(self):
        '''All columns required in query to fetch requested fields from db.

        Returns:
            dict: Union of requested_attributes and requested_relationships_local_columns
        '''
        ret = self.requested_attributes
        ret.update(
            self.requested_relationships_local_columns
        )
        return ret

    @functools.lru_cache(maxsize=128)
    def requested_include_names(self):
        '''Parse any 'include' param in http request.

        Returns:
            set: names of all requested includes.

        Default:
            set: names of all direct relationships of self.model.
        '''
        inc = set()
        param = self.request.params.get('include')

        if param is None:
            return inc

        for i in param.split(','):
            curname = []
            for name in i.split('.'):
                curname.append(name)
                inc.add('.'.join(curname))
        return inc

    @property
    def bad_include_paths(self):
        '''Return a set of invalid 'include' parameters.'''
        param = self.request.params.get('include')
        bad = set()
        if param is None:
            return bad
        for i in param.split(','):
            curname = []
            curview = self
            tainted = False
            for name in i.split('.'):
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

    @functools.lru_cache(maxsize=128)
    def view_instance(self, model):
        '''(memoised) get an instance of view class for model.
        '''
        return view_classes[model](self.request)

class DebugView:
    '''Pyramid view class defining a debug API.

    These are available as ``/debug/{action}`` if
    ``jsonapi.debug.debug_endpoints == 'true'``.

    Attributes:
        engine: sqlalchemy engine with connection to the db.
        metadata: sqlalchemy model metadata
        test_data: module with an ``add_to_db()`` method which will populate the
            database
    '''
    def __init__(self, request):
        self.request = request

    def drop(self):
        '''Drop all tables from the database!!!
        '''
        self.metadata.drop_all(self.engine)
        return 'dropped'

    def populate(self):
        '''Create tables and populate with test data.
        '''
        # Create or update tables and schema. Safe if tables already exist.
        self.metadata.create_all(self.engine)
        # Add test data. Safe if test data already exists.
        self.test_data.add_to_db()
        return 'populated'

    def reset(self):
        '''The same as 'drop' and then 'populate'.
        '''
        self.drop()
        self.populate()
        return "reset"

class ModelInfo:
    '''Information about a model class (either table or relationship).

    Use the :meth:`construct` factory method to create one.

    Attributes:
        is_relationship (bool): True if info is for relationship.
        model_class (class): sqlalchemy class which represents the table.
        table_name (str): database table name.
        relationship_name (str): (relationships only) name of relationship.
    '''

    @classmethod
    def construct(cls, model_part):
        '''Construct a ModelInfo instance from a model or relationship class.

        Args:
            model_part (class): model or relationship class.

        Returns:
            ModelInfo: ModelInfo class instance.
        '''
        info = cls()
        if isinstance(model_part, DeclarativeMeta):
            info.is_relationship = False
            info.table_name = sqlalchemy.inspect(model_part).tables[0].name
            info.model_class = model_part
        elif isinstance(model_part, RelationshipProperty):
            info.is_relationship = True
            info.relationship_name = model_part.key
            info.table_name = model_part.parent.tables[0].name
            info.model_class = model_part.parent.class_
        else:
            raise ValueError("Don't know how to deal with model_part class {}".format(model_part.__class__))
        return info
