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

from zope.sqlalchemy import ZopeTransactionExtension
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.ext.declarative.api import DeclarativeMeta

DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))
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

def create_jsonapi(config, models):
    '''Auto-create jsonapi from module with sqlAlchemy models.

    Arguments:
        models (module): a module with model classes derived from sqlalchemy.ext.declarative.declarative_base().
    '''
    config.add_notfound_view(error, renderer='json')
    config.add_forbidden_view(error, renderer='json')
    config.add_view(error, context=HTTPError, renderer='json')
    # Loop through the models module looking for declaratively defined model
    # classes (inherit DeclarativeMeta). Create resource endpoints for these and
    # any relationships found.
    for k, model_class in models.__dict__.items():
        if isinstance(model_class,
            sqlalchemy.ext.declarative.api.DeclarativeMeta)\
                and hasattr(model_class, 'id'):
            create_resource(config, model_class)
create_jsonapi_using_magic_and_pixie_dust = create_jsonapi

def create_resource(config, model,
        collection_name = None,
        allowed_fields = None,
    ):
    '''Produce a set of resource endpoints.

    Arguments:
        collectiona_name (str): name of collection. Defaults to table name from model.
    '''

    # Figure out what table model is from
    info = ModelInfo.construct(model)

    if collection_name is None:
        collection_name = info.table_name

    view = CollectionViewFactory(model, collection_name,
        allowed_fields = allowed_fields)
    view_classes['collection_name'] = view
    view_classes[model] = view

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


def CollectionViewFactory(
        model,
        collection_name = None,
        allowed_fields = None
    ):
    '''Build a class to handle requests for model.'''
    if collection_name is None:
        collection_name = model.__tablename__

    class CollectionView:
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
                    raise HTTPUnsupportedMediaType('Media Type parameters not allowed by JSONAPI spec (http://jsonapi.org/format).')
                    params = cth[1].lstrip();

                # Spec says throw 406 Not Acceptable if Accept header has no
                # application/vnd.api+json entry without parameters.
                accepts = re.split(
                    r',\s*',
                    self.request.headers.get('accept','')
                )
                jsonapi_accepts = {a for a in accepts if a.startswith('application/vnd.api')}
                if jsonapi_accepts and 'application/vnd.api+json' not in jsonapi_accepts:
                    raise HTTPNotAcceptable('application/vnd.api+json must appear with no parameters in Accepts header (http://jsonapi.org/format).')

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

                ret['meta'].update({
                    'debug': {
                        'accept_header': {a:None for a in jsonapi_accepts},
                        'qinfo_page': self.collection_query_info(self.request)['_page'],
                        'atts': { k: None for k in self.attributes.keys() },
                        'includes': {k:None for k in self.requested_include_names()}
                    }
                })

                return ret
            return new_f


        @jsonapi_view
        def get(self):
            '''Get a single item.

            Returns:
                dict: single item.
            '''
            q = DBSession.query(
                self.model.id,
                *self.requested_query_columns.values()
            ).filter(
                self.model.id == self.request.matchdict['id']
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
            raise HTTPNotImplemented

        @jsonapi_view
        def delete(self):
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

            # Set up the query
            q = DBSession.query(
                self.model.id,
                *self.requested_query_columns.values()
            )
            q = self.query_add_sorting(q)
            q = self.query_add_filtering(q)
            qinfo = self.collection_query_info(self.request)
            q = q.offset(qinfo['page[offset]']).limit(qinfo['page[limit]'])

            return self.collection_return(q)

        @jsonapi_view
        def collection_post(self):
            '''Create a new object in collection.

            Returns:
                Resource identifier for created item.
            '''
            data = self.request.json_body['data']
            # Check to see if we're allowing client ids
#            if not self.allow_client_id and 'id' in data:
#                raise HTTPForbidden('Client generated ids are not supported.')
            # Type should be correct or raise 409 Conflict
            datatype = data.get('type')
            if datatype != self.collection_name:
                raise HTTPConflict("Unsupported type '{}'".format(datatype))
            atts = data['attributes']
            if 'id' in data:
                atts['id'] = data['id']
            item = self.model(**atts)
            mapper = sqlalchemy.inspect(self.model).mapper
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
                if rel.direction is sqlalchemy.orm.interfaces.ONETOMANY:
                    setattr(item, relname, [
                        DBSession.query(rel_class).get(rel_identifier['id'])
                            for rel_identifier in reldata
                    ])
                else:
                    setattr(item, relname,
                        DBSession.query(rel_class).get(reldata['id']))
            try:
                DBSession.add(item)
                DBSession.flush()
            except sqlalchemy.exc.IntegrityError as e:
                raise HTTPConflict(e.args[0])
            self.request.response.status_code = 201
            return {'data': { 'type': self.collection_name, 'id': item.id } }

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
            q = rel_view.query_add_sorting(q)
            q = rel_view.query_add_filtering(q)
            qinfo = rel_view.collection_query_info(self.request)
            q = q.offset(qinfo['page[offset]']).limit(qinfo['page[limit]'])

            if rel.direction is sqlalchemy.orm.interfaces.ONETOMANY:
                return rel_view.collection_return(q)
            else:
                return rel_view.single_return(
                    q,
                    'No id {} in collection {} relationship {}'.format(
                        obj_id,
                        self.collection_name,
                        relname
                    )
                )

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

            # Set up the query
            q = self.related_query(obj_id, rel, id_only = True)
            q = rel_view.query_add_sorting(q)
            q = rel_view.query_add_filtering(q)
            qinfo = rel_view.collection_query_info(self.request)
            q = q.offset(qinfo['page[offset]']).limit(qinfo['page[limit]'])

            if rel.direction is sqlalchemy.orm.interfaces.ONETOMANY:
                return rel_view.collection_return(q, identifiers = True)
            else:
                return rel_view.single_return(
                    q,
                    'No id {} in collection {} relationship {}'.format(
                        obj_id,
                        self.collection_name,
                        relname
                    ),
                    identifier = True
                )

        @jsonapi_view
        def relationships_post(self):
            raise HTTPNotImplemented

        @jsonapi_view
        def relationships_patch(self):
            raise HTTPNotImplemented

        @jsonapi_view
        def relationships_delete(self):
            raise HTTPNotImplemented

        def single_return(self, q, not_found_message, identifier = False):
            '''Populate return dictionary for single items.
            '''
            included = {}
            ret = {}
            try:
                item = q.one()
            except NoResultFound:
                raise HTTPNotFound(not_found_message)
            if identifier:
                ret['data'] = { 'type': self.collection_name, 'id': item.id }
            else:
                ret['data'] = self.serialise_db_item(item, included)
                if self.requested_include_names():
                    ret['included'] = [obj for obj in included.values()]
            return ret

        def collection_return(self, q, identifiers = False):
            '''Populate return dictionary for collections.
            '''
            # Get info for query.
            qinfo = self.collection_query_info(self.request)

            # Add information to the return dict
            ret = { 'meta': {'results': {} } }

            # Full count.
            try:
                ret['meta']['results']['available'] = q.count()
            except sqlalchemy.exc.ProgrammingError as e:
                raise HTTPBadRequest(
                    "Could not use operator '{}' with field '{}'".format(
                        op, prop.name
                    )
                )

            # Pagination links
            ret['links'] = self.pagination_links(
                count=ret['meta']['results']['available']
            )
            ret['meta']['results']['limit'] = qinfo['page[limit]']
            ret['meta']['results']['offset'] = qinfo['page[offset]']

            # Primary data
            if identifiers:
                ret['data'] = [
                    { 'type': self.collection_name, 'id': dbitem.id }
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
            sort_keys = qinfo['_sort']['key'].split('.')
            order_att = getattr(self.model, sort_keys[0])
            # order_att will be a sqlalchemy.orm.properties.ColumnProperty if
            # sort_keys[0] is the name of an attribute or a
            # sqlalchemy.orm.relationships.RelationshipProperty if sort_keys[0]
            # is the name of a relationship.
            if isinstance(order_att.property, RelationshipProperty):
                # If order_att is a relationship then we need to add a join to
                # the query and order_by the sort_keys[1] column of the
                # relationship's target. The default target column is 'id'.
                q = q.join(order_att)
                try:
                    sub_key = sort_keys[1]
                except IndexError:
                    sub_key = 'id'
                order_att = getattr(order_att.property.mapper.entity, sub_key)
            if qinfo['_sort']['ascending']:
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
            rel = relationship
            rel_class = rel.mapper.class_
            rel_view = self.view_instance(rel_class)
            local_col, rem_col = rel.local_remote_pairs[0]
            if id_only:
                q = DBSession.query(rel_class.id)
            else:
                q = DBSession.query(
                    rel_class.id,
                    *rel_view.requested_query_columns.values()
                )
            if rel.direction is sqlalchemy.orm.interfaces.ONETOMANY:
                q = q.filter(obj_id == rem_col)
            else:
                q = q.filter(rel_class.id == local_col)
                q = q.filter(self.model.id == obj_id)

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
            if include_path is None:
                include_path = []
            model = self.model
            # Required for some introspection.
            mapper = sqlalchemy.inspect(model).mapper
            ispector = self.request.registry.introspector

            # Item's id and type are required at the top level of json-api
            # objects.
            # The item's id.
            item_id = getattr(item, 'id')
            # JSON API type.
            type_name = self.collection_name
            item_url = self.request.route_url(
                self.item_route_name,
                **{'id': getattr(item, 'id')}
            )

            atts = { key: getattr(item, key)
                for key in self.requested_attributes.keys() }

            rels = {}
            for key, rel in self.requested_relationships.items():
                rel_path_str = '.'.join(include_path + [key])
                rels[key] = {
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
                print('rel_path_str: ' + rel_path_str)
                if rel_path_str in self.requested_include_names():
                    rel_view = self.view_instance(rel_class)
                local_col, rem_col = rel.local_remote_pairs[0]
                if rel.direction is sqlalchemy.orm.interfaces.ONETOMANY:
                    qinfo = self.collection_query_info(self.request)
                    limit_comps = [ 'limit', 'relationships', key ]
                    limit = self.default_limit
                    while limit_comps:
                        if '.'.join(limit_comps) in qinfo['_page']:
                            limit = int(qinfo['_page']['.'.join(limit_comps)])
                            break
                        limit_comps.pop()
                    limit = min(limit, self.max_limit)
                    rels[key]['meta']['results']['limit'] = limit
                    if rel_view:
                        q = DBSession.query(
                            rel_class.id,
                            *rel_view.requested_query_columns.values()
                        )
                    else:
                        q = DBSession.query(rel_class.id)
                    q = q.filter(item.id == rem_col)
                    rels[key]['meta']['results']['available'] = q.count()
                    q = q.limit(limit)
                    rels[key]['data'] = []
                    for ritem in q.all():
                        rels[key]['data'].append(
                            {'type': key, 'id': str(ritem.id)}
                        )
                        if rel_view:
                            included[(rel_view.collection_name, ritem.id)] =\
                                rel_view.serialise_db_item(
                                    ritem,
                                    included, include_path + [key]
                                )
                    rels[key]['meta']['results']['returned'] =\
                        len(rels[key]['data'])
                else:
                    if rel_view:
                        q = DBSession.query(
                            rel_class.id,
                            *rel_view.requested_query_columns.values()
                        )
                        q = q.filter(rel_class.id == getattr(item, local_col.name))
                        ritem = None
                        try:
                            ritem = q.one()
                        except sqlalchemy.orm.exc.NoResultFound:
                            rels[key]['data'] = None
                        if ritem:
                            included[(rel_view.collection_name, ritem.id)] =\
                                rel_view.serialise_db_item(
                                    ritem,
                                    included, include_path + [key]
                                )

                    else:
                        rels[key]['data'] = {
                            'type': key,
                            'id': str(getattr(item, local_col.name))
                        }

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
                        '_sort': {
                            'key': sort key ('field' or 'relationship.field'),
                            'ascending': sort ascending or descending (bool)
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
            sort_key = request.params.get('sort', 'id')
            info['sort'] = sort_key
            # Break sort param down into components and store in _sort.
            info['_sort'] = {}
            # Check to see if it starts with '-', which indicates a reverse sort.
            ascending = True
            if sort_key.startswith('-'):
                ascending = False
                sort_key = sort_key[1:]
            info['_sort']['key'] = sort_key
            info['_sort']['ascending'] = ascending



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
            if next_offset < count:
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
            _query['page[offset]'] = ((count - 1) // qinfo['page[limit]']) * qinfo['page[limit]']
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
                        if rel.direction is sqlalchemy.orm.interfaces.MANYTOONE
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

        @functools.lru_cache(maxsize=128)
        def view_instance(self, model):
            '''(memoised) get an instance of view class for model.
            '''
            return view_classes[model](self.request)

#        def related_route_name(self, relationship_name):
#            return self.collection_route_name + ':related:' + relationship_name

#        def relationship_route_name(self, relationship_name):
#            return self.collection_route_name +\
#                ':relationships:' + relationship_name

    CollectionView.model = model
    CollectionView.collection_name = collection_name

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

    CollectionView.default_limit = 10
    CollectionView.max_limit = 100
    CollectionView.class_allowed_fields = allowed_fields
    atts = {}
    for key, col in sqlalchemy.inspect(model).mapper.columns.items():
        if key == 'id':
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
