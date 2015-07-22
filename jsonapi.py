import json
from sqlalchemy import inspect
from pprint import pprint

def get_query_fields(request, type_name):
    '''Get the sparse field names as a set from req params for type_name.

    Return None if there was no sparse field param.
    '''
    param = request.params.get('fields[{}]'.format(type_name))
    if param is None:
        return None
    return set(param.split(','))


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
        self.options.setdefault('nest',1)
        pprint(options)

    def __call__(self, info):
        '''Hook called by pyramid to invoke renderer.'''
        def _render(value, system):
            req = system['request']
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
            if isinstance(results, list):
                data = [
                    self.serialise_db_item(
                        dbitem, system,
                        options = view_options,
                        nests_remaining = view_options.get(
                            'nest', self.options.get('nest', 0)
                        )
                    )
                    for dbitem in results
                ]
            else:
                data = self.serialise_db_item(
                    results, system,
                    options = view_options,
                    nests_remaining = view_options.get(
                        'nest', self.options.get('nest', 0)
                    )
                )
            ret = {
                'data': data,
                'links': {
                    'self': req.route_url(req.matched_route.name, **req.matchdict)
                }
            }
            return json.dumps(ret)
        return _render

    def resource_link(self, item, system):
        return system['request'].route_url(
            item.__class__.__name__.lower() + 'resource',
            **{'id': getattr(item, 'id')}
        )

    def serialise_db_item(self, item, system, options = None, nests_remaining=0):
        '''Serialise an individual database item to JSON-API.


        '''
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

        # JSON API type
        type_name = item.__tablename__

        # fields string to look for in params for sparse fieldsets
        fields_str = 'fields[{}]'.format(type_name)
        # Start by allowing all fields.
        allowed_fields = {c for c in mapper.columns.keys()}
        # Intersect with fields allowed by options (from model or view).
        if fields_str in opts:
            allowed_fields = allowed_fields & opts[fields_str]
        # Intersect with fields asked for in query string.
        query_fields = get_query_fields(system['request'], type_name)
        if query_fields:
            allowed_fields = allowed_fields & query_fields

        atts = {
            colname: getattr(item, colname)
            for colname in mapper.columns.keys()
            if colname in allowed_fields
        }
        item_id = getattr(item, 'id')
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

        # Don't nest any further.
        #if nests_remaining == 0:
        #    return ret

        # At least one more nesting level: check for relationships and add.
        relationships = {}
        for relname, rel in mapper.relationships.items():
            thing = getattr(item, relname)
            # thing can be a single item or a list of them.
            if isinstance(thing, list):
                if nests_remaining == 0:
                    relationships[relname] = [
                        self.resource_link(subitem, system) for subitem in thing
                    ]
                else:
                    relationships[relname] = [
                        self.serialise_db_item(
                            subitem, system,
                            options=opts, nests_remaining=nests_remaining - 1
                        )
                            for subitem in thing
                    ]
            else:
                if nests_remaining == 0:
                    relationships[relname] = self.resource_link(thing, system)
                else:
                    relationships[relname] = self.serialise_db_item(
                        thing, system, options=opts,
                        nests_remaining=nests_remaining - 1
                    )
        if relationships:
            ret['relationships'] = relationships

        return ret
