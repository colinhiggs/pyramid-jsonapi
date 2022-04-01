"""Provide base class for collection views and utilities."""
# pylint: disable=too-many-lines; It's mostly docstrings
import functools
import itertools
import importlib
import logging
import re
import sqlalchemy
import warnings
from collections import namedtuple
from collections.abc import Sequence
from functools import partial
from pyramid.httpexceptions import (
    HTTPNotFound,
    HTTPForbidden,
    HTTPBadRequest,
    HTTPConflict,
    HTTPUnsupportedMediaType,
    HTTPNotAcceptable,
    HTTPError,
    HTTPFailedDependency,
    HTTPInternalServerError,
    HTTPMethodNotAllowed,
    status_map,
)
from pyramid.settings import asbool
from rqlalchemy import RQLQueryMixIn
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm import (
    load_only,
    aliased,
    Query as BaseQuery,
)
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.orm.exc import NoResultFound

ONETOMANY = sqlalchemy.orm.interfaces.ONETOMANY
MANYTOMANY = sqlalchemy.orm.interfaces.MANYTOMANY
MANYTOONE = sqlalchemy.orm.interfaces.MANYTOONE

from pyramid_jsonapi.permissions import (
    Permission,
    Targets,
)
import pyramid_jsonapi.workflow as wf


Entity = namedtuple('Entity', 'type')


class RQLQuery(BaseQuery, RQLQueryMixIn):

    def _rql_ilike(self, args):
        attr, value = args

        attr = self._rql_attr(attr)
        value = self._rql_value(value, attr)
        value = value.replace("*", "%")

        return attr.ilike(value)


class CollectionViewBase:
    """Base class for all view classes.

    Arguments:
        request (pyramid.request): passed by framework.
    """

    # pylint:disable=too-many-public-methods

    # Define class attributes
    # Callable attributes use lambda to keep pylint happy
    api = None
    all_attributes = None
    attributes = None
    callbacks = None
    collection_name = None
    default_limit = None
    exposed_fields = None
    fields = None
    dbsession = None
    hybrid_attributes = None
    item = None
    key_column = None
    max_limit = None
    model = lambda: None
    obj_id = None
    not_found_message = None
    request = None
    rel = None
    rel_class = None
    rel_view = None
    relationships = None
    relname = None
    view_classes = None
    settings = None
    permission_filters = None
    permission_template = None
    methods = None

    def __init__(self, request):
        self.request = request
        if self.api.get_dbsession:
            self.dbsession = self.api.get_dbsession(self)
        else:
            self.dbsession = self.request.dbsession
        self.views = {}

    @staticmethod
    def id_col(item):
        """Return the column holding an item's id."""
        return getattr(item, item.__pyramid_jsonapi__['id_col_name'])

    def get_one(self, query, not_found_message=None):
        try:
            item = query.one()
        except (NoResultFound, sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            # NoResultFound is sqlalchemy's native exception if there is no
            #  such id in the collection.
            # DataError is caused by e.g. id (int) = cat
            # StatementError is caused by e.g. id (uuid) = 1
            if not_found_message:
                raise HTTPNotFound(not_found_message)
            else:
                return None
        return item

    def get_item(self, _id=None):
        """Return the item specified by _id. Will look up id from request if _id is None.
        """
        if _id is None:
            _id = self.obj_id
        return self.get_one(
            self.dbsession.query(
                self.model
            ).options(
                load_only(self.key_column.name)
            ).filter(
                self.key_column == _id
            )
        )

    def get_old(self):
        """Handle GET request for a single item.

        Get a single item from the collection, referenced by id.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound

        Example:

            Get person 1:

            .. parsed-literal::

                http GET http://localhost:6543/people/1
        """
        pass

    def patch_old(self):
        """Handle PATCH request for a single item.

        Update an existing item from a partially defined representation.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        **Request Body**

            **Partial resource object** (*json*)

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    'meta': {
                        'updated': [
                            <attribute_name>,
                            <attribute_name>
                        ]
                    }
                }

        Raises:
            HTTPNotFound

        Todo:
            Currently does not deal with relationships.

        Example:
            PATCH person 1, changing name to alicia:

            .. parsed-literal::

                http PATCH http://localhost:6543/people/1 data:='
                {
                    "type":"people", "id": "1",
                    "attributes": {
                        "name": "alicia"
                    }
                }' Content-Type:application/vnd.api+json

            Change the author of posts/1 to people/2:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1 data:='
                {
                    "type":"posts", "id": "1",
                    "relationships": {
                        "author": {"type": "people", "id": "2"}
                    }
                }' Content-Type:application/vnd.api+json

            Set the comments on posts/1 to be [comments/4, comments/5]:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1 data:='
                {
                    "type":"posts", "id": "1",
                    "relationships": {
                        "comments": [
                            {"type": "comments", "id": "4"},
                            {"type": "comments", "id": "5"}
                        ]
                    }
                }' Content-Type:application/vnd.api+json
        """
        pass

    def delete_old(self):
        """Handle DELETE request for single item.

        Delete the referenced item from the collection.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id

        Returns:
            jsonapi.Document: Resource Identifier for deleted object.

        Raises:
            HTTPFailedDependency: if a database constraint would be broken by
            deleting the specified resource from the relationship.

        Example:
            delete person 1:

            .. parsed-literal::

                http DELETE http://localhost:6543/people/1
        """
        pass

    def collection_get_old(self):
        """Handle GET requests for the collection.

        Get a set of items from the collection, possibly matching search/filter
        parameters. Optionally sort the results, page them, return only certain
        fields, and include related resources.

        **Query Parameters**

            **include:** comma separated list of related resources to include
            in the include section.

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

            **sort:** comma separated list of sort keys.

            **page[limit]:** number of results to return per page.

            **page[offset]:** starting index for current page.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": [ list of resource objects ],
                    "links": { links object },
                    "include": [ optional list of included resource objects ],
                    "meta": { implementation specific information }
                }

        Raises:
            HTTPBadRequest

        Examples:
            Get up to default page limit people resources:

            .. parsed-literal::

                http GET http://localhost:6543/people

            Get the second page of two people, reverse sorted by name and
            include the related posts as included documents:

            .. parsed-literal::

                http GET http://localhost:6543/people?page[limit]=2&page[offset]=2&sort=-name&include=posts
        """
        pass

    def collection_post_old(self):
        """Handle POST requests for the collection.

        Create a new object in collection.

        **Request Body**

            **resource object** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": { resource object }
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPForbidden: if an id is presented in "data" and client ids are
            not supported.

            HTTPConflict: if type is not present or is different from the
            collection name.

            HTTPNotFound: if a non existent relationship is referenced in the
            supplied resource object.

            HTTPConflict: if creating the object would break a database
            constraint (most commonly if an id is supplied by the client and
            an item with that id already exists).

            HTTPBadRequest: if the request is malformed in some other way.

        Examples:
            Create a new person with name 'monty' and let the server pick the
            id:

            .. parsed-literal::

                http POST http://localhost:6543/people data:='
                {
                    "type":"people",
                    "attributes": {
                        "name": "monty"
                    }
                }' Content-Type:application/vnd.api+json
        """
        pass

    def related_get_old(self):
        """Handle GET requests for related URLs.

        Get object(s) related to a specified object.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            For a TOONE relationship (return one object):

            .. parsed-literal::

                {
                    "data": { resource object },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

            For a TOMANY relationship (return multiple objects):

            .. parsed-literal::

                {
                    "data": [ { resource object }, ... ]
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if `relname` is not found as a relationship.

            HTTPBadRequest: if a bad filter is used.

        Examples:
            Get the author of post 1:

            .. parsed-literal::

                http GET http://localhost:6543/posts/1/author
        """
        pass

    def relationships_get_old(self):
        """Handle GET requests for relationships URLs.

        Get object identifiers for items referred to by a relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Query Parameters**
            **sort:** comma separated list of sort keys.

            **filter[<attribute>:<op>]:** filter operation.

        Returns:
            jsonapi.Document: in the form:

            For a TOONE relationship (return one identifier):

            .. parsed-literal::

                {
                    "data": { resource identifier },
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

            For a TOMANY relationship (return multiple identifiers):

            .. parsed-literal::

                {
                    "data": [ { resource identifier }, ... ]
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPBadRequest: if a bad filter is used.

        Examples:
            Get an identifer for the author of post 1:

            .. parsed-literal::

                http GET http://localhost:6543/posts/1/relationships/author
        """
        pass

    def relationships_post_old(self):
        """Handle POST requests for TOMANY relationships.

        Add the specified member to the relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPNotFound: if an attempt is made to modify a TOONE relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Add comments/1 as a comment of posts/1

            .. parsed-literal::

                http POST http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        """
        pass

    def relationships_patch_old(self):
        """Handle PATCH requests for relationships (TOMANY or TOONE).

        Completely replace the relationship membership.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            TOONE relationship:

            .. parsed-literal::

                {
                    "data": { resource identifier }
                }

            TOMANY relationship:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Replace comments list of posts/1:

            .. parsed-literal::

                http PATCH http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" },
                    { "type": "comments", "id": "2" }
                ]' Content-Type:application/vnd.api+json
        """
        pass

    def relationships_delete_old(self):
        """Handle DELETE requests for TOMANY relationships.

        Delete the specified member from the relationship.

        **URL (matchdict) Parameters**

            **id** (*str*): resource id
            **relname** (*str*): relationship name

        **Request Body**

            **resource identifier list** (*json*) in the form:

            .. parsed-literal::

                {
                    "data": [ { resource identifier },... ]
                }

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "links": {
                        "self": self url,
                        maybe other links...
                    },
                    "meta": { jsonapi specific information }
                }

        Raises:
            HTTPNotFound: if there is no <relname> relationship.

            HTTPNotFound: if an attempt is made to modify a TOONE relationship.

            HTTPConflict: if a resource identifier is specified with a
            different type than that which the collection holds.

            HTTPFailedDependency: if a database constraint would be broken by
            adding the specified resource to the relationship.

        Examples:
            Delete comments/1 from posts/1 comments:

            .. parsed-literal::

                http DELETE http://localhost:6543/posts/1/relationships/comments data:='
                [
                    { "type": "comments", "id": "1" }
                ]' Content-Type:application/vnd.api+json
        """
        pass

    def base_collection_query(self, loadonly=None):
        if not loadonly:
            loadonly = self.allowed_requested_query_columns.keys()
        query = self.dbsession.query(
            self.model
        ).options(
            load_only(*loadonly)
        )
        query._entities = [Entity(type=self.model)]
        query.__class__ = RQLQuery
        return query

    def single_item_query(self, obj_id=None, loadonly=None):
        """A query representing the single item referenced by id.

        Keyword Args:
            obj_id: id of object to be fetched. If None then use the id from
                the URL.
            loadonly: which attributes to load. If None then all requested
                attributes from the URL.

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch item with id
            'id'.
        """
        if obj_id is None:
            obj_id = self.obj_id
        return self.base_collection_query(loadonly=loadonly).filter(
            self.id_col(self.model) == obj_id
        )

    def query_add_sorting(self, query):
        """Add sorting to query.

        Use information from the ``sort`` query parameter (via
        :py:func:`collection_query_info`) to contruct an ``order_by`` clause on
        the query.

        See Also:
            ``_sort`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **sort:** comma separated list of sort keys.

        Parameters:
            query (sqlalchemy.orm.query.Query): query

        Returns:
            sqlalchemy.orm.query.Query: query with ``order_by`` clause.
        """
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
            if main_key in self.relationships:
                # If order_att is a relationship then we need to add a join to
                # the query and order_by the sort_keys[1] column of the
                # relationship's target. The default target column is 'id'.
                rel = self.relationships[main_key]
                if rel.to_many:
                    raise HTTPBadRequest(f"Can't sort by TO_MANY relationship {main_key}.")
                query = query.join(order_att)
                try:
                    sub_key = sort_keys[1]
                except IndexError:
                    # Use the relationship
                    sub_key = self.view_instance(
                        rel.tgt_class
                    ).key_column.name
                order_att = getattr(rel.tgt_class, sub_key)
            if key_info['ascending']:
                query = query.order_by(order_att)
            else:
                query = query.order_by(order_att.desc())

        return query

    def query_add_filtering(self, query):
        """Add filtering clauses to query.

        Use information from the ``filter`` query parameter (via
        :py:func:`collection_query_info`) to filter query results.

        Filter parameter structure:

            ``filter[<attribute>:<op>]=<value>``

        where:

            ``attribute`` is an attribute of the queried object type.

            ``op`` is the comparison operator.

            ``value`` is the value the comparison operator should compare to.

        Valid comparison operators:
            Only operators added via self.api.filter_registry.register() are
            considered valid. Get a list of filter names with
            self.api.filter_registry.valid_filter_names()

        See Also:
            ``_filters`` key from :py:func:`collection_query_info`

        **Query Parameters**
            **filter[<attribute>:<op>]:** filter operation.

        Parameters:
            query (sqlalchemy.orm.query.Query): query

        Returns:
            sqlalchemy.orm.query.Query: filtered query.

        Examples:

            Get people whose name is 'alice'

            .. parsed-literal::

                http GET http://localhost:6543/people?filter[name:eq]=alice

            Get posts published after 2015-01-03:

            .. parsed-literal::

                http GET http://localhost:6543/posts?filter[published_at:gt]=2015-01-03

        Todo:
            Support dotted (relationship) attribute specifications.
        """
        qinfo = self.collection_query_info(self.request)
        # Filters
        for finfo in qinfo['_filters'].values():
            val = finfo['value']
            colspec = finfo['colspec']
            prop_name = colspec[0]
            operator = finfo['op']
            try:
                prop = getattr(self.model, prop_name)
            except AttributeError:
                raise HTTPBadRequest(
                    "Collection '{}' has no attribute '{}'".format(
                        self.collection_name, '.'.join(colspec)
                    )
                )
            if prop_name in self.relationships:
                # The property indicated is on the other side of a relationship
                rel = self.relationships[prop_name]
                if isinstance(rel.obj, AssociationProxy):
                    # We need to join across association proxies differently.
                    proxy = rel.obj.for_class(rel.src_class)
                    query = query.join(proxy.remote_attr).filter(
                        proxy.local_attr.property.local_remote_pairs[0][1] == self.id_col(self.model)
                    )
                else:
                    query = query.join(prop)
                prop = getattr(rel.tgt_class, colspec[1])
            try:
                filtr = self.api.filter_registry.get_filter(type(prop.type), operator)
            except KeyError:
                raise HTTPBadRequest(
                    "No such filter operator: '{}'".format(operator)
                )
            val = filtr['value_transform'](val)
            try:
                comparator = getattr(prop, filtr['comparator_name'])
            except AttributeError:
                raise HTTPInternalServerError(
                    "Operator '{}' is registered but has no implementation on attribute '{}'.".format(
                        operator, '.'.join(colspec)
                    )
                )
            query = query.filter(comparator(val))

        for rql in qinfo['_rql_filters']:
            query = query.rql(rql)

        return query

    def related_limit(self, relationship):
        """Paging limit for related resources.

        **Query Parameters**

            **page[limit:relationships:<relname>]:** number of results to
            return per page for related resource <relname>.

        Parameters:
            relationship(sqlalchemy.orm.relationships.RelationshipProperty):
                the relationship to get the limit for.

        Returns:
            int: paging limit for related resources.
        """
        limit_comps = ['limit', 'relationships', relationship.name]
        limit = self.default_limit
        qinfo = self.collection_query_info(self.request)
        while limit_comps:
            if '.'.join(limit_comps) in qinfo['_page']:
                limit = int(qinfo['_page']['.'.join(limit_comps)])
                break
            limit_comps.pop()
        return min(limit, self.max_limit)

    @functools.lru_cache()
    def model_from_table(self, table):
        """Find the model class mapped to a table."""
        for model in self.api.view_classes.keys():
            if model.__table__ is table:
                return model
        raise KeyError("No model mapped to %s." % table)

    def association_proxy_query(self, obj_id, rel, full_object=True):
        """Construct query for related objects across an association proxy.

        Parameters:
            obj_id (str): id of an item in this view's collection.

            proxy (sqlalchemy.ext.associationproxy.ObjectAssociationProxyInstance):
                the relationships to get related objects from.

            full_object (bool): if full_object is ``True``, query for all
                requested columns (probably to build resource objects). If
                full_object is False, only query for the key column (probably
                to build resource identifiers).

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch related
            object(s).
        """
        rel_view = self.view_instance(rel.tgt_class)
        proxy = rel.obj.for_class(rel.src_class)
        src_class = rel.src_class if rel.src_class is not rel.tgt_class else aliased(rel.src_class)
        query = self. dbsession.query(
            rel.tgt_class
        ).select_from(
            src_class
        ).join(
            proxy.local_attr
        ).join(
            proxy.remote_attr
        ).filter(
            self.id_col(src_class) == obj_id
        )
        if full_object:
            query = query.options(
                load_only(*rel_view.allowed_requested_query_columns.keys())
            )
        else:
            query = query.options(load_only(rel_view.key_column.name))
        return query

    def standard_relationship_query(self, obj_id, relationship, full_object=True):
        """Construct query for related objects via a normal relationship.

        Parameters:
            obj_id (str): id of an item in this view's collection.

            relationship (sqlalchemy.orm.relationships.RelationshipProperty):
                the relationships to get related objects from.

            full_object (bool): if full_object is ``True``, query for all
                requested columns (probably to build resource objects). If
                full_object is False, only query for the key column (probably
                to build resource identifiers).

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch related
            object(s).
        """
        rel_model = relationship.tgt_class
        tables = [
            getattr(col, 'table', None)
            for col in relationship.obj.local_remote_pairs[0]
        ]
        # if tables[0] is tables[1]:
        if rel_model is self.model:
            model = aliased(self.model)
        else:
            model = self.model
        return self.dbsession.query(rel_model).select_from(
            model
        ).join(
            getattr(model, relationship.name)
        ).filter(
            self.id_col(model) == obj_id
        )

    def related_query(self, obj, relationship, full_object=True):
        """Construct query for related objects.

        Parameters:
            obj_id (str): id of an item in this view's collection.

            relationship: the relationship object to get related objects from.
                This can be a RelationshipProperty or AssociationProxy object.

            related_to (model class or None): the class the relationship is
                coming from. AssociationProxy relationships use this. It
                defaults to ``None``, which is interpreted as self.model.

            full_object (bool): if full_object is ``True``, query for all
                requested columns (probably to build resource objects). If
                full_object is False, only query for the key column (probably
                to build resource identifiers).

        Returns:
            sqlalchemy.orm.query.Query: query which will fetch related
            object(s).
        """
        if obj is None:
            obj_id = None
        else:
            obj_id = self.id_col(obj)
        if isinstance(relationship.obj, AssociationProxy):
            query = self.association_proxy_query(
                obj_id, relationship, full_object=full_object
            )
        else:
            query = self.standard_relationship_query(
                obj_id, relationship, full_object=full_object
            )
        return query

    def object_exists(self, obj_id):
        """Test if object with id obj_id exists.

        Args:
            obj_id (str): object id

        Returns:
            bool: True if object exists, False if not.
        """
        try:
            return bool(self.dbsession.query(
                self.model
            ).options(
                load_only(self.key_column.name)
            ).filter(self.key_column == obj_id).one_or_none())
        except (sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            return False

    def mapped_info_from_name(self, name, model=None):
        """Get the pyramid_jsonapi info dictionary for a mapped object.

        Parameters:
            name (str): name of object.

            model (sqlalchemy.ext.declarative.declarative_base): model to
                inspect. Defaults to self.model.

        """
        return sqlalchemy.inspect(model or self.model).all_orm_descriptors.get(
            name
        ).info.get('pyramid_jsonapi', {})

    @classmethod
    @functools.lru_cache()
    def collection_query_info(cls, request):
        """Return dictionary of information used during DB query.

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
        """
        info = {}

        # Paging by limit and offset.
        # Use params 'page[limit]' and 'page[offset]' to comply with spec.
        info['page[limit]'] = min(
            cls.max_limit,
            int(request.params.get('page[limit]', cls.default_limit))
        )
        if info['page[limit]'] < 0:
            raise HTTPBadRequest('page[limit] must not be negative.')
        info['page[offset]'] = int(request.params.get('page[offset]', 0))
        if info['page[offset]'] < 0:
            raise HTTPBadRequest('page[offset] must not be negative.')

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
        info['_rql_filters'] = []
        info['_page'] = {}
        for param in request.params.keys():
            match = re.match(r'(.*?)\[(.*?)\]', param)
            if not match:
                continue
            val = request.params.get(param)

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
                if match.group(2) == '*rql':
                    info['_rql_filters'].append(val)
                else:
                    colspec = match.group(2)
                    operator = 'eq'
                    try:
                        colspec, operator = colspec.split(':')
                    except ValueError:
                        pass
                    colspec = colspec.split('.')
                    info['_filters'][param] = {
                        'colspec': colspec,
                        'op': operator,
                        'value': val
                    }

            # Paging.
            elif match.group(1) == 'page':
                info['_page'][match.group(2)] = val

        # Options.
        info['pj_include_count'] = asbool(
            request.params.get('pj_include_count', 'false')
        )

        return info

    def pagination_links(self, count=0):
        """Return a dictionary of pagination links.

        Args:
            count (int): total number of results available.

        Returns:
            dict: dictionary of named links.
        """
        links = {}
        req = self.request
        route_name = req.matched_route.name
        qinfo = self.collection_query_info(req)
        _query = {'page[{}]'.format(k): v for k, v in qinfo['_page'].items()}
        _query['sort'] = qinfo['sort']
        for filtr in sorted(qinfo['_filters']):
            _query[filtr] = qinfo['_filters'][filtr]['value']

        # First link.
        _query['page[offset]'] = 0
        links['first'] = req.route_url(
            route_name, _query=_query, **req.matchdict
        )

        # Next link.
        next_offset = qinfo['page[offset]'] + qinfo['page[limit]']
        if count is None or next_offset < count:
            _query['page[offset]'] = next_offset
            links['next'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Previous link.
        if qinfo['page[offset]'] > 0:
            prev_offset = qinfo['page[offset]'] - qinfo['page[limit]']
            if prev_offset < 0:
                prev_offset = 0
            _query['page[offset]'] = prev_offset
            links['prev'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Last link.
        if count is not None:
            _query['page[offset]'] = (
                max((count - 1), 0) //
                qinfo['page[limit]']
            ) * qinfo['page[limit]']
            links['last'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )
        return links

    @property
    def allowed_fields(self):
        """Set of fields to which current action is allowed.

        Returns:
            set: set of allowed field names.
        """
        return set(self.fields)

    def allowed_object(self, obj):  # pylint:disable=no-self-use,unused-argument
        """Whether or not current action is allowed on object.

        Returns:
            bool:
        """
        return True

    @property
    @functools.lru_cache()
    def requested_field_names(self):
        """Get the sparse field names from request.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            set: set of field names.
        """
        param = self.request.params.get(
            'fields[{}]'.format(self.collection_name)
        )
        if param is None:
            return set(self.attributes.keys()).union(
                self.hybrid_attributes.keys()
            ).union(
                self.relationships.keys()
            )
        elif param == '':
            return set()
        return set(param.split(','))

    @property
    def requested_attributes(self):
        """Return a dictionary of attributes.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <colname>: <column_object>,
                        ...
                    }
        """
        return {
            k: v for k, v in self.all_attributes.items()
            if k in self.requested_field_names
        }

    @property
    def requested_relationships(self):
        """Return a dictionary of relationships.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <relname>: <relationship_object>,
                        ...
                    }
        """
        return {
            k: v for k, v in self.relationships.items()
            if k in self.requested_field_names
        }

    @property
    def requested_fields(self):
        """Union of attributes and relationships.

        **Query Parameters**

            **fields[<collection>]:** comma separated list of fields
            (attributes or relationships) to include in data.

        Returns:
            dict: dict in the form:

                .. parsed-literal::

                    {
                        <colname>: <column_object>,
                        ...
                        <relname>: <relationship_object>,
                        ...
                    }

        """
        ret = self.requested_attributes
        ret.update(
            self.requested_relationships
        )
        return ret

    @property
    def allowed_requested_relationships_local_columns(self):  # pylint:disable=invalid-name
        """Finds all the local columns for allowed MANYTOONE relationships.

        Returns:
            dict: local columns indexed by column name.
        """
        rels = {}
        for k, rel in self.requested_relationships.items():
            if isinstance(rel.obj, RelationshipProperty) and rel.direction is MANYTOONE and k in self.allowed_fields:
                for pair in rel.obj.local_remote_pairs:
                    rels[pair[0].name] = pair[0]
        return rels

    @property
    def allowed_requested_query_columns(self):
        """All columns required in query to fetch allowed requested fields from
        db.

        Returns:
            dict: Union of allowed requested_attributes and
            allowed_requested_relationships_local_columns
        """
        ret = {
            k: v for k, v in self.requested_attributes.items()
            if k in self.allowed_fields and k not in self.hybrid_attributes
        }
        ret.update(
            self.allowed_requested_relationships_local_columns
        )
        return ret

    @functools.lru_cache()
    def requested_include_names(self):
        """Parse any 'include' param in http request.

        Returns:
            set: names of all requested includes.

        Default:
            set: names of all direct relationships of self.model.
        """
        inc = set()
        param = self.request.params.get('include')

        if param:
            for item in param.split(','):
                curname = []
                for name in item.split('.'):
                    curname.append(name)
                    inc.add('.'.join(curname))
        return inc

    # @functools.lru_cache()
    def path_is_included(self, path):
        """Test if path is in requested includes.

        Args:
            path (list): list representation if include path to test.

        Returns:
            bool: True if path is in requested includes.

        """
        return '.'.join(path) in self.requested_include_names()

    @property
    def bad_include_paths(self):
        """Return a set of invalid 'include' parameters.

        **Query Parameters**

            **include:** comma separated list of related resources to include
            in the include section.

        Returns:
            set: set of requested include paths with no corresponding
            attribute.
        """
        param = self.request.params.get('include')
        bad = set()
        if param:
            for item in param.split(','):
                curname = []
                curview = self
                tainted = False
                for name in item.split('.'):
                    curname.append(name)
                    if tainted:
                        bad.add('.'.join(curname))
                    else:
                        if name in curview.relationships.keys():
                            curview = curview.view_instance(
                                curview.relationships[name].tgt_class
                            )
                        else:
                            tainted = True
                            bad.add('.'.join(curname))
        return bad

    @functools.lru_cache()
    def view_instance(self, model):
        """(memoised) get an instance of view class for model.

        Args:
            model (DeclarativeMeta): model class.

        Returns:
            class: subclass of CollectionViewBase providing view for ``model``.
        """
        view_instance = self.api.view_classes[model](self.request)
        try:
            view_instance.pj_shared = self.pj_shared
        except AttributeError:
            pass
        return view_instance

    @classmethod
    def _add_stage_handler(
        cls, view_method, stage_name, hfunc,
        add_after='end',
        add_existing=False,
    ):
        '''
        Add a stage handler to a stage of a view method.
        '''
        vm_func = getattr(cls, view_method)
        try:
            stage = vm_func.stages[stage_name]
        except KeyError:
            raise KeyError(
                f'Endpoint {view_method} has no stage {stage_name}.'
            )
        try:
            index = stage.index(hfunc)
        except ValueError:
            index = False
        if index and not add_existing:
            return
        if add_after == 'start':
            stage.appendleft(hfunc)
        elif add_after == 'end':
            stage.append(hfunc)
        else:
            stage.insert(stage.index(add_after) + 1, hfunc)

    @classmethod
    def add_stage_handler(
        cls, methods, stages, hfunc,
        add_after='end',
        add_existing=False,
    ):
        '''
        Add a stage handler to stages of view methods.

        Arguments:
            methods: an iterable of view method names (``get``,
                ``collection_get`` etc.).
            stages: an iterable of stage names.
            hfunc: the handler function.
            add_existing: If True, add this handler even if it exists in the
                deque.
            add_after: 'start', 'end', or an existing function.
        '''
        for vm_name in methods:
            vm_func = getattr(cls, vm_name)
            for stage_name in stages:
                cls._add_stage_handler(
                    vm_name, stage_name, hfunc, add_after, add_existing,
                )

    @staticmethod
    def true_filter(*args, **kwargs):
        return True

    @classmethod
    def wrap_permission_filter(cls, permission, stage, pfunc):
        def wrapped_pfunc(
            view,
            object_rep,
            target,
            mask=Permission.from_template_cached(
                cls.permission_template
            ),
        ):
            result = pfunc(
                object_rep,
                view=view,
                stage=stage,
                permission=permission,
                target=target,
                mask=mask,
            )
            if target.type == Targets.relationship:
                # We want to be sure that we return a bool here.
                if isinstance(result, bool):
                    return result
                elif isinstance(result, Permission):
                    return target.name in result.relationships
                else:
                    raise TypeError(
                        f"Permission filter should return a bool or Permission, not {type(result)}."
                    )
            return Permission.from_pfilter(
                cls.permission_template, result
            )
        return wrapped_pfunc

    @classmethod
    def register_permission_filter(
        cls, permissions, stages, pfunc, target_types=list(Targets), warn=True,
    ):
        # Permission filters should have the signature:
        #   pfunc(object_rep, view, stage, permission)

        # Just to shorten a long ugly name:
        method_sets = cls.api.endpoint_data.endpoints['http_method_sets']
        perms = set()
        for pname in permissions:
            if pname in method_sets:
                perms |= method_sets[pname]
            else:
                perms.add(pname)
        cls.api.enable_permission_handlers(stages)
        # Triply nested for loop gets very deep. Use product to flatten it.
        for stage_name, perm, tt in itertools.product(stages, perms, target_types):
            perm = perm.lower()
            # Register the filter function.
            if warn and cls.permission_filters[perm][tt].get(stage_name, False):
                warnings.warn(f"Overwriting existing permission filter in {perm}.{tt}.{stage_name}")
            cls.permission_filters[perm][tt][stage_name] = \
                cls.wrap_permission_filter(perm, stage_name, pfunc)

    def permission_filter(self, permission, target_type, stage_name, default=None):
        """
        Find the permission filter given a permission and stage name.
        """
        default = default or (lambda *a, **kw: True)
        try:
            filter = self.permission_filters[permission][target_type][stage_name]
        except KeyError as e:
            defmask = Permission.from_template_cached(self.permission_template)
            filter = self.wrap_permission_filter(permission, stage_name, default)
        return partial(filter, self)

    @classmethod
    def permission_handler(cls, endpoint_name, stage_name):
        # Look for the most specific permission handler first: see if one is
        # defined by the workflow method module (wf_kind_endpoint).
        wf_kind_endpoint = importlib.import_module(
            getattr(cls.api.settings, 'workflow_{}'.format(endpoint_name))
        )
        try:
            return wf_kind_endpoint.permission_handler(stage_name)
        except (KeyError, AttributeError):
            # Either no permission_handler (AttributeError) or it doesn't handle
            # method_name or stage_name (KeyError). Either way look for a
            # handler in the wf_kind package.
            wf_kind = importlib.import_module(wf_kind_endpoint.__package__)
            # Last part after the underscore of the endpoint name should be the
            # HTTP method/verb.
            try:
                return wf_kind.permission_handler(endpoint_name, stage_name)
            except (KeyError, AttributeError):
                # Use generic workflow module if it handles this stage.
                try:
                    return wf.permission_handler(endpoint_name, stage_name)
                except KeyError:
                    # This method and stage is completely unhandled. Return a
                    # handler that effectively does nothing.
                    return lambda arg, *args, **kwargs: arg

    def permission_object(
        self,
        attributes=None, relationships=None, id=None,
        subtract_attributes=frozenset(), subtract_relationships=frozenset()
    ):
        template = self.permission_template
        id = id if id is not None else template.id
        attributes = Permission._caclulate_attr_val(
            'attributes', attributes, template.attributes, id
        ) - subtract_attributes
        relationships = Permission._caclulate_attr_val(
            'relationships', relationships, template.relationships, id
        ) - subtract_relationships

        return Permission(template, attributes, relationships, id)
