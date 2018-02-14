"""Generate OpenAPI documentation from Models, Schema and Endpoint info.

This module provides 2 ``metadata`` views:

* ``OpenAPI`` - the Swagger UI.
* ``OpenAPI/specification`` - the project OpenAPI specification (JSON).

Configuration
-------------

The config option ``openapi_file`` can be used to provide a JSON or YAML
file which will be used to update the dynamically generated documentation.

Metadata for the OpenAPI documentation will be extracted from the ``PKG-INFO``
data provided with the pyramid package that is using ``pyramid_jsonapi``,
using the ``pkginfo`` module. This requires that the pyramid package can be
located in the python path (i.e it can be imported).

Documentation is dynamically generated from several sources:

* Endpoint data -> endpoints, parameters, request and response content.
* Model docstrings -> endpoint descriptions.
* sqlalchemy columns -> schemas (via JSONSchema module).

"""

import functools
import pkginfo
import yaml
from pyramid.renderers import JSON

from pyramid_jsonapi.metadata import VIEWS


class OpenAPI():
    """Auto-generate OpenAPI documentation."""

    def __init__(self, api):
        self.api = api
        self.metadata = {}
        # Load mako templating
        self.api.config.include('pyramid_mako')
        self.api.config.add_renderer('json_sorted', JSON(sort_keys=True))

        self.views = [
            VIEWS(
                attr='openapi_spec',
                route_name='specification',
                request_method='',
                renderer='json_sorted'
            ),
            VIEWS(
                attr='swagger_ui',
                route_name='',
                request_method='',
                renderer='pyramid_jsonapi.metadata.OpenAPI:swagger-ui/index.mako'
            )
        ]

    @staticmethod
    def swagger_ui(request):
        """Dynamically generate the swagger-ui index.html

        Parameters:
            request (optional): Pyramid Request object.

        Returns:
            dict containing variables for template substitution.
        """

        return {'openapi_url': "{}/specification".format(request.current_route_url())}

    def openapi_spec(self, request=None):  # pylint:disable=unused-argument
        """Return the OpenAPI specification dict (as a pyramid view).

        Parameters:
            request (optional): Pyramid Request object.

        Returns:
            OpenAPI template document.
        """

        return self.generate_openapi(request=request)

    @functools.lru_cache()
    def generate_pkg_metadata(self):
        """Get metadatsa for 'parent' pyramid package."""
        # Get the PKG-INFO metadata for the 'parent' pyramid app
        pkg_name = self.api.config.package_name
        self.metadata = pkginfo.Installed(pkg_name)

    @staticmethod
    def build_content(schema, description='', mediatype='application/vnd.api+json'):
        """Construct a content dictionary for a given schema."""

        return {
            'description': description,
            'content': {
                mediatype: {
                    'schema': schema
                }
            }
        }

    def build_parameters(self, opts):
        """Build paramaters schema."""

        # Add 'in: query' parameters - 'global' and ep-specific
        parameters = []
        for param, val in self.api.endpoint_data.endpoints['query_parameters'].items():
            schema = {}
            if isinstance(val, list):
                schema['type'] = 'array'
                schema['items'] = {'type': 'string',
                                   'pattern': '|'.join(["^{}$".format(x) for x in val])}
            else:
                schema['type'] = 'string'
            q_param = {
                'name': param,
                'in': 'query',
                'schema': schema,
            }
            parameters.append(q_param)

        # Add 'in: path' parameters extracted from route_pattern
        if 'route_pattern' in opts:
            for field in opts['route_pattern']['fields']:
                parameters.append({
                    'name': field,
                    'in': 'path',
                    'required': True,
                    'schema': {
                        'type': 'string'
                    }
                })
        return parameters

    def build_request(self, name, method):
        """Build requestBody part of schema."""

        content = self.api.metadata.JSONSchema.endpoint_schema(
            name,
            method.lower(),
            'request',
            '999'  # Code is irrelevant for requests
        )

        return self.build_content(content)

    def build_responses(self, name, ep_type, method):
        """Build responses part of schema."""
        responses = {}
        resp_data = dict()
        for resps in self.api.endpoint_data.find_all_keys('responses', ep_type, method):
            for http_class, opts in resps.items():
                if http_class not in resp_data:
                    resp_data[http_class] = opts['reason']
                else:
                    resp_data[http_class].extend(opts['reason'])
            for response, reason in resp_data.items():
                responses[str(response.code)] = self.build_content(
                    self.api.metadata.JSONSchema.endpoint_schema(
                        name,
                        method.lower(),
                        'response',
                        response.code
                    ),
                    description="\n\n".join(set(reason)),
                )
        return responses

    def recurse_remove_keys(self, dictionary, name):
        """Recursively build a new version of dictionary with named keys removed."""
        new_dict = {}
        for key, value in dictionary.items():
            if key != name:
                if isinstance(value, dict):
                    new_dict[key] = self.recurse_remove_keys(value, name)
                else:
                    new_dict[key] = value
        return new_dict

    def replace_in_value_inner(self, val, old, new):
        """Inner part of recurse_replace_in_value."""
        if isinstance(val, (dict, list, tuple)):
            return self.recurse_replace_in_value(val, old, new)
        elif isinstance(val, str):
            return val.replace(old, new)
        return val

    def recurse_replace_in_value(self, obj, old, new):
        """Recursively replace() strings in values."""
        if isinstance(obj, dict):
            new_obj = {}
            for key, val in obj.items():
                new_obj[key] = self.replace_in_value_inner(val, old, new)
        elif isinstance(obj, (list, tuple)):
            new_obj = []
            for val in obj:
                new_obj.append(self.replace_in_value_inner(val, old, new))
        return new_obj

    @functools.lru_cache()
    def generate_openapi(self, request=None):
        """Generate openapi documentation."""

        # OpenAPI 'template'
        openapi = {
            # OpenAPI specification version
            'openapi': '3.0.0',
            'paths': {},
        }

        self.generate_pkg_metadata()

        openapi['info'] = {
            'title': self.metadata.name or '',
            'description': self.metadata.description or '',
            'version': self.api.settings.api_version or self.metadata.version or '',
            'contact': {
                'name': self.metadata.author or '',
                'email': self.metadata.author_email or '',
                'url': self.metadata.home_page or ''
            },
            'license': {
                'name': self.metadata.license or ''
            }
        }

        ep_data = self.api.endpoint_data

        # Split the route_path using the metadata_pattern.
        # any prefixes are then prefixed to path_name later
        # This handles hosting from a sub-directory.
        base_path = None
        if request:
            path_pattern = ep_data.rp_constructor.metadata_pattern('OpenAPI')
            base_path, _ = request.current_route_path().split(path_pattern, 1)

        paths = {}
        # Iterate through all view_classes, getting name (for path)
        for model, view_class in self.api.view_classes.items():
            name = view_class.collection_name
            # Iterate through endpoints, adding paths and methods
            for ep_type, opts in ep_data.endpoints['endpoints'].items():
                # Add appropriate suffix to path endpoint
                path_name = ep_data.rp_constructor.api_pattern(
                    name,
                    ep_data.route_pattern_to_suffix(
                        opts.get('route_pattern', {})
                    ),
                    base=base_path or '/',
                )
                paths[path_name] = {}
                for method in opts['http_methods']:
                    paths[path_name][method.lower()] = {}
                    paths[path_name][method.lower()]['parameters'] = self.build_parameters(opts)
                    if opts['http_methods'][method].get('request_schema', False):
                        paths[path_name][method.lower()]['requestBody'] = self.build_request(name, method)
                    if opts['http_methods'][method].get('response_schema', True):
                        paths[path_name][method.lower()]['responses'] = self.build_responses(name, ep_type, method)

                    # Add description
                    paths[path_name][method.lower()]['description'] = model.__doc__ or ''

        # Add 'paths' to the openapi spec
        openapi['paths'].update(paths)

        # Add the JSONSchema JSONAPI definitions to the openapi spec
        openapi.update({'x-definitions': self.api.metadata.JSONSchema.template()['definitions']})

        # Update openapi dict from external yaml/json file, if provided in config.
        openapi_file = str(self.api.settings.openapi_file)
        if openapi_file:
            with open(openapi_file) as oa_f:
                openapi.update(yaml.safe_load(oa_f.read()))

        # TODO: patternProperties not supported in openapi, so remove all occurrences
        # https://github.com/OAI/OpenAPI-Specification/issues/687
        openapi = self.recurse_remove_keys(openapi, 'patternProperties')

        # Re-map all definitions refs to x-definitions
        openapi = self.recurse_replace_in_value(openapi, 'definitions', 'x-definitions')

        return openapi
