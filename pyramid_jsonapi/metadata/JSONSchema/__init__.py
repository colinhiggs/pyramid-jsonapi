"""JSONSchema metadata plugin.

This plugin provides JSONSchema schemas and validation.

This module provides 3 ``metadata`` views:

* ``JSONSchema``  - The full JSONSchema for JSONAPI (as provided by jsonapi.org)
* ``JSONSchema/endpoint/{endpoint}`` - JSONSchema for a specific endpoint, with attributes defined.
* ``JSONSchema/resource/{resource}`` -  JSONSchema of just the attributes for a resource.

Configuration
-------------

This plugin uses `alchemyjsonschema <https://github.com/podhmo/alchemyjsonschema>`_
to provide mapping between pyramid model and JSONSchema types.

``alchemyjsonschema`` provides a ``default_column_to_schema`` dictionary, which maps
column types to jsonschema types. If you wish to extend this, you can do so by importing
this module and modifying this constant prior to importing pyramid_jsonapi.
For example, to extend the default mapping to include ``uuid`` types:

.. code-block:: python

    import alchemyjsonschema

    alchemyjsonschema.default_column_to_schema.update(
        {
            sqlalchemy_utils.types.uuid.UUIDType: "string"
        }
    )

    jsonapi = pyramid_jsonapi.PyramidJSONAPI(config, models)


Endpoint View
-------------

The endpoint view expects the path to include the endpoint in question, and 3 query parameters must be provided:

* method - http method (GET, POST etc)
* direction - 'request' or 'response'
* code - http status code (if direction is 'response')

For example:

``https://localhost:6543/metadata/JSONSchema/endpoint/people?method=get&direction=response&code=200``

Will return the schema that matches a valid response (200 OK) to a GET to ``/api/people``
"""

import functools
import json
import logging
import pkgutil
import sys

# Dict and deepcopy performance in python < 3.6 is lacking
# pickle/unpickle hack gives much better performance.
if sys.version_info.minor >= 6:
    from copy import deepcopy
else:
    import pickle
    deepcopy = lambda x: pickle.loads(pickle.dumps(x, -1))  # pylint:disable=invalid-name

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
        self.schema_post = {}
        self.load_schema()
        self.build_definitions()

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
        # POSTs can omit the id
        self.schema_post = json.loads(schema)
        try:
            # Custom schemas may not have this structure
            self.schema_post['definitions']['resource']['required'].remove('id')
        except (IndexError, KeyError):
            pass

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
        endpoint = request.matchdict['endpoint']
        try:
            return self.resource_attributes(endpoint)
        except IndexError:
            raise HTTPNotFound("Invalid endpoint specified: {}.".format(endpoint))

    @functools.lru_cache()
    def resource_attributes(self, endpoint):
        """Return jsonschema attributes for a specific resource.

        Parameters:
            endpoint (str): endpoint to obtain schema for.

        Returns:
            Dictionary containing jsonschema attributes for the endpoint.
        """
        # Hack relevant view_class out of endpoint name
        view_class = [x for x in self.api.view_classes.values() if x.collection_name == endpoint][0]
        classifier = alchemyjsonschema.Classifier(mapping=self.column_to_schema)
        factory = alchemyjsonschema.SchemaFactory(alchemyjsonschema.NoForeignKeyWalker,
                                                  classifier=classifier)
        schema = {}
        try:
            schema.update(factory(view_class.model))
        except alchemyjsonschema.InvalidStatus as exc:
            logging.warning("Schema Error: %s", exc)

        # Remove 'id' attribute
        # (returned by db, but not stored in attrs in jsonapi)
        if 'properties' in schema:
            if 'id' in schema['properties']:
                del schema['properties']['id']
            if 'required' in schema:
                if 'id' in schema['required']:
                    schema['required'].remove('id')
                # Empty required list is invalid jsonschema
                if not schema['required']:
                    del schema['required']

        return schema

    def endpoint_schema_view(self, request):
        """Pyramid view for endpoint_schema.

        Parameters:
            request: Pyramid Request object.

        Returns:
            Results of endpoint_schema() method call.

        Raises:
            HTTPNotFound error for unknown endpoints.

        Takes 1 path parameert:
          * 'endpoint'

        Takes 3 optional query parameters:
          * 'method': http method (defaults to get)
          * 'direction': request or response (defaults to response)
          * 'code': http status code
        """

        endpoint = request.matchdict['endpoint']
        method = request.params.get('method')
        direction = request.params.get('direction')
        code = request.params.get('code')
        return self.endpoint_schema(endpoint, method, direction, code)

    def endpoint_schema(self, endpoint, method, direction, code):
        """Generate a full schema for an endpoint.

        Parameters:
            endpoint (string): Endpoint name
            method (string): http method (defaults to 'get')
            direction (string): request or response (defaults to response)
            code (string): http status code

        Returns:
            JSONSchema (dict)
        """

        try:
            method = method.lower()
            direction = direction.lower()
            code = int(code)
        except (AttributeError, ValueError):
            raise HTTPBadRequest("Invalid parameters specified")

        # reject invalid endpoints
        if not "{}_attrs".format(endpoint) in self.schema['definitions']:
            raise HTTPNotFound("Invalid endpoint specified: {}.".format(endpoint))

        success = deepcopy(self.schema['definitions']['success'])

        if direction == 'response' and code >= 400:
            # Return reference to failure part of schema
            return {'$ref': '#/definitions/failure'}

        if direction == 'request':
            # Replace data with single (ep-specific) resource
            # (POST/PATCH can only be single resource)
            success['properties'] = {
                'data': {'$ref': '#/definitions/{}_attrs'.format(endpoint)}
            }
        else:  # direction == response
            # Replace data with ep-specific data ref
            success['properties']['data'] = {'$ref': '#/definitions/{}_data'.format(endpoint)}

        return success

    def validate(self, json_body, method='get'):
        """Validate schema against jsonschema."""

        method = method.lower()
        # TODO: How do we validate PATCH requests?
        if method != 'patch':
            schm = self.schema
            if method == 'post':
                schm = self.schema_post
            try:
                jsonschema.validate(json_body, schm)
            except (jsonschema.exceptions.ValidationError) as exc:
                raise HTTPBadRequest(str(exc))
            except Exception as exc:
                from pyramid.httpexceptions import HTTPInternalServerError
                raise HTTPInternalServerError(str(exc))

    def build_definitions(self):
        """Build data and attribute references for all endpoints,
        and updates the 'global' schema.
        """

        for view_class in self.api.view_classes.values():
            endpoint = view_class.collection_name

            # Get attributes for this endpoint
            attrs = self.resource_attributes(endpoint)

            # Add a resource definition for this endpoint to the 'global' schema
            attr_ref = {'$ref': '#/definitions/{}_attrs'.format(endpoint)}
            resource = deepcopy(self.schema['definitions']['resource'])
            resource['properties']['attributes'] = attrs
            resource['properties']['type']['pattern'] = "^{}$".format(endpoint)
            self.schema['definitions']["{}_attrs".format(endpoint)] = resource

            # Add a data definition for this endpoint to the 'global' schema
            ep_data = deepcopy(self.schema['definitions']['data'])
            # Data can be a single resource...
            ep_data['oneOf'][0] = attr_ref
            # Or an array.
            ep_data['oneOf'][1]['items'] = attr_ref
            self.schema['definitions']["{}_data".format(endpoint)] = ep_data
