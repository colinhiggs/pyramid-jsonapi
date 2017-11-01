"""Classes to store and manipulate endpoints and routes."""

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

    def __init__(
            self, sep='/', main_prefix='',
            api_prefix='api', metadata_prefix='metadata'
    ):
        self.sep = sep
        self.main_prefix = main_prefix
        self.api_prefix = api_prefix
        self.metadata_prefix = metadata_prefix

    def pattern_from_components(self, *components):
        """Construct a route pattern from components.

        Join components together with self.sep. Remove all occurrences of '',
        except at the beginning, so that there are no double or trailing
        separators.

        Arguments:
            *components (str): route pattern components.
        """
        components = components or []
        new_comps = []
        for i, component in enumerate(components):
            if component == '' and (i != 0):
                continue
            new_comps.append(component)
        return self.sep.join(new_comps)

    def api_pattern(self, name, *components, rstrip=True):
        """Generate a route pattern from a collection name and suffix components.

        Arguments:
            name (str): A collection name.
            rstrip (bool): Strip trailing separator (defaults to True).
            *components (str): components to add after collection name.
        """
        pattern = self.pattern_from_components(
            '', self.main_prefix, self.api_prefix, name, *components
        )
        if rstrip:
            pattern = pattern.rstrip(self.sep)
        return pattern

    def metadata_pattern(self, metadata_type, *components):
        """Generate a metadata route pattern.

        Arguments:
            metadata_type (str): Metadata type (e.g. swagger, json-schema).
            *components (str): components to add after metadata type.
        """
        return self.pattern_from_components(
            '', self.main_prefix, self.metadata_prefix,
            metadata_type, *components
        )


class EndpointData():
    """Class to hold endpoint data and utility methods.

    Arguments:
        api: A PyramidJSONAPI object.

    """

    def __init__(self, api):
        self.config = api.config
        settings = api.settings
        self.route_name_prefix = settings.route_name_prefix
        self.route_pattern_prefix = settings.route_pattern_prefix
        self.route_name_sep = settings.route_name_sep
        self.route_pattern_sep = settings.route_pattern_sep
        self.api_prefix = ''
        if settings.metadata_endpoints:
            self.api_prefix = settings.route_pattern_api_prefix
        self.metadata_prefix = settings.route_pattern_metadata_prefix
        self.rp_constructor = RoutePatternConstructor(
            sep=self.route_pattern_sep,
            main_prefix=self.route_pattern_prefix,
            api_prefix=self.api_prefix,
            metadata_prefix=self.metadata_prefix,
        )

        # Mapping of endpoints, http_methods and options for constructing routes and views.
        # Update this dictionary prior to calling create_jsonapi()
        # 'responses' can be 'global', 'per-endpoint' and 'per-endpoint-method'
        # Mandatory 'endpoint' keys: http_methods
        # Optional 'endpoint' keys: route_pattern
        # Mandatory 'http_method' keys: function
        # Optional 'http_method' keys: renderer
        self.endpoints = {
            'responses': {
                # Top-level: apply to all endpoints
                HTTPUnsupportedMediaType: {'reason': ['Servers MUST respond with a 415 Unsupported Media Type status code if a request specifies the header Content-Type: application/vnd.api+json with any media type parameters.']},
                HTTPNotAcceptable: {'reason': ['Servers MUST respond with a 406 Not Acceptable status code if a request’s Accept header contains the JSON API media type and all instances of that media type are modified with media type parameters.']},
                HTTPBadRequest: {'reason': ['If a server encounters a query parameter that does not follow the naming conventions above, and the server does not know how to process it as a query parameter from this specification, it MUST return 400 Bad Request.',
                                            'If the server does not support sorting as specified in the query parameter sort, it MUST return 400 Bad Request.',
                                            'If an endpoint does not support the include parameter, it MUST respond with 400 Bad Request to any requests that include it.',
                                            'If the request content is malformed in some way.']},
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
                        HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']},
                    },
                    'route_pattern': {'fields': ['id'], 'pattern': '{{{}}}'},
                    'http_methods': {
                        'DELETE': {
                            'function': 'delete',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST return a 200 OK status code if a deletion request is successful and the server responds with only top-level meta data.']},
                                HTTPNotFound: {'reason': ['A server SHOULD return a 404 Not Found status code if a deletion request fails due to the resource not existing.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by deleting the specified resource from the relationship.']},
                            },
                        },
                        'GET': {
                            'function': 'get',
                            'responses': {
                                HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch an individual resource or resource collection with a 200 OK response.']},
                                HTTPNotFound: {'reason': ['A server MUST respond with 404 Not Found when processing a request to fetch a single resource that does not exist.']},
                            },
                        },
                        'PATCH': {
                            'function': 'patch',
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
                        HTTPOk: {'reason': ['A server MUST respond to a successful request to fetch a relationship with a 200 OK response.']},
                        HTTPNotFound: {'reason': ['A server MUST return 404 Not Found when processing a request to fetch a relationship link URL that does not exist.']},
                    },
                    'route_pattern': {'fields': ['id', 'relationship'], 'pattern': '{{{}}}{sep}relationships{sep}{{{}}}'},
                    'http_methods': {
                        'DELETE': {
                            'function': 'relationships_delete',
                            'responses': {
                                HTTPOk: {'reason': ['If all of the specified resources are able to be removed from, or are already missing from, the relationship then the server MUST return a successful response.']},
                                HTTPConflict: {'reason'},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by deleting the specified resource from the relationship.']},
                                HTTPForbidden: {
                                    'reason': [
                                        'If the client makes a DELETE request to a URL from a relationship link the server MUST delete the specified members from the relationship or return a 403 Forbidden response.',
                                        'DELETE not supported in TOONE relationships and "a server MUST return 403 Forbidden in response to an unsupported request to update a relationship."'
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
                            'responses': {
                                HTTPConflict: {'reason': ['A server MUST return 409 Conflict when processing a POST request in which the resource object’s type is not among the type(s) that constitute the collection represented by the endpoint.']},
                                HTTPFailedDependency: {'reason': ['If a database constraint would be broken by adding the specified resource to the relationship.']},
                                HTTPForbidden: {'reason': ['DELETE not supported in TOONE relationships and "a server MUST return 403 Forbidden in response to an unsupported request to update a relationship."']},
                            },
                        },
                    },
                },
            },
        }

    def make_route_name(self, name, suffix=''):
        """Attach prefix and suffix to name to generate a route_name.

        Arguments:
            name: A pyramid route name.

        Keyword Arguments:
            suffix: An (optional) suffix to append to the route name.
        """
        return self.route_name_sep.join(
            (self.route_name_prefix, name, suffix)
        ).rstrip(self.route_name_sep)

    def route_pattern_to_suffix(self, pattern_dict):
        """Convert route_pattern dict to suffix string."""
        if pattern_dict:
            return pattern_dict['pattern'].format(sep=self.route_pattern_sep, *pattern_dict['fields'])
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
