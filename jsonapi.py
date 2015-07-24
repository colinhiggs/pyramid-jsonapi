import json
from sqlalchemy import inspect
from pprint import pprint

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
        #self.info = info
        self.options = options
        #pprint(options)

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
            if isinstance(results, list):
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
        return system['request'].route_url(
            item.__class__.__name__.lower() + 'resource',
            **{'id': getattr(item, 'id')}
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
        mapper = inspect(item).mapper

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
                        '/relationships/' + relname
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
                                include_path=include_path,
                                requested_includes=requested_includes,
                                included=included,
                                options=options
                            )
                        )

            else:
                relationships[relname] = {
                    'links': {
                        'self': self.resource_link(item,system) +
                        '/relationships/' + relname
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
                            include_path=include_path,
                            requested_includes=requested_includes,
                            included=included,
                            options=options
                        )
                    )

        if relationships:
            ret['relationships'] = relationships

        return ret
