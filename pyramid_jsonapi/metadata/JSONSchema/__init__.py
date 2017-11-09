"""JSONSchema metadata plugin."""

import copy
import functools
import json
import logging
import pkgutil

import alchemyjsonschema
import jsonschema
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPNotFound
)
from pyramid_jsonapi.metadata import VIEWS


class JSONSchema():
    """Metadata plugin to generate and validate JSONSchema for sqlalchemy,
    using alchemyjsonschema to map sqlalchemy types.
    """

    def __init__(self, api):
        """
        Parameters:
            api: A PyramidJSONAPI class instance
        Attributes:
            views (list): VIEWS named tuples associating methods with views
            column_to_schema (dict): alchemyjsonschema column to schema mapping.
                This defaults to alchemyjsonschema.default_column_to_schema,
                but can be extended or overridden.

            For example, to add a mapping of 'JSONB' to 'string'::
                from sqlalchemy.dialects.postgresql import JSONB
                self.column_to_schema[JSONB] = 'string'
        """

        self.views = [
            VIEWS(
                attr='template',
                route_name='',
                request_method='',
                renderer=''
            ),
            VIEWS(
                attr='resource_attributes_view',
                route_name='resource/{endpoint}',
                request_method='',
                renderer=''
            ),
            VIEWS(
                attr='endpoint_schema_view',
                route_name='endpoint/{endpoint}{sep:/?}{method:.*}',
                request_method='',
                renderer=''
            ),
        ]
        self.api = api
        self.column_to_schema = alchemyjsonschema.default_column_to_schema
        self.schema = {}
        self.load_schema()

    def template(self, request=None):  # pylint:disable=unused-argument
        """Return the JSONAPI jsonschema dict (as a pyramid view).

        Parameters:
            request (optional): Pyramid Request object.

        Returns:
            JSONAPI schema document.
        """
        return self.schema

    def load_schema(self):
        """Load the JSONAPI jsonschema from file.

        Reads 'pyramid_jsonapi.schema_file' from config,
        or defaults to one provided with the package.
        """
        schema_file = self.api.settings.schema_file
        if schema_file:
            with open(schema_file) as schema_f:
                schema = schema_f.read()
        else:
            schema = pkgutil.get_data(
                self.api.__module__,
                'schema/jsonapi-schema.json'
            ).decode('utf-8')
        self.schema = json.loads(schema)

    def resource_attributes_view(self, request):
        """Call resource() via a pyramid view.
        Parameters:
            request: Pyramid Request object.

        Returns:
            Results of resource_attributes() method call.

        Raises:
            HTTPNotFound error for unknown endpoints.
        """
        # Extract endpoint from route pattern, use to get resource schema, return this
        try:
            return self.resource_attributes(endpoint=request.matchdict['endpoint'])
        except IndexError:
            raise HTTPNotFound

    @functools.lru_cache()
    def resource_attributes(self, endpoint):
        """Return jsonschema attributes for a specific resource.

        Parameters:
            endpoint (str): endpoint to obtain schema for.

        Returns:
            Dictionary containing jsonschema attributes for the endpoint.
        """
        # Hack relevant view_class out of endpoint name
        try:
            view_class = [x for x in self.api.view_classes.values() if x.collection_name == endpoint][0]
        except IndexError:
            raise HTTPNotFound("Invalid endpoint specified: {}.".format(endpoint))
        classifier = alchemyjsonschema.Classifier(mapping=self.column_to_schema)
        factory = alchemyjsonschema.SchemaFactory(alchemyjsonschema.NoForeignKeyWalker,
                                                  classifier=classifier)
        schema = {}
        try:
            schema.update(factory(view_class.model))
        except alchemyjsonschema.InvalidStatus as exc:
            logging.warning("Schema Error: %s", exc)

        # Remove 'id' attribute
        if 'properties' in schema:
            del schema['properties']['id']
            if 'id' in schema['required']:
                schema['required'].remove('id')

        return schema

    def endpoint_schema_view(self, request):
        """Pyramid view for endpoint_schema.
        Parameters:
            request: Pyramid Request object.

        Returns:
            Results of endpoint_schema() method call.

        Raises:
            HTTPNotFound error for unknown endpoints.

        Takes 2 path params: endpoint[/method] (defaults to get).
        """

        endpoint = request.matchdict['endpoint']
        method = request.matchdict.get('method')
        return self.endpoint_schema(endpoint, method)

    def endpoint_schema(self, endpoint, method):
        """Generate a full schema for an endpoint.

        Parameters:
            endpoint (string): Endpoint name
            method (string): http method (defaults to 'get')

        Returns:
            JSONSchema (dict)
        """

        if not method:
            method = 'get'
        method = method.lower()

        schema = copy.deepcopy(self.schema)
        if method == 'post':
            schema['definitions']['resource']['required'].remove('id')

        attrs = self.resource_attributes(endpoint)
        props = schema['definitions']['resource']['properties']
        props['attributes'] = attrs
        props['type']['pattern'] = "^{}$".format(endpoint)

        return schema

    def validate(self, json_body, method='get'):
        """Validate schema against jsonschema."""

        method = method.lower()
        # TODO: How do we validate PATCH requests?
        if method != 'patch':
            schm = self.schema
            if method == 'post':
                schm = copy.deepcopy(self.schema)
                # POSTs should not have an id
                schm['definitions']['resource']['required'].remove('id')
            try:
                jsonschema.validate(json_body, schm)
            except (jsonschema.exceptions.ValidationError) as exc:
                raise HTTPBadRequest(str(exc))
