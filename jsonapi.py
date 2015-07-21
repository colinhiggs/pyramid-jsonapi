import json
from sqlalchemy import inspect

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

    def __init__(self, info):
        self.info = info

    def __call__(self, value, system):
        '''Hook called by pyramid to invoke renderer.'''
        req = system['request']
        req.response.content_type = 'application/vnd.api+json'
        if isinstance(value, list):
            data = [self.serialise_db_item(dbitem, system) for dbitem in value]
        else:
            data = self.serialise_db_item(value, system)
        #matchdict = req.matchdict
        ret = {
            'data': data,
            'links': {
                'self': req.route_url(req.matched_route.name, **req.matchdict)
            }
        }
        return json.dumps(ret)

    def serialise_db_item(self, item, system):
        '''Serialise an individual database item to JSON-API.'''
        itemdict = self.item_as_dict(item)
        ret = {
            'id': str(itemdict['id']),
            'type': item.__tablename__,
            'attributes': itemdict,
            'links': {
                'self': system['request'].route_url(
                    item.__class__.__name__.lower() + 'resource',
                    **{'id': itemdict['id']}
                )
            }
        }
        del(itemdict['id'])
        return ret

    def item_as_dict(self, item, nest_level=1):
        '''Return a dictionary representation of an item from a query.'''
        data = {}
        state = inspect(item)
        mapper = state.mapper
        # Basic data.
        for colname in mapper.columns.keys():
            data[colname] = getattr(item, colname)

        # No more nesting.
        if nest_level == 0:
            return data

        # Nested data from relationships.
        for name, rel in mapper.relationships.items():
            print(repr(name),repr(rel))
            subitem = getattr(item, name)
            if isinstance(subitem, list):
                data[name] = []
                for thing in subitem:
                    data[name].append(self.item_as_dict(thing, nest_level=nest_level-1))
            else:
                data[name] = self.item_as_dict(subitem, nest_level=nest_level - 1)
        return data
