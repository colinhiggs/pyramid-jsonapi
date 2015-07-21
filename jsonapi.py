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

    def serialise_db_item(self, item, system, nest_level=1):
        '''Serialise an individual database item to JSON-API.'''
        mapper = inspect(item).mapper
        atts = {
            colname: getattr(item, colname)
            for colname in mapper.columns.keys()
        }
        item_id = atts['id']
        del(atts['id'])

        ret = {
            'id': str(item_id),
            'type': item.__tablename__,
            'attributes': atts,
            'links': {
                'self': system['request'].route_url(
                    item.__class__.__name__.lower() + 'resource',
                    **{'id': item_id}
                )
            }
        }

        # Don't nest any further.
        if nest_level == 0:
            return ret

        # At least one more nesting level: check for relationships and add.
        relationships = {}
        for relname, rel in mapper.relationships.items():
            thing = getattr(item, relname)
            # thing can be a single item or a list of them.
            if isinstance(thing, list):
                relationships[relname] = [
                    self.serialise_db_item(subitem, system, nest_level - 1)
                        for subitem in thing
                ]
            else:
                relationships[relname] = self.serialise_db_item(thing, system, nest_level - 1)
        if relationships:
            ret['relationships'] = relationships

        return ret
