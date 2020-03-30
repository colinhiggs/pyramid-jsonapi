"""Provide base class for collection views and utilities."""
# pylint: disable=too-many-lines; It's mostly docstrings
import functools
import itertools
import logging
import re
from collections.abc import Sequence

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
    status_map,
)
import pyramid_jsonapi.jsonapi
import sqlalchemy
from sqlalchemy.ext.associationproxy import AssociationProxy
from sqlalchemy.orm import load_only, aliased
from sqlalchemy.orm.relationships import RelationshipProperty
from sqlalchemy.orm.exc import NoResultFound

ONETOMANY = sqlalchemy.orm.interfaces.ONETOMANY
MANYTOMANY = sqlalchemy.orm.interfaces.MANYTOMANY
MANYTOONE = sqlalchemy.orm.interfaces.MANYTOONE


class CollectionViewBase:
    """Base class for all view classes.

    Arguments:
        request (pyramid.request): passed by framework.
    """

    # pylint:disable=too-many-public-methods

    # Define class attributes
    # Callable attributes use lambda to keep pylint happy
    api = None
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
    request = None
    rel = None
    rel_class = None
    rel_view = None
    relationships = None
    relname = None
    view_classes = None
    settings = None

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
        return self.dbsession.query(
            self.model
        ).options(
            load_only(*loadonly)
        )

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

    def single_return(self, query, not_found_message=None, identifier=False):
        """Populate return dictionary for a single item.

        Arguments:
            query (sqlalchemy.orm.query.Query): query designed to return one item.

        Keyword Arguments:
            not_found_message (str or None): if an item is not found either:

                * raise 404 with ``not_found_message`` if it is a str;

                * or return ``{"data": None}`` if ``not_found_message`` is None.

            identifier: return identifier if True, object if false.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": { resource object }

                    optionally...
                    "included": [ included objects ]
                }

            or

            .. parsed-literal::

                { resource identifier }

        Raises:
            HTTPNotFound: if the item is not found.
        """
        included = {}
        doc = pyramid_jsonapi.jsonapi.Document()
        try:
            item = query.one()
        except NoResultFound:
            if not_found_message:
                raise HTTPNotFound(not_found_message)
            else:
                return doc
        if identifier:
            doc.data = self.serialise_resource_identifier(self.id_col(item))
        else:
            doc.data = self.serialise_db_item(item, included)
            if self.requested_include_names():
                doc.included = [obj for obj in included.values()]
        return doc

    def collection_return(self, query, count=None, identifiers=False):
        """Populate return document for collections.

        Arguments:
            query (sqlalchemy.orm.query.Query): query designed to return multiple
            items.

        Keyword Arguments:
            count(int): Number of items the query will return (if known).

            identifiers(bool): return identifiers if True, objects if false.

        Returns:
            jsonapi.Document: in the form:

            .. parsed-literal::

                {
                    "data": [ resource objects ]

                    optionally...
                    "included": [ included objects ]
                }

            or

            .. parsed-literal::

                [ resource identifiers ]

        Raises:
            HTTPBadRequest: If a count was not supplied and an attempt to call
            q.count() failed.
        """
        # Get info for query.
        qinfo = self.collection_query_info(self.request)

        # Add information to the return dict
        doc = pyramid_jsonapi.jsonapi.Document(collection=True)
        results = {}

        try:
            count = count or query.count()
        except sqlalchemy.exc.ProgrammingError:
            raise HTTPInternalServerError(
                'An error occurred querying the database. Server logs may have details.'
            )

        results['available'] = count

        # Pagination links
        doc.links = self.pagination_links(
            count=results['available']
        )
        results['limit'] = qinfo['page[limit]']
        results['offset'] = qinfo['page[offset]']

        # Primary data
        try:
            if identifiers:
                data = [
                    self.serialise_resource_identifier(self.id_col(dbitem))
                    for dbitem in query.all()
                ]
            else:
                included = {}
                data = [
                    self.serialise_db_item(dbitem, included)
                    for dbitem in query.all()
                ]
                # Included objects
                if self.requested_include_names():
                    doc.included = [obj for obj in included.values()]
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest(str(exc.orig))
        for item in data:
            res = pyramid_jsonapi.jsonapi.Resource()
            res.update(item)
            doc.resources.append(res)
        results['returned'] = len(doc.resources)

        doc.meta = {'results': results}
        return doc

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
            # order_att will be a sqlalchemy.orm.properties.ColumnProperty if
            # sort_keys[0] is the name of an attribute or a
            # sqlalchemy.orm.relationships.RelationshipProperty if sort_keys[0]
            # is the name of a relationship.
            if hasattr(order_att, 'property') and isinstance(order_att.property, RelationshipProperty):
                # If order_att is a relationship then we need to add a join to
                # the query and order_by the sort_keys[1] column of the
                # relationship's target. The default target column is 'id'.
                query = query.join(order_att)
                rel = order_att.property
                try:
                    sub_key = sort_keys[1]
                except IndexError:
                    # Use the relationship
                    sub_key = self.view_instance(
                        rel.tgt_class
                    ).key_column.name
                order_att = getattr(rel.obj.mapper.entity, sub_key)
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
        limit_comps = ['limit', 'relationships', relationship.obj.key]
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
        query = self. dbsession.query(
            rel.tgt_class
        ).join(proxy.remote_attr).filter(
            # I thought the simpler
            # proxy.local_attr.contains() should work but it doesn't
            proxy.local_attr.property.local_remote_pairs[0][1] == obj_id
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
        rel = relationship.obj
        rel_class = rel.mapper.class_
        rel_view = self.view_instance(rel_class)
        local_col, rem_col = rel.local_remote_pairs[0]
        query = self.dbsession.query(rel_class)
        if full_object:
            query = query.options(
                load_only(*rel_view.allowed_requested_query_columns.keys())
            )
        else:
            query = query.options(load_only(rel_view.key_column.name))
        if rel.direction is ONETOMANY:
            query = query.filter(obj_id == rem_col)
        elif rel.direction is MANYTOMANY:
            query = query.filter(
                obj_id == rel.primaryjoin.right
            ).filter(
                self.id_col(rel_class) == rel.secondaryjoin.right
            )
        elif rel.direction is MANYTOONE:
            if rel.primaryjoin.left.table == rel.primaryjoin.right.table:
                # This is a self-joined table with a child->parent rel. AKA
                # adjacancy list. We need aliasing.
                rel_class_alias = aliased(rel_class)

                # Assume a 'Node' model with 'id' and 'parent_id' attributes and
                # a relationship 'parent' such that parent_id stores the id of
                # this Node's parent.
                #
                # The parent_id column from the aliased class.
                right_alias = getattr(rel_class_alias, rel.primaryjoin.right.key)
                # The id column from the aliased class.
                left_alias = getattr(rel_class_alias, rel.primaryjoin.left.key)

                query = query.join(
                    rel_class_alias,
                    # Node.id == Aliased.parent_id
                    rel.primaryjoin.left == right_alias
                ).filter(
                    # Aliased.id == obj_id
                    left_alias == obj_id
                )
            else:
                query = query.filter(
                    rel.primaryjoin
                ).filter(
                    self.id_col(self.model_from_table(local_col.table)) == obj_id
                )
        else:
            raise HTTPError('Unknown relationships direction, "{}".'.format(
                rel.direction.name
            ))

        return query
        # rel = relationship.obj
        # rel_class = rel.mapper.class_
        # rel_view = self.view_instance(rel_class)
        # local_col, rem_col = rel.local_remote_pairs[0]
        # query = self.dbsession.query(rel_class)
        # if full_object:
        #     query = query.options(
        #         load_only(*rel_view.allowed_requested_query_columns.keys())
        #     )
        # else:
        #     query = query.options(load_only(rel_view.key_column.name))
        # if rel.direction is MANYTOMANY:
        #     query = query.filter(
        #         rel.secondaryjoin
        #     )
        # elif rel.direction is MANYTOONE or rel.direction is ONETOMANY:
        #     query = query.join(
        #         relationship.instrumented
        #     )
        # else:
        #     raise HTTPError('Unknown relationships direction, "{}".'.format(
        #         rel.direction.name
        #     ))
        # query = query.filter(obj_id == rel.primaryjoin.right)
        #
        # return query

    def related_query(self, obj_id, relationship, full_object=True):
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
            item = self.dbsession.query(
                self.model
            ).options(
                load_only(self.key_column.name)
            ).get(obj_id)
        except (sqlalchemy.exc.DataError, sqlalchemy.exc.StatementError):
            item = False
        return bool(item)

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

    def serialise_resource_identifier(self, obj_id):
        """Return a resource identifier dictionary for id "obj_id"

        """
        ret = {
            'type': self.collection_name,
            'id': str(obj_id)
        }

        for callback in self.callbacks['after_serialise_identifier']:
            ret = callback(self, ret)

        return ret

    def serialise_db_item(
            self, item,
            included, include_path=None,
    ):
        """Serialise an individual database item to JSON-API.

        Arguments:
            item: item to serialise.

        Keyword Arguments:
            included (dict): dictionary to be filled with included resource
                objects.
            include_path (list): list tracking current include path for
                recursive calls.

        Returns:
            jsonapi.Resource:
        """

        include_path = include_path or []

        # Item's id and type are required at the top level of json-api
        # objects.
        # The item's id.
        item_id = self.id_col(item)
        # JSON API type.
        item_url = self.request.route_url(
            self.api.endpoint_data.make_route_name(self.collection_name, suffix='item'),
            **{'id': item_id}
        )

        resource_json = pyramid_jsonapi.jsonapi.Resource(self)
        resource_json.id = str(item_id)
        resource_json.attributes = {
            key: getattr(item, key)
            for key in self.requested_attributes.keys()
            if self.mapped_info_from_name(key).get('visible', True)
        }
        resource_json.links = {'self': item_url}

        rels = {}
        for key, rel in self.relationships.items():
            is_included = False
            if '.'.join(include_path + [key]) in self.requested_include_names():
                is_included = True
            if key not in self.requested_relationships and not is_included:
                continue
            if not self.mapped_info_from_name(key).get('visible', True):
                continue

            rel_dict = {
                'data': None,
                'links': {
                    'self': '{}/relationships/{}'.format(item_url, key),
                    'related': '{}/{}'.format(item_url, key)
                },
                'meta': {
                    'direction': rel.direction.name,
                    'results': {}
                }
            }
            rel_view = self.view_instance(rel.tgt_class)

            query = self.related_query(item_id, rel, full_object=is_included)

            many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
            if many:
                limit = self.related_limit(rel)
                rel_dict['meta']['results']['limit'] = limit
                query = query.limit(limit)

            data = []
            ritems = query.all()
            if not many and len(ritems) > 1:
                raise HTTPInternalServerError("Multiple results for TOONE relationship.")

            for ritem in ritems:
                data.append(
                    rel_view.serialise_resource_identifier(
                        self.id_col(ritem)
                    )
                )
                if is_included:
                    included[
                        (rel_view.collection_name, self.id_col(ritem))
                    ] = rel_view.serialise_db_item(
                        ritem,
                        included, include_path + [key]
                    )
            if many:
                rel_dict['meta']['results']['available'] = query.count()
                rel_dict['meta']['results']['returned'] = len(data)
                rel_dict['data'] = data
            else:
                if data:
                    rel_dict['data'] = data[0]

            if key in self.requested_relationships:
                rels[key] = rel_dict

        resource_json.relationships = rels

        for callback in self.callbacks['after_serialise_object']:
            callback(self, resource_json)

        return resource_json.as_dict()

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
        info['page[offset]'] = int(request.params.get('page[offset]', 0))

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
            k: v for k, v in itertools.chain(
                self.attributes.items(), self.hybrid_attributes.items()
            )
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
        return self.api.view_classes[model](self.request)

    @classmethod
    def append_callback_set(cls, set_name):
        """Append a named set of callbacks from ``callback_sets``.

        Args:
            set_name (str): key in ``callback_sets``.
        """
        for cb_name, callback in cls.callback_sets[set_name].items():
            cls.callbacks[cb_name].append(callback)

    def acso_after_serialise_object(view, obj):  # pylint:disable=no-self-argument
        """Standard callback altering object to take account of permissions.

        Args:
            obj (dict): the object immediately after serialisation.

        Returns:
            dict: the object, possibly with some fields removed, or meta
            information indicating permission was denied to the whole object.
        """
        if view.allowed_object(obj):
            # Remove any forbidden fields that have been added by other
            # callbacks. Those from the model won't have been added in the first
            # place.

            # Keep track so we can tell the caller which ones were forbidden.
            forbidden = set()
            for attr in ('attributes', 'relationships'):
                if hasattr(obj, attr):
                    new = {}
                    for name, val in getattr(obj, attr).items():
                        if name in view.allowed_fields:
                            new[name] = val
                        else:
                            forbidden.add(name)
                    setattr(obj, attr, new)
            # Now add all the forbidden fields from the model to the forbidden
            # list. They don't need to be removed from the serialised object
            # because they should not have been added in the first place.
            for field in view.requested_field_names:
                if field not in view.allowed_fields:
                    forbidden.add(field)
            if not hasattr(obj, 'meta'):
                obj.meta = {}
            obj.meta['forbidden_fields'] = list(forbidden)
        else:
            obj.meta = {
                'errors': [
                    {
                        'code': 403,
                        'title': 'Forbidden',
                        'detail': 'No permission to view {}/{}.'.format(
                            obj.type, obj.id
                        )
                    }
                ]
            }
        return obj

    def acso_after_get(view, ret):  # pylint:disable=unused-argument, no-self-argument, no-self-use
        """Standard callback throwing 403 (Forbidden) based on information in meta.

        Args:
            ret (jsonapi.Document): object which would have been returned from get().

        Returns:
            jsonapi.Document: the same object if an error has not been raised.

        Raises:
            HTTPForbidden
        """
        obj = ret
        errors = []
        try:
            errors = obj.meta['errors']
        except KeyError:
            return ret
        for error in errors:
            if error['code'] == 403:
                raise HTTPForbidden(error['detail'])
        return ret

    callback_sets = {
        'access_control_serialised_objects': {
            'after_serialise_object': acso_after_serialise_object,
            'after_get': acso_after_get
        }
    }
