'''Tools for constructing a JSON-API from sqlalchemy models in Pyramid.'''
import json
#from sqlalchemy import inspect
import transaction
import sqlalchemy
from pyramid.view import view_config
from pyramid.renderers import JSON
import cornice.resource
import sys
import inspect
import re
from collections import namedtuple

from zope.sqlalchemy import ZopeTransactionExtension
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.ext.declarative.api import DeclarativeMeta

DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))
route_prefix = 'jsonapi'
model_map = {}
relationship_map = {}

class Resource:
    '''Base class for JSON-API RESTful resources.

    Args:
        request (pyramid.request): request object.

    Attributes:
        request (pyramid.request): request object.
    '''
    def __init__(self, request):
        self.request = request

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


    def collection_get(self):
        '''Get items from the collection.

        Returns:
            dict: results with count::

                {
                    'results': sqlalchemy query results,
                    'count': full number of results available (without pagination)
                }

            \ \
        '''
        # Figure out whether this is a direct model route or a relationship one.
        rc = RouteComponents.from_route(self.request.matched_route.name)
        if rc.relationship:
            # Looking for items from the relationship model.
            rel_class = getattr(self.model, rc.relationship)\
                .property.mapper.class_
            # Looking for relationship items where parent id is resource_id.
            q = DBSession.query(rel_class)
            q = q.join(self.model).filter(
                self.model.id == self.request.matchdict['resource_id'])
        else:
            # Directly looking for items from this classes model.
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
            q = q.filter(op_func(val))

        ret = {}
        # Full count
        ret['count'] = q.count()

        # Paging
        q = q.offset(qinfo['page[offset]']).limit(qinfo['page[limit]'])

        ret['results'] = q.all()

        return ret

    def get(self):
        '''Get a single item.

        Returns:
            single sqlalchemy result.
        '''
        try:
            item = DBSession.query(self.model).filter(self.model.id == self.request.matchdict['id']).one()
        except NoResultFound:
            raise ResourceNotFoundError('No such {} item: {}.'.format(self.model.__tablename__, self.request.matchdict['id']))
        return item

    def collection_post(self):
        '''Create a new item from information in POST request.

        Returns:
            created item.
        '''
        data = self.request.json_body
        atts = data['attributes']
        # Delete id key to force creation of a new item
        try:
            del(atts['id'])
        except KeyError:
            pass
        item = DBSession.merge(self.model(**atts))
        DBSession.flush()
        self.request.response.status_code = 201
        return item

    def patch(self):
        '''Update an existing item with information in PATCH request.

        Returns:
            altered item.
        '''
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

    def delete(self):
        '''Delete an existing item.'''
        item = self.get()
        DBSession.delete(item)

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

def std_meta(section, request, results, **options):
    '''Default function to generate meta sections.

    Arguments:
        section (str): 'toplevel' or 'item'.
            Section of the resulting JSON where this
            information will be added:

                toplevel: information for the
                `JSON-API document top level <http://jsonapi.org/format/#document-top-level>`_.

                resource: information for each `JSON-API document resource object <http://jsonapi.org/format/#document-resource-objects>`_.

        request (pyramid.request): request object.
        results (list of query results): results.
        **options: jsonapi options.

    Returns:
        dict: key, value pairs to be merged with meta section.
    '''
    ret = {}
    if section == 'toplevel':
        ret['route'] = request.matched_route.name
    if isinstance(results, list):
        ret['results_returned'] = len(results)
        if 'count' in options:
            ret['results_available'] = options['count']
    return ret

def test_links(section, request, results, **options):
    ret = {}
    if section == 'toplevel':
        ret['test'] = '/testing'
    if section == 'resource':
        rc = RouteComponents.from_request(request)
        if rc.relationship is None:
            ret['schema'] = '/schemas/{}'.format(rc.resource)
        else:
            ret['schema'] = '/schemas/{}'.format(rc.relationship)
    return ret

def create_jsonapi(models, links_callback=test_links, meta_callback=std_meta):
    '''Auto-create jsonapi from module with sqlAlchemy models.

    Arguments:
        models (module): a module with model classes derived from sqlalchemy.ext.declarative.declarative_base().
        links_callback (function): function returning links dict. Passed to :meth:`create_resource` with the signature described in :meth:`std_meta`.
        meta_callback (function): function returning meta dict. Passed to :meth:`create_resource` with the signature described in :meth:`std_meta`.
    '''
    # Need to add wrapped classes back into this module so that the venusian
    # scan can find them.
    module = sys.modules[__name__]

    # Loop through the models module looking for declaratively defined model
    # classes (inherit DeclarativeMeta). Wrap those classes and their
    # relationships with create_resource().
    for k, model_class in models.__dict__.items():
        if isinstance(model_class,
            sqlalchemy.ext.declarative.api.DeclarativeMeta)\
                and hasattr(model_class, 'id'):
#            print('{}: {}'.format(k, model_class.__class__.__name__))
            setattr(module, k + 'Resource',
                create_resource(
                    model_class, bases=(Resource,),
                    links_callback=links_callback,
                    meta_callback=meta_callback
                )
            )
            for relname, rel in\
                sqlalchemy.inspect(model_class).relationships.items():
                setattr(module, '{}_{}Relationship'.format(k, relname),
                    create_resource(
                        rel, bases=(Resource,),
                        links_callback=links_callback,
                        meta_callback=meta_callback
                    )
                )
create_jsonapi_using_magic_and_pixie_dust = create_jsonapi

def resource(model, **options):
    '''Class decorator: produce a set of resource endpoints from a model class.

    See :meth:`create_resource` for arguments and their meanings.
    '''
    def wrap(cls):
        # Depth has something to do with venusian detecting and creating routes.
        # Needs to be bumped up by one each time a function/class is wrapped.
        return create_resource(model, cls=cls, depth=3, **options)
    return wrap

def create_resource(model,
    collection_name=None, relationship_name=None,
    cls=None, cls_name=None, bases=(Resource,),
    links_callback=None, meta_callback=std_meta,
    depth=2,
    **options):
    '''Produce a set of resource endpoints.

    Arguments:
        collectiona_name (str): name of collection. Defaults to table name from model.
        relationship_name (str): name of relationship. Defaults to None or relationship name derived from model.
        cls (class): class providing cornice view functions. Auto constructed from bases if None.
        cls_name (str): name for autoconstructed class. Defaults to model cls_name + 'Resource' for resources, cls_name + '_' + relationship_name + 'Relationship' for relationships.
        bases (tuple): tuple of base classes for autonstructed cls.
        links_callback (function): function which returns a links dictionary. Signature as described in :meth:`std_meta`.
        meta_callback (function): function which returns a meta dictionary. Signature as described in :meth:`std_meta`.
        depth (int): depth passed to cornice.resource.resource.
        **options (dict): options attached to cls for later rendering.
            In the form::

                {
                    'default_limit': default no of results per page,
                    'max_limit': maximum no of results per page
                }

            \ \

    '''

    # Figure out what table model is from
    info = ModelInfo.construct(model)

    if collection_name is None:
        collection_name = info.table_name
    if relationship_name is None and info.is_relationship:
        relationship_name = info.relationship_name

    # Set up the cornice paths.
    if info.is_relationship:
        collection_path = '{}/{{resource_id}}/relationships/{}'\
            .format(collection_name, relationship_name)
        path = collection_path + '/{related_id}'
    else:
        collection_path = collection_name
        path = collection_path + '/{id}'

    # Find a name for the cornice resource class.
    if cls_name is None:
        if info.is_relationship:
            cls_name = '{}_{}Relationship'.format(
                info.model_class.__name__, relationship_name)
        else:
            cls_name = '{}Resource'.format(info.model_class.__name__)

    # Make sure the __jsonapi__ attribute is available on model_class.
    if not hasattr(info.model_class, '__jsonapi__'):
        info.model_class.__jsonapi__ = {}

    # Populate route information.
    routes = info.model_class.__jsonapi__.setdefault('routes', {})
    route_name = RouteComponents.from_components(collection_name, relationship_name).route
    if info.is_relationship:
        rels = routes.setdefault('relationships', {})
        rels[relationship_name] = route_name
    else:
        info.model_class.__jsonapi__['routes'].setdefault(
            'resource', route_name
        )

    info.model_class.__jsonapi__['links_callback'] = links_callback
    info.model_class.__jsonapi__['meta_callback'] = meta_callback

    # Merge in options from model_class, if any.
    my_opts = {'default_limit': 10, 'max_limit': 100}
    try:
        my_opts.update(info.model_class.__jsonapi__['options'])
    except (AttributeError, KeyError):
        pass
    my_opts.update(options)

    # Set up the class to be wrapped by cornice.
    if cls is None:
        cls = type(cls_name, bases, {})
    # Store the class in the model so that the renderer can find it.
    classes = info.model_class.__jsonapi__.setdefault('classes', {})
    if info.is_relationship:
        classes.setdefault('relationships', {})
        classes['relationships'][relationship_name] = cls
    else:
        classes['resource'] = cls
    cls.model = info.model_class
    cls.default_limit = my_opts['default_limit']
    cls.max_limit = my_opts['max_limit']
    # Add the cls to our module so that a scan will find it.
    setattr(sys.modules[__name__], cls.__name__, cls)
    # Add cls to model_map or relationship_map.
    if info.is_relationship:
        relationship_map.setdefault(collection_name, {})
        relationship_map[collection_name][relationship_name] = cls
    else:
        model_map[collection_name] = cls


    # Call cornice to create the resource class.
    # See the comment in resource about depth.
    return cornice.resource.resource(
        name=route_name,
        collection_path=collection_path, path=path,
        depth=depth, renderer='jsonapi')(cls)

def requested_fields(request, type_name):
    '''Get the sparse field names as a set from req params for type_name.

    Return None if there was no sparse field param.
    '''
    param = request.params.get('fields[{}]'.format(type_name))
    if param is None:
        return None
    return set(param.split(','))

def requested_includes(request):
    '''Parse any 'include' param in http request.'''
    param = request.params.get('include', '')
    inc = set()
    for i in param.split(','):
        curname = []
        for name in i.split('.'):
            curname.append(name)
            inc.add('.'.join(curname))
    return inc

class JSONAPIFromSqlAlchemyRenderer(JSON):
    '''Pyramid renderer: to JSON-API from SqlAlchemy query results.

    **Inherits:** :class:`pyramid.renderers.JSON`

    Args:
        options (dict): Renderer options.
        **kw: Arguments sent to JSON().

    Attributes:
        options (dict): Renderer options.
    '''

    def __init__(self, options=None, **kw):
        '''Init renderer.'''
        if options is None:
            options = {}
        self.options = options
        super().__init__(**kw)

    def __call__(self, info):
        '''Return a renderer function.

        Args:
            info (pyramid.interfaces.IRendererInfo): renderer info

        Returns:
            function: .. function:: _render(value, system)

            The rendering function.

            Args:
                value (dict or query results): Result of view.
                    Should either be a dict like::

                        {
                            'results': query_results,
                            'count': optional_number_of_results,
                            'option1': value1,
                            'option2': value2,
                            ...
                        }

                    or a list of sqlalchemy query results.

                system (dict): Rendering information passed by pyramid.

            Returns:
                Rendered view.
        '''
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
            rc = RouteComponents.from_route(req.matched_route.name)
            ret = {
                'links': {
                    'self': req.route_url(rc.route,_query=req.params, **req.matchdict),
                },
            }

            if results is None:
                data = None
            elif isinstance(results, list):
                ret['links'].update(
                    self.pagination_links(
                        results,
                        req,
                        view_options.get('count'),
                    )
                )
                data = [
                    self.serialise_db_item(
                        dbitem, system,
                        options = view_options,
                        requested_includes = inc,
                        included = included
                    )
                    for dbitem in results
                ]
                if results and results[0].__jsonapi__['meta_callback'] is not None:
                    meta = results[0].__jsonapi__['meta_callback'](
                        section='toplevel',
                        request=req,
                        results=results,
                        **view_options
                    )
                    if meta:
                        if 'meta' in ret:
                            ret['meta'].update(meta)
                        else:
                            ret['meta'] = meta
                if results and results[0].__jsonapi__['links_callback'] is not None:
                    ret['links'].update(
                        results[0].__jsonapi__['links_callback'](
                            section='toplevel',
                            request=req,
                            results=results,
                            **view_options
                        )
                    )
            else:
                data = self.serialise_db_item(
                    results, system,
                    options = view_options,
                    requested_includes = inc,
                    included = included
                )
                if results.__jsonapi__['meta_callback'] is not None:
                    meta = results.__jsonapi__['meta_callback'](
                        section='toplevel',
                        request=req,
                        results=results,
                        **view_options
                    )
                    if meta:
                        if 'meta' in ret:
                            ret['meta'].update(meta)
                        else:
                            ret['meta'] = meta
                if results.__jsonapi__['links_callback'] is not None:
                    ret['links'].update(
                        results.__jsonapi__['links_callback'](
                            section='toplevel',
                            request=req,
                            results=results,
                            **view_options
                        )
                    )

            ret['data'] = data

            if included:
                ret['included'] = [v for v in included.values()]
            #return json.dumps(ret)
            default = self._make_default(req)
            return self.serializer(ret, default=default, **self.kw)
        return _render


    def resource_link(self, item, system):
        '''Return a link to the resource represented by item.

        Args:
            item: item from query results.
            system (dict): Rendering information passed by pyramid.

        Returns:
            str: URL
        '''
        return system['request'].route_url(
            item.__jsonapi__['routes']['resource'],
            **{'id': getattr(item, 'id')}
        )

    def collection_link(self, item, system):
        '''Return a link to the collection item is from.

        Args:
            item: item from query results.
            system (dict): rendering information passed by pyramid.

        Returns:
            str: URL
        '''
        return system['request'].route_url(
            'collection_' + item.__jsonapi__['routes']['resource'], **{}
        )

    def pagination_links(self, results, req, count=None):
        '''Return a dictionary of pagination links.

        Args:
            results (list): query results.
            req: request.
            count (int): total number of results available.

        Returns:
            dict: dictionary of named links.
        '''
        links = {}
        if not results:
            return links
        route_name = req.matched_route.name
        rc = RouteComponents.from_route(req.matched_route.name)
        if rc.relationship is None:
            qinfo = model_map[rc.resource].collection_query_info(req)
        else:
            qinfo = relationship_map[rc.resource][rc.relationship]\
                .collection_query_info(req)

        _query = {
            'page[limit]': qinfo['page[limit]'],
            'sort': qinfo['sort']
        }
        for f in sorted(qinfo['_filters']):
            _query[f] = qinfo['_filters'][f]['value']

        # First link.
        _query['page[offset]'] = 0
        links['first'] = req.route_url(route_name,_query=_query, **req.matchdict)

        # Next link.
        next_offset = qinfo['page[offset]'] + qinfo['page[limit]']
        if count is not None and next_offset < count:
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
            _query['page[offset]'] = ((count - 1) // qinfo['page[limit]']) * qinfo['page[limit]']
            links['last'] = req.route_url(route_name,_query=_query, **req.matchdict)
        return links

    def serialise_db_item(self, item, system,
        requested_includes=None, include_path=None, included=None,
        options=None):
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

        # meta and links callbacks
        if item.__jsonapi__['meta_callback'] is not None:
            add_meta = item.__jsonapi__['meta_callback'](
                section='resource',
                request=system['request'],
                results=item,
                **opts
            )
            if add_meta:
                if 'meta' in ret:
                    ret['meta'].update(add_meta)
                else:
                    ret['meta'] = add_meta
        if item.__jsonapi__['links_callback'] is not None:
            ret['links'].update(
                item.__jsonapi__['links_callback'](
                    section='resource',
                    request=system['request'],
                    results=item,
                    **opts
                )
            )


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
