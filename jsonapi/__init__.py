'''Tools for constructing a JSON-API from sqlalchemy models in Pyramid.'''
import json
#from sqlalchemy import inspect
import transaction
import sqlalchemy
from pyramid.view import view_config, notfound_view_config, forbidden_view_config
from pyramid.renderers import JSON
from pyramid.httpexceptions import exception_response, HTTPException, HTTPNotFound, HTTPForbidden, HTTPUnauthorized, HTTPClientError, HTTPBadRequest, HTTPConflict, HTTPUnsupportedMediaType, HTTPNotAcceptable
import pyramid
import sys
import inspect
import re
from collections import namedtuple
import psycopg2
import pprint

from zope.sqlalchemy import ZopeTransactionExtension
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.ext.declarative.api import DeclarativeMeta

DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))
route_prefix = 'jsonapi'

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
    config.add_view(error, context=HTTPClientError, renderer='json')
    # Loop through the models module looking for declaratively defined model
    # classes (inherit DeclarativeMeta). Create resource endpoints for these and
    # any relationships found.
    for k, model_class in models.__dict__.items():
        if isinstance(model_class,
            sqlalchemy.ext.declarative.api.DeclarativeMeta)\
                and hasattr(model_class, 'id'):
            create_resource(config, model_class)
            for relname, rel in sqlalchemy.inspect(model_class).relationships.items():
                create_relationship_resource(config, rel, relname)
create_jsonapi_using_magic_and_pixie_dust = create_jsonapi

def create_resource(config, model, collection_name=None):
    '''Produce a set of resource endpoints.

    Arguments:
        collectiona_name (str): name of collection. Defaults to table name from model.
    '''

    # Figure out what table model is from
    info = ModelInfo.construct(model)

    if collection_name is None:
        collection_name = info.table_name

    view = CollectionViewFactory(model, collection_name)
    config.add_route(view.item_route_name, view.item_route_pattern)
    config.add_view(view, attr='get', request_method='GET',
        route_name=view.item_route_name, renderer='json')
    config.add_route(view.collection_route_name, view.collection_route_pattern)
    config.add_view(view, attr='collection_get', request_method='GET',
        route_name=view.collection_route_name, renderer='json')


def create_relationship_resource(config, model, name):
    pass

def CollectionViewFactory(model, collection_name=None):
    '''Build a class to handle requests for model'''
    if collection_name is None:
        collection_name = model.__tablename__

    class CollectionView:
        '''Implement view methods.'''
        def __init__(self, request):
            self.request = request

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
                    }
                })

                return ret
            return new_f


        @jsonapi_view
        def get(self):
            '''Get a single item.

            Returns:
                single item dictionary.
            '''
            try:
                item = DBSession.query(self.model).filter(self.model.id == self.request.matchdict['id']).one()
            except NoResultFound:
                raise HTTPNotFound('No id {} in collection {}'.format(
                    self.request.matchdict['id'],
                    self.model.__tablename__
                ))
            return {
                'data': self.serialise_db_item(item),
            }

        @jsonapi_view
        def collection_get(self):
            '''Get multiple items from the collection.'''
            # Figure out whether this is a direct model route or a relationship one.
            rc = RouteComponents.from_route(self.request.matched_route.name)
            q = DBSession.query(self.model)

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
                # If order_att is a relationship then we need to add a join to the
                # query and order_by the sort_keys[1] column of the relationship's
                # target. The default target column is 'id'.
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

            ret = {}
            # Full count.
            try:
                ret['meta'] = { 'count': q.count() }
            except sqlalchemy.exc.ProgrammingError as e:
                raise HTTPBadRequest(
                    "Could not use operator '{}' with field '{}'".format(
                        op, prop.name
                    )
                )


            # Paging
            #print("page[limit]: " + str(qinfo['page[limit]']))
            q = q.offset(qinfo['page[offset]']).limit(qinfo['page[limit]'])


            ret['data'] = [
                self.serialise_db_item(
                    dbitem
                )
                for dbitem in q.all()
            ]

            return ret

        def serialise_db_item(self, item):
            '''Serialise an individual database item to JSON-API.

            Args:
                item: item from query to serialise.
                system (dict): information passed by pyramid.
                requested_includes (set): to be included as per request.
                include_path (list):
                included (dict): tracking included items.

            Returns:
                dict: item dictionary.
            '''
            # Required for some introspection.
            mapper = sqlalchemy.inspect(item).mapper

            # Item's id and type are required at the top level of json-api
            # objects.
            # The item's id.
            item_id = getattr(item, 'id')
            # JSON API type.
            type_name = self.collection_name

            atts = {}
            for key, col in mapper.columns.items():
                if key == 'id':
                    continue
                if len(col.foreign_keys) > 0:
                    continue
                atts[key] = getattr(item, key)

            rels = {}

            ret = {
                'id': str(item_id),
                'type': type_name,
                'attributes': atts,
                'links': {
                    'self': self.request.route_url(
                        self.item_route_name,
                        **{'id': getattr(item, 'id')}
                    )
                },
                'relationships': rels
            }

            return ret

        @classmethod
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
            info['_filters'] = {}
            for p in request.params.keys():
                match = re.match(r'filter\[(.*?)\]', p)
                if not match:
                    continue
                val = request.params.get(p)
                colspec, op = match.group(1).split(':')
                colspec = colspec.split('.')
                info['_filters'][p] = {
                    'colspec': colspec,
                    'op': op,
                    'value': val
                }

            return info


    CollectionView.model = model
    CollectionView.collection_name = collection_name
    CollectionView.collection_route_name =\
        ':'.join((route_prefix, collection_name))
    CollectionView.collection_route_pattern = collection_name
    CollectionView.item_route_name =\
        ':'.join((route_prefix, collection_name, 'item'))
    CollectionView.item_route_pattern = collection_name + '/{id}'
    CollectionView.default_limit = 10
    CollectionView.max_limit = 100

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


class RouteComponents(namedtuple('RouteComponents', ('prefix', 'resource', 'relationship'))):
    '''The components of a jsonapi route.

    **Inherits:** :class:`namedtuple`

    pyramid-jsonapi routes are in the form prefix:resource:relationship.

    Attributes:
        prefix (str): route prefix (from jsonapi.route_prefix)
        resource (str): resource collection name.
        relationship (str): relationship_name.

    '''

    @classmethod
    def from_route(cls, route):
        '''Construct an instance by splitting a route string.'''
        comps = route.split(':')
        if len(comps) == 2:
            comps.append(None)
        return cls(*comps)

    @classmethod
    def from_components(cls, resource, relationship=None):
        '''Construct an instance from resource and/or relationship names.'''
        return cls(route_prefix, resource, relationship)

    @classmethod
    def from_request(cls, request):
        '''Construct an instance from a request object.'''
        return cls.from_route(request.matched_route.name)

    @property
    def route(self):
        '''route string evaluated from components.'''
        if self.relationship is None:
            return ':'.join(self[:-1])
        else:
            return ':'.join(self)
