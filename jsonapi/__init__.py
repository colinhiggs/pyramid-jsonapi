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

class DebugView:
    '''Some API operations available if jsonapi.debug.debug_endpoints == 'true'.
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

def create_jsonapi(config, models, get_dbsession,
    engine = None, test_data = None):
    '''Auto-create jsonapi from module with sqlAlchemy models.

    Arguments:
        models (iterable): an iterable (or module) of model classes derived from DeclarativeMeta.
    '''

    config.add_notfound_view(error, renderer='json')
    config.add_forbidden_view(error, renderer='json')
    config.add_view(error, context=HTTPError, renderer='json')

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

    # Loop through the models module looking for declaratively defined model
    # classes (inherit DeclarativeMeta). Create resource endpoints for these and
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
        collectiona_name (str): name of collection. Defaults to table name from model.
        allowed_fields (set): set of allowed field names.
    '''

    try:
        keycols = sqlalchemy.inspect(model).primary_key
    except sqlalchemy.exc.NoInspectionAvailable:
        # Trying to inspect the declarative_base() raises this exception. We
        # don't want to add it to the API.
        return

    # Only deal with one primary key column.
    if len(keycols) > 1:
        raise Exception(
            'Model {} has more than one primary key.'.format(model_class.__name__)
        )
    model._jsonapi_id = getattr(model, keycols[0].name)

    # Figure out what table model is from
    info = ModelInfo.construct(model)

    if collection_name is None:
        collection_name = info.table_name

    view = CollectionViewFactory(model, get_dbsession, collection_name,
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

class CollectionViewBase:
    '''Implement view methods.'''
    def __init__(self, request):
        self.request = request
        self.views = {}

    def jsonapi_view(f):
        '''Decorator for view functions. Adds jsonapi boilerplate.'''
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

            if self.bad_include_paths:
                raise HTTPBadRequest(
                    "Bad include paths {}".format(
                        self.bad_include_paths
                    )
                )

            # Spec says set Content-Type to application/vnd.api+json.
            self.request.response.content_type = 'application/vnd.api+json'

            ret = {
                'links': {},
                'meta': {}
            }

            ret.update(f(self, *args))

            ret['links'].update({
                'self': self.request.url
            })

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
        '''Get a single item.

        Returns:
            dict: single item.
        '''
        DBSession = self.get_dbsession()
        q = DBSession.query(
            self.model
        ).options(
            load_only(*self.requested_query_columns.keys())
        ).filter(
            self.model._jsonapi_id == self.request.matchdict['id']
        )

        return self.single_return(
            q,
            'No id {} in collection {}'.format(
                self.request.matchdict['id'],
                self.collection_name
            )
        )

    @jsonapi_view
    def patch(self):
        '''Update an existing item from a partially defined representation.
        '''
        DBSession = self.get_dbsession()
        data = self.request.json_body['data']
        req_id = self.request.matchdict['id']
        data_id = data.get('id')
        if data_id is not None and data_id != req_id:
            raise HTTPConflict('JSON id ({}) does not match URL id ({}).'.
            format(data_id, req_id))
        atts = data['attributes']
        atts[self.key_column.name] = req_id
        # TODO(Colin): deal with relationships
        item = DBSession.merge(self.model(**atts))
        DBSession.flush()
        return self.serialise_db_item(item, {})

    @jsonapi_view
    def delete(self):
        '''Delete an item.

        Returns:
            dict: resource identifier for deleted object.
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
        '''Get multiple items from the collection.

        Returns:
            list: list of items.
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
        '''Create a new object in collection.

        Returns:
            Resource identifier for created item.
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
        return {
            'data': {
                'type': self.collection_name,
                'id': str(item._jsonapi_id)
            }
        }

    @jsonapi_view
    def related_get(self):
        '''GET object(s) related to a specified object.
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

        if rel.direction is ONETOMANY:
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
        '''GET resource identifiers for members in a relationship.
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

        if rel.direction is ONETOMANY:
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
        '''Add new items to a relationship collection.
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
        '''Replace relationship collection.
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
            if resid['type'] != rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(resid['type'], rel_view.collection_name)
                )
            if resid is None:
                setattr(obj, relname, None)
            else:
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
        '''Delete items from relationship collection.
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
            getattr(obj, relname).\
                remove(DBSession.query(rel_class).get(resid['id']))
        try:
            DBSession.flush()
        except sqlalchemy.exc.IntegrityError as e:
            raise HTTPFailedDependency(str(e))
        return {}

    def single_return(self, q, not_found_message = None, identifier = False):
        '''Populate return dictionary for single items.
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
            ret['data'] = { 'type': self.collection_name, 'id': item._jsonapi_id }
        else:
            ret['data'] = self.serialise_db_item(item, included)
            if self.requested_include_names():
                ret['included'] = [obj for obj in included.values()]
        return ret

    def collection_return(self, q, count = None, identifiers = False):
        '''Populate return dictionary for collections.
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
                { 'type': self.collection_name, 'id': dbitem._jsonapi_id }
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
        else:
            q = q.filter(rel_class._jsonapi_id == local_col)
            q = q.filter(self.model._jsonapi_id == obj_id)

        return q

    def serialise_db_item(
        self, item,
        included, include_path = None,
        ):
        '''Serialise an individual database item to JSON-API.

        Args:
            item: item from query to serialise.
            requested_includes (set): to be included as per request.
            include_path (list):
            included (dict): tracking included items.

        Returns:
            dict: item dictionary.
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
                    q = q.filter(rel_class._jsonapi_id == rel.secondaryjoin.right)
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

    @functools.lru_cache(maxsize=128)
    def requested_field_names(self, request):
        '''Get the sparse field names as a set from req params for type_name.

        Return None if there was no sparse field param.
        '''
        param = request.params.get(
            'fields[{}]'.format(self.collection_name)
        )
        if param is None:
            return self.attributes.keys() | self.relationships.keys()
        if param == '':
            return set()
        return set(param.split(','))

    @property
    def requested_attributes(self):
        '''Return a dictionary of attributes: {colname: column}.
        '''
        return { k:v for k,v in self.attributes.items()
            if k in self.requested_field_names(self.request)}

    @property
    def requested_relationships(self):
        '''Return a dictionary of relationships: {relname: rel}.
        '''
        return { k:v for k,v in self.relationships.items()
            if k in self.requested_field_names(self.request)}

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



def CollectionViewFactory(
        model,
        get_dbsession,
        collection_name = None,
        allowed_fields = None
    ):
    '''Build a class to handle requests for model.'''
    if collection_name is None:
        collection_name = model.__tablename__


#        def related_route_name(self, relationship_name):
#            return self.collection_route_name + ':related:' + relationship_name

#        def relationship_route_name(self, relationship_name):
#            return self.collection_route_name +\
#                ':relationships:' + relationship_name

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
