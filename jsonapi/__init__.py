import json
#from sqlalchemy import inspect
import transaction
import sqlalchemy
from pyramid.view import view_config
import cornice.resource
import sys
import inspect
import re

from zope.sqlalchemy import ZopeTransactionExtension
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty

DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))

class Resource:
    '''Base class for all REST resources'''
    def __init__(self, request):
        self.request = request

    def collection_get(self):
        '''Get items from the collection.'''
        # Paging by limit and offset.
        # Use params 'page[limit]' and 'page[offset]' to comply with spec.
        limit = min(
            self.max_limit,
            int(self.request.params.get('page[limit]', self.default_limit))
        )
        offset = int(self.request.params.get('page[offset]', 0))

        # Start building the query.
        q = DBSession.query(self.model)

        # Sorting.
        # Use param 'sort' as per spec.
        # Split on '.' to allow sorting on columns of relationship tables:
        #   sort=name -> sort on the 'name' column.
        #   sort=owner.name -> sort on the 'name' column of the target table
        #     of the relationship 'owner'.
        # The default sort column is 'id'.
        sort_key = self.request.params.get('sort', 'id').split('.')
        order = getattr(self.model, sort_key[0])
        # order will be a sqlalchemy.orm.properties.ColumnProperty if
        # sort_key[0] is the name of an attribute or a
        # sqlalchemy.orm.relationships.RelationshipProperty if sort_key[0]
        # is the name of a relationship.
        if isinstance(order.property, RelationshipProperty):
            # If order is a relationship then we need to add a join to the query
            # and order_by the sort_key[1] column of the relationship's target.
            # The default target column is 'id'.
            q = q.join(order)
            try:
                sub_key = sort_key[1]
            except IndexError:
                sub_key = 'id'
            order = getattr(order.property.mapper.entity, sub_key)

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
        for p in self.request.params.keys():
            match = re.match(r'filter\[(.*?)\]', p)
            if not match:
                continue
            colspec, op = match.group(1).split(':')
            colspec = colspec.split('.')
#        return None

        return q.order_by(order).\
            offset(offset).limit(limit).\
            all()

    def get(self):
        '''Get a single item.'''
        try:
            item = DBSession.query(self.model).filter(self.model.id == self.request.matchdict['id']).one()
        except NoResultFound:
            raise ResourceNotFoundError('No such {} item: {}.'.format(self.model.__tablename__, self.request.matchdict['id']))
        return item

    def collection_post(self):
        '''Create a new item.'''
        data = self.request.json_body
        atts = data['attributes']
        # Delete id key to force creation of a new item
        try:
            del(atts['id'])
        except KeyError:
            pass
        item = DBSession.merge(self.model(**atts))
        DBSession.flush()
        return item

    def patch(self):
        '''Update an existing item.'''
        data = self.request.json_body
        req_id = self.request.matchdict['id']
        data_id = data.get('id')
        if data_id is not None and data_id != req_id:
            raise KeyError('JSON id ({}) does not match URL id ({}).'.
            format(data_id, req_id))
        data['id'] = req_id
        item = DBSession.merge(self.model(**data))
        DBSession.flush()
        return item

def create_jsonapi(models, module=None):
    '''Auto-create jsonapi from module with sqlAlchemy models.'''
    if module is None:
    # Add resource classes to the caller's module.
        parentframe = inspect.stack()[1][0]
        try:
            module = inspect.getmodule(parentframe)
        finally:
            # Memory leak (or delayed free) if parentframe is not
            # deleted.
            del parentframe

    # Adding the new classes to another module doesn't work for some reason.
    # Stick to our own for now.
    module = sys.modules[__name__]
    print('module: {}'.format(module))
    for k,v in models.__dict__.items():
        if isinstance(v, sqlalchemy.ext.declarative.api.DeclarativeMeta) and hasattr(v, 'id'):
            print('{}: {}'.format(k, v.__class__.__name__))
            setattr(module, k + 'Resource', create_resource(v, v.__tablename__, bases=(Resource,), module=module))
create_jsonapi_using_magic_and_pixie_dust = create_jsonapi

def resource(model, name, **options):
    '''Class decorator: produce a set of resource endpoints from an appropriate class.'''
    model.__jsonapi_route_name__ = name
    def wrap(cls):
        # Depth has something to do with venusian detecting and creating routes.
        # Needs to be bumped up by one each time a function/class is wrapped.
        return create_resource(model, name, cls=cls, depth=3, **options)
    return wrap

def create_resource(model, name, cls=None, bases=(Resource,), depth=2, module=None, **options):
    '''Produce a set of resource endpoints.'''
    my_opts = {'default_limit': 10, 'max_limit': 100}
    try:
        my_opts.update(model.__jsonapi_options__)
    except AttributeError:
        pass
    my_opts.update(options)
    model.__jsonapi_route_name__ = name
    if cls is None:
        cls = type(
            '{}Resource'.format(model.__name__),
            bases,
            {'model': model, 'route_name': name}
        )
    cls.model = model
    cls.route_name = name
    cls.default_limit = my_opts['default_limit']
    cls.max_limit = my_opts['max_limit']
    setattr(module, cls.__name__, cls)
    # See the comment in resource about depth.
    return cornice.resource.resource(name=name, collection_path=name, path='{}/{{id}}'.format(name), depth=depth, renderer='jsonapi')(cls)

def requested_fields(request, type_name):
    '''Get the sparse field names as a set from req params for type_name.

    Return None if there was no sparse field param.
    '''
    param = request.params.get('fields[{}]'.format(type_name))
    if param is None:
        return None
    return set(param.split(','))

def requested_includes(request):
    '''Parse any 'include' param in request.'''
    param = request.params.get('include', '')
    inc = set()
    for i in param.split(','):
        curname = []
        for name in i.split('.'):
            curname.append(name)
            inc.add('.'.join(curname))
    return inc

class JSONAPIFromSqlAlchemyRenderer:
    '''Pyramid renderer: to JSON-API from SqlAlchemy.

    Pass in as the renderer to a view and return the results of a sqlalchemy
    query from the view. The renderer will produce a correct JSON-API response.

    In __init__.py:
    from jsonapi import JSONAPIFromSqlAlchemyRenderer
    ...
    config.add_renderer('jsonapi', JSONAPIFromSqlAlchemyRenderer)

    In views.py:
    @view(renderer='jsonapi')
    def some_view(request):
        # return a collection
        return DBSession.query(some_model).all()
        # or an individual item
        return DBSession.query(some_model).filter(some_model.id == request.matchdict['id']).one()
    '''

    def __init__(self, **options):
        self.options = options

    def __call__(self, info):
        '''Hook called by pyramid to invoke renderer.'''
        def _render(value, system):
            req = system['request']
            inc = requested_includes(req)

            #intro = req.registry.introspector
            #print(intro.get_category('routes'))
            req.response.content_type = 'application/vnd.api+json'
            view_options = {}
            if isinstance(value, dict):
                results = value['results']
                del(value['results'])
                view_options.update(value)
            else:
                results = value
            included = {}
            if results is None:
                data = None
            elif isinstance(results, list):
                data = [
                    self.serialise_db_item(
                        dbitem, system,
                        options = view_options,
                        requested_includes = inc,
                        included = included
                    )
                    for dbitem in results
                ]
            else:
                data = self.serialise_db_item(
                    results, system,
                    options = view_options,
                    requested_includes = inc,
                    included = included
                )
            ret = {
                'data': data,
                'links': {
                    'self': req.route_url(req.matched_route.name, **req.matchdict)
                }
            }
            if included:
                ret['included'] = [v for v in included.values()]
            return json.dumps(ret)
        return _render

    def resource_link(self, item, system):
        '''Return a link to the resource represented by item.'''
        return system['request'].route_url(
            item.__jsonapi_route_name__,
            **{'id': getattr(item, 'id')}
        )

    def collection_link(self, item, system):
        '''Return a link to the collection item is from.'''
        return system['request'].route_url(
            'collection_' + item.__jsonapi_route_name__, **{}
        )

    def serialise_db_item(self, item, system,
        requested_includes=None, include_path=None, included=None,
        options=None):
        '''Serialise an individual database item to JSON-API.


        '''
        if requested_includes is None:
            requested_includes = set()
        if include_path is None:
            include_path = []
        if included is None:
            included = {}
        # options affect how data is rendered. Get defaults from self.
        opts = {}
        opts.update(self.options)
        # Next update with options from the model.
        try:
            opts.update(item.__jsonapi_options__)
        except AttributeError:
            pass
        # Lastly update with options passed as args (from the view).
        if options is None:
            options = {}
        opts.update(options)

        # Required for some introspection.
        mapper = sqlalchemy.inspect(item).mapper

        # Item's id and type are required at the top level of json-api objects.
        # The item's id.
        item_id = getattr(item, 'id')
        # JSON API type.
        type_name = item.__tablename__

        # fields string to look for in params for sparse fieldsets
        fields_str = 'fields[{}]'.format(type_name)
        # Start by allowing all fields.
        allowed_fields = {c for c in mapper.columns.keys()}
        # Intersect with fields allowed by options (from model or view).
        if fields_str in opts:
            allowed_fields = allowed_fields & opts[fields_str]
        # Intersect with fields asked for in query string.
        query_fields = requested_fields(system['request'], type_name)
        if query_fields:
            allowed_fields = allowed_fields & query_fields

        # Build a dictionary of attributes.
        atts = {
            colname: getattr(item, colname)
            for colname in mapper.columns.keys()
            if colname in allowed_fields
        }
        # make sure that 'id' doesn't end up in attributes
        try:
            del(atts['id'])
        except KeyError:
            pass

        ret = {
            'id': str(item_id),
            'type': type_name,
            'attributes': atts,
            'links': {
                'self': self.resource_link(item, system)
            }
        }

        # Add relationships
        relationships = {}
        for relname, rel in mapper.relationships.items():
            thing = getattr(item, relname)
            rel_path = include_path + [relname]
            rel_str = '.'.join(rel_path)
            # thing can be a single item or a list of them.
            if isinstance(thing, list):
                relationships[relname] = {
                    'links': {
                        'self': self.resource_link(item,system) +
                        '/relationships/' + relname,
                    }
                }
                relationships[relname]['data'] = []
                for subitem in thing:
                    relationships[relname]['data'].append(
                        {
                            'type': subitem.__tablename__,
                            'id': getattr(subitem, 'id')
                        }
                    )
                    if rel_str in requested_includes:
                        included.setdefault(
                            (subitem.__tablename__, getattr(subitem, 'id')),
                            self.serialise_db_item(
                                subitem,system,
                                include_path=rel_path,
                                requested_includes=requested_includes,
                                included=included,
                                options=options
                            )
                        )

            else:
                relationships[relname] = {
                    'links': {
                        'self': self.resource_link(item,system) +
                        '/relationships/' + relname,
                    },
                    'data': {
                        'type': thing.__tablename__,
                        'id': getattr(thing, 'id')
                    }
                }
                if rel_str in requested_includes:
                    included.setdefault(
                        (thing.__tablename__, getattr(thing, 'id')),
                        self.serialise_db_item(
                            thing,system,
                            include_path=rel_path,
                            requested_includes=requested_includes,
                            included=included,
                            options=options
                        )
                    )

        if relationships:
            ret['relationships'] = relationships

        return ret
