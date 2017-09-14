"""This package contains metadata 'plugin' modules
that provide extra information related to the API being generated,
such as documentation, schemas etc.

Such plugins can optionally be offered as pyramid routes and views
under the 'metadata' endpoint."""

import collections
import importlib

from pyramid.settings import aslist


class MetaData():
    """Adds routes and views for all metadata modules.

    Plugins are added by the module name being added to self.modules
    This may be overriden in the pyramid inifile config option
    'pyramid_jsonapi.metadata_modules'
    Modules specified in thbis wasy should be space or newline separated
    (see pyramid.settings aslist())

    All modules MUST have a class with the same name as the package.
    This class MAY contain a 'views' attribute, which contains a list
    of 'VIEWS' namedtuple instances, which will be converted into pyramid
    routes and views.
    """

    def __init__(self, api):
        self.api = api
        # TODO(mrichar1): defaults list from package introspection
        self.modules = aslist(self.api.config.registry.settings.get(
            'pyramid_jsonapi.metadata_modules',
            'JSONSchema'
        ))
        self.make_routes_views()

    def make_routes_views(self):
        """Generate routes and views for plugin modules."""
        for module in self.modules:
            # Import the module from the name provided
            module = importlib.import_module("{}.{}".format(__name__, module))
            # Each module should have a class with the same name
            class_name = module.__name__.lstrip(__name__)
            mclass = getattr(module, class_name)(self.api)
            views = getattr(mclass, 'views', [])
            for view in views:
                rp_constructor = self.api.endpoint_data.rp_constructor
                route_name = self.api.endpoint_data.make_route_name(
                    class_name,
                    suffix=view.route_name
                )
                route_pattern = rp_constructor.metadata_pattern(
                    class_name,
                    view.route_name
                )
                self.api.config.add_route(
                    route_name,
                    route_pattern
                )
                self.api.config.add_view(
                    mclass,
                    attr=str(view.attr),
                    route_name=route_name,
                    request_method=view.request_method or 'GET',
                    renderer=view.renderer or 'json',
                )


VIEWS = collections.namedtuple('Views', 'attr request_method route_name renderer')
