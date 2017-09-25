"""pyramid_jsonapi configuration settings."""

import logging
from pyramid.settings import asbool, aslist


class ConfigString(str):
    """Override 'str' to add custom methods."""
    def asbool(self):
        """Access pyramid.settings.asbool in a pythonic way."""
        return asbool(self)

    def aslist(self):
        """Access pyramid.settings.aslist in a pythonic way."""
        return aslist(self, flatten=True)

    __bool__ = asbool


class Settings():
    """Class to store pyramid configuration settings (from the ini file)
    and provide easier programatic access to them."""

    # Default configuration values
    _defaults = {
        'allow_client_ids': {'val': False, 'desc': 'Allow client to specify resource ids.'},
        'filter_operator_groups': {'val': '', 'desc': ''},
        'metadata_endpoints': {'val': True, 'desc': 'Should /metadata endpoint be enabled?'},
        'metadata_modules': {'val': '', 'desc': 'Modules to load to provide metadata endpoints (defaults to all modules in the metadata package).'},
        'paging_default_limit': {'val': 10, 'desc': 'Default pagination limit for collections.'},
        'paging_max_limit': {'val': 100, 'desc': 'Default limit on the number of items returned for collections.'},
        'route_name_prefix': {'val': 'pyramid_jsonapi', 'desc': 'Prefix for pyramid route names for view_classes.'},
        'route_pattern_api_prefix': {'val': 'api', 'desc': 'Prefix for api endpoints (if metadata_endpoints is enabled).'},
        'route_pattern_metadata_prefix': {'val': 'metadata', 'desc': 'Prefix for metadata endpoints (if metadata_endpoints is enabled).'},
        'route_pattern_prefix': {'val': '', 'desc': '"Parent" prefix for all endpoints'},
        'route_name_sep': {'val': ':', 'desc': 'Separator for pyramid route names.'},
        'route_pattern_sep': {'val': '/', 'desc': 'Separator for pyramid route patterns.'},
        'schema_file': {'val': '', 'desc': 'File containing jsonschema JSON for validation.'},
        'schema_validation': {'val': True, 'desc': 'jsonschema schema validation enabled?'},
        'tests_models_iterable': {'val': '', 'desc': ''},
        'debug_endpoints': {'val': False, 'desc': ''},
        'debug_test_data_module': {'val': 'test_data', 'desc': ''},
        'debug_meta': {'val': False, 'desc': ''},
    }

    def __init__(self, settings):
        """
        Create attributes from settings, overriding defaults
        with values from pyramid config.

        Arguments:
            settings: Pyramid config.registry.settings dictionary.

        """
        prefix = 'pyramid_jsonapi.'
        # Extract pyramid_jsonapi config from settings, stripping prefix
        pj_settings = {k[len(prefix):]: v for k, v in settings.items() if k.startswith(prefix)}

        # Create attributes from  _defaults, overriding with pj_settings
        for key, opts in self._defaults.items():
            val = opts['val']
            if key in pj_settings:
                val = pj_settings.pop(key)
            setattr(self, key, ConfigString(val))

        # Remaining keys must have ben invalid config options
        logging.warning("Invalid configuration options: %s", pj_settings)
