"""Classes to store and manipulate endpoints and routes."""

from functools import partial, lru_cache
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPCreated,
    HTTPConflict,
    HTTPFailedDependency,
    HTTPForbidden,
    HTTPInternalServerError,
    HTTPNotAcceptable,
    HTTPNotFound,
    HTTPOk,
    HTTPUnsupportedMediaType,
)


class RoutePatternConstructor():
    """Construct pyramid_jsonapi route patterns."""

    def __init__(self, api):
        self.api = api
        self.settings = self.api.settings
        # type-specific methods that wrap create_pattern
        self.api_pattern = partial(self.create_pattern, self.settings.route_pattern_api_prefix)
        self.metadata_pattern = partial(self.create_pattern, self.settings.route_pattern_metadata_prefix)

    def pattern_from_components(self, *components, start_sep=False, end_sep=False):
        """Construct a route pattern from components.

        Join components together with self.sep.
        Remove all occurrences of '', and strip extra separators.

        Arguments:
            *components (str): route pattern components.
            start_sep (bool): Add a leading separator
            end_sep (bool): Add a trailing separator
        """
        psep = self.settings.route_pattern_sep
        components = [x for x in components if x != '']
        pattern = psep.join(components).replace(psep * 2, psep)
        if start_sep and not pattern.startswith(psep):
            pattern = '{}{}'.format(psep, pattern)
        if end_sep and not pattern.endswith(psep):
            pattern = '{}{}'.format(pattern, psep)
        return pattern

    def create_pattern(self, type_prefix, endpoint_name, *components, base='/', rstrip=True):
        """Generate a pattern from a type_prefix, endpoint name and suffix components.

        This method is not usually called directly.  Instead, the wrapping
        `api_pattern` and `metadata_pattern` partial methods are used.

        Arguments:
            type_prefix (str): api or metadataprefix (see 'partial' methods).
            endpoint_name (str): An endpoint name.
            base (str): Base string to prepend to pattern (defaults to '/').
            rstrip (bool): Strip trailing separator (defaults to True).
            *components (str): components to add after collection name.
        """
        pattern = self.pattern_from_components(
            base,
            self.settings.route_pattern_prefix,
            self.settings.api_version,
            type_prefix,
            endpoint_name,
            *components
        )
        if rstrip:
            pattern = pattern.rstrip(self.settings.route_pattern_sep)
        return pattern


class EndpointData():
    """Class to hold endpoint data and utility methods.

    Arguments:
        api: A PyramidJSONAPI object.

    """

    def __init__(self, api):
        self.config = api.config
        self.settings = api.settings
        self.rp_constructor = RoutePatternConstructor(api)

        # Mapping of endpoints, http_methods and options for constructing routes and views.
        # Update this dictionary prior to calling create_jsonapi()
        # 'responses' can be 'global', 'per-endpoint' and 'per-endpoint-method'
        # Mandatory 'endpoint' keys: http_methods
        # Optional 'endpoint' keys: route_pattern
        # Mandatory 'http_method' keys: function
        # Optional 'http_method' keys: renderer
        self.endpoints = {
            'http_method_sets': {
                'read': {'get'},
                'write': {'post', 'patch', 'delete'},
            },
            'query_parameters': {
                'fields': '',
                'filter': '',
                'page': ['limit', 'offset'],
                'sort': '',
            },
            'responses': {
                # Top-level: apply to all endpoints
                HTTPUnsupportedMediaType: {'reason': ['Servers MUST respond with a 415 Unsupported Media Type status code if a request specifies the header Content-Type: application/vnd.api+json with any media type parameters.']},
                HTTPNotAcceptable: {'reason': ['Servers MUST respond with a 406 Not Acceptable status code if a request’s Accept header contains the JSON API media type and all instances of that media type are modified with media type parameters.']},
                HTTPBadRequest: {'reason': ['If a server encounters a query parameter that does not follow the naming conventions above, and the server does not know how to process it as a query parameter from this specification, it MUST return 400 Bad Request.',
                                            'If the server does not support sorting as specified in the query parameter sort, it MUST return 400 Bad Request.',
                                            'If an endpoint does not support the include parameter, it MUST respond with 400 Bad Request to any requests that include it.',
                                            'If the request content is malformed in some way.']},
                HTTPForbidden: {'reason': ['The authenticated user is not allowed to access the resource in this way.']},
            },
            'endpoints': {
                'collection': {
                    'responses': {
                        HTTPInternalServerError: {'reason': ['An error occurred on the server.']}
                    },
                    'http_methods': {
                        'GET': {
                            'function': 'collection_get',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']},
                            },
                        },
                        'POST': {
                            'function': 'collection_post',
                            'request_schema': True,
                            'responses': {
                                HTTPCreated: {'reason': ['If a POST request did not include a Client-Generated ID and the requested resource has been created successfully, the server MUST return a 201 Created status code.']},
                                HTTPForbidden: {'reason': ['A server MUST return 403 Forbidden in response to an unsupported request to create a resource with a client-generated ID.',
                                                           'A server MAY return 403 Forbidden in response to an unsupported request to create a resource.']},
                                HTTPNotFound: {'reason': ['A server MUST return 404 Not Found when processing a request to modify a resource that does not exist.',
                                                          'A server MUST return 404 Not Found when processing a request that references a related resource that does not exist.']},
                                HTTPConflict: {'reason': ['A server MUST return 409 Conflict when processing a POST request to create a resource with a client-generated ID that already exists.',
                                                          'A server MUST return 409 Conflict when processing a POST request in which the resource object’s type is not among the type(s) that constitute the collection represented by the endpoint.']},
                                HTTPBadRequest: {'reason': ['Request is malformed in some way.']},
                            },
                        },
                    },
                },
                'item': {
                    'responses': {
                        HTTPInternalServerError: {'reason': ['An error occurred on the server.']}
                    },
                    'route_pattern': {'fields': ['id'], 'pattern': '{{{}}}'},
                    'http_methods': {
                        'DELETE': {
                            'function': 'item_delete',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST return a 200 OK status code if a deletion request is successful and the server responds with only top-level meta data.']},
                                HTTPNotFound: {'reason': ['A server SHOULD return a 404 Not Found status code if a deletion request fails due to the resource not existing.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by deleting the specified resource from the relationship.']},
                            },
                        },
                        'GET': {
                            'function': 'item_get',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']},
                                HTTPNotFound: {'reason': ['A server MUST respond with 404 Not Found when processing a request to fetch a single resource that does not exist.']},
                            },
                        },
                        'PATCH': {
                            'function': 'item_patch',
                            'request_schema': True,
                            'responses': {
                                HTTPOk: {'reason': ['If an update is successful and the server doesn’t update any attributes besides those provided, the server MUST return either a 200 OK status code and response document']},
                                HTTPForbidden: {'reason': ['A server MUST return 403 Forbidden in response to an unsupported request to update a resource or relationship.']},
                                HTTPNotFound: {'reason': ['A server MUST return 404 Not Found when processing a request to modify a resource that does not exist.',
                                                          'A server MUST return 404 Not Found when processing a request that references a related resource that does not exist.']},
                                HTTPBadRequest: {'reason': ['Request is malformed in some way.']},
                                HTTPConflict: {'reason': ['A server MAY return 409 Conflict when processing a PATCH request to update a resource if that update would violate other server-enforced constraints (such as a uniqueness constraint on a property other than id).',
                                                          'A server MUST return 409 Conflict when processing a PATCH request in which the resource object’s type and id do not match the server’s endpoint.']},
                            },
                        },
                    },
                },
                'related': {
                    'responses': {
                        HTTPBadRequest: {'reason': ['If a server is unable to identify a relationship path or does not support inclusion of resources from a path, it MUST respond with 400 Bad Request.']},
                    },
                    'route_pattern': {'fields': ['id', 'relationship'], 'pattern': '{{{}}}{sep}{{{}}}'},
                    'http_methods': {
                        'GET': {
                            'function': 'related_get',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']},
                                HTTPBadRequest: {'reason': ['A bad filter is used.']},
                            }
                        },
                    },
                },
                'relationships': {
                    'responses': {
                        HTTPNotFound: {'reason': ['A server MUST return 404 Not Found when processing a request to fetch a relationship link URL that does not exist.']},
                    },
                    'route_pattern': {'fields': ['id', 'relationship'], 'pattern': '{{{}}}{sep}relationships{sep}{{{}}}'},
                    'http_methods': {
                        'DELETE': {
                            'function': 'relationships_delete',
                            'request_schema': True,
                            'responses': {
                                HTTPOk: {'reason': ['If all of the specified resources are able to be removed from, or are already missing from, the relationship then the server MUST return a successful response.']},
                                HTTPConflict: {'reason': ['A server MUST return 409 Conflict when processing a DELETE request in which the resource object’s type and id do not match the server’s endpoint.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by deleting the specified resource from the relationship.']},
                                HTTPForbidden: {
                                    'reason': [
                                        'If the client makes a DELETE request to a URL from a relationship link the server MUST delete the specified members from the relationship or return a 403 Forbidden response.',
                                        'A server MUST return 403 Forbidden in response to an unsupported request to update a relationship.'
                                    ]
                                },
                            },
                        },
                        'GET': {
                            'function': 'relationships_get',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch a relationship with a 200 OK response.']},
                                HTTPBadRequest: {'reason': ['If a server is unable to identify a relationship path or does not support inclusion of resources from a path, it MUST respond with 400 Bad Request.',
                                                            'A bad filter is used.']},
                            },
                        },
                        'PATCH': {
                            'function': 'relationships_patch',
                            'request_schema': True,
                            'responses': {
                                HTTPOk: {'reason': ['If a server accepts an update but also changes the targeted relationship(s) in other ways than those specified by the request, it MUST return a 200 OK response']},
                                HTTPConflict: {'reason': ['A server MUST return 409 Conflict when processing a PATCH request in which the resource object’s type and id do not match the server’s endpoint.']},
                                HTTPForbidden: {'reason': ['If a client makes a PATCH request to a URL from a to-many relationship link, the server MUST either completely replace every member of the relationship, return an appropriate error response if some resources can not be found or accessed, or return a 403 Forbidden response if complete replacement is not allowed by the server.',
                                                           'A server MUST return 403 Forbidden in response to an unsupported request to update a relationship.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by modifying the specified resource in a relationship.']},
                            },
                        },
                        'POST': {
                            'function': 'relationships_post',
                            'request_schema': True,
                            'responses': {
                                HTTPConflict: {'reason': ['A server MUST return 409 Conflict when processing a POST request in which the resource object’s type is not among the type(s) that constitute the collection represented by the endpoint.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by adding the specified resource to the relationship.']},
                                HTTPForbidden: {'reason': ['A server MUST return 403 Forbidden in response to an unsupported request to update a relationship."']},
                            },
                        },
                    },
                },
            },
        }
        self.endpoints['http_method_sets']['all'] = self.http_methods

    def make_route_name(self, name, suffix=''):
        """Attach prefix and suffix to name to generate a route_name.

        Arguments:
            name: A pyramid route name.

        Keyword Arguments:
            suffix: An (optional) suffix to append to the route name.
        """
        return self.settings.route_name_sep.join(
            (self.settings.route_name_prefix, name, suffix)
        ).rstrip(self.settings.route_name_sep)

    def route_pattern_to_suffix(self, pattern_dict):
        """Convert route_pattern dict to suffix string."""
        if pattern_dict:
            return pattern_dict['pattern'].format(
                sep=self.settings.route_pattern_sep,
                *pattern_dict['fields']
            )
        return ''

    def add_routes_views(self, view):
        """Generate routes and views from the endpoints data object.

        Arguments:
            view: A view_class to associate routes and views with.
        """

        for endpoint, endpoint_opts in self.endpoints['endpoints'].items():
            route_name = self.make_route_name(
                view.collection_name,
                suffix=endpoint
            )
            route_pattern = self.rp_constructor.api_pattern(
                view.collection_name,
                self.route_pattern_to_suffix(
                    endpoint_opts.get('route_pattern', {})
                )
            )
            self.config.add_route(route_name, route_pattern)
            for http_method, method_opts in endpoint_opts['http_methods'].items():
                self.config.add_view(
                    view,
                    attr=method_opts['function'],
                    request_method=http_method,
                    route_name=route_name,
                    renderer=method_opts.get('renderer', 'json')
                )

    def find_all_keys(self, name, ep_type, method):
        """Generator to fetch all the instances of a particular key in part of the tree.

        Parameters:
          ep_type: per-endpoint - e.g. collection, item etc.
          method: http method

          Returns:
            Yields the value of each matching key.
        """

        # top-level instance
        if name in self.endpoints:
            yield self.endpoints[name]
        # ep-type instance
        if name in self.endpoints['endpoints'][ep_type]:
            yield self.endpoints['endpoints'][ep_type][name]
        # method instance
        if name in self.endpoints['endpoints'][ep_type]['http_methods'][method.upper()]:
            yield self.endpoints['endpoints'][ep_type]['http_methods'][method.upper()][name]

    def get_function_name(self, view, http_method, route_pattern):
        """Find the name of the function which handles the given route and method.
        """
        for endpoint, endpoint_opts in self.endpoints['endpoints'].items():
            ep_route_pattern = self.rp_constructor.api_pattern(
                view.collection_name,
                self.route_pattern_to_suffix(
                    endpoint_opts.get('route_pattern', {})
                )
            )
            if ep_route_pattern == route_pattern:
                return endpoint_opts['http_methods'][http_method.upper()]['function']
        raise Exception(
            'No endpoint function found for {}, {}, {},'.format(
                view.collection_name,
                http_method,
                route_pattern,
            )
        )

    @property
    def http_methods(self):
        return {
            hname.lower() for ep_type in self.endpoints['endpoints'].values()
            for hname in ep_type['http_methods']
        }

    @property
    def http_to_view_methods(self):
        ep_map = {}
        for ep_type in self.endpoints['endpoints'].values():
            for http_name, data in ep_type['http_methods'].items():
                http_name = http_name.lower()
                try:
                    view_methods = ep_map[http_name]
                except KeyError:
                    view_methods = ep_map[http_name] = set()
                view_methods.add(data['function'])
        ep_map['write'] = set()
        for m in map(str.lower, self.endpoints['http_method_sets']['write']):
            ep_map['write'] |= ep_map[m]
        ep_map['read'] = set()
        for m in map(str.lower, self.endpoints['http_method_sets']['read']):
            ep_map['read'] |= ep_map[m]
        ep_map['all'] = ep_map['read'] | ep_map['write']

        return ep_map
