import json

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

    def item_as_dict(self, item):
        '''Return a dictionary representation of an item from a query.'''
        return {attr: get.as_dict() if hasattr(get, 'as_dict') else get for attr in item.__mapper__.attrs.keys() for get in [getattr(item, attr)]}
