"""Tools for constructing a JSON-API from sqlalchemy models in Pyramid."""

# pylint:disable=line-too-long

import copy
import importlib
import re
import types
from collections import deque

from pyramid.view import (
    view_config,
    notfound_view_config,
    forbidden_view_config
)
from pyramid.httpexceptions import (
    exception_response,
    HTTPException,
    HTTPNotFound,
    HTTPForbidden,
    HTTPUnauthorized,
    HTTPClientError,
    HTTPBadRequest,
    HTTPConflict,
    HTTPUnsupportedMediaType,
    HTTPNotAcceptable,
    HTTPNotImplemented,
    HTTPInternalServerError,
    HTTPError,
    HTTPFailedDependency,
    status_map,
)
import pyramid_settings_wrapper
import sqlalchemy
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.declarative.api import DeclarativeMeta
from sqlalchemy.ext.hybrid import hybrid_property

import pyramid_jsonapi.collection_view
import pyramid_jsonapi.endpoints
import pyramid_jsonapi.filters
import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.metadata
import pyramid_jsonapi.version

__version__ = pyramid_jsonapi.version.get_version()


class PyramidJSONAPI():
    """Class encapsulating an API.

    Arguments:
        config (pyramid.config.Configurator): pyramid config object from app.
        models (module or iterable): a models module or iterable of models.

    Keyword Args:
        get_dbsession (callable): function accepting an instance of
            CollectionViewBase and returning a sqlalchemy database session.
    """

    view_classes = {}

    # Default configuration values
    config_defaults = {
        'allow_client_ids': {'val': False, 'desc': 'Allow client to specify resource ids.'},
        'api_version': {'val': '', 'desc': 'API version for prefixing endpoints and metadata generation.'},
        'expose_foreign_keys': {'val': False, 'desc': 'Expose foreign key fields in JSON.'},
        'metadata_endpoints': {'val': True, 'desc': 'Should /metadata endpoint be enabled?'},
        'metadata_modules': {'val': 'JSONSchema OpenAPI', 'desc': 'Modules to load to provide metadata endpoints (defaults are modules provided in the metadata package).'},
        'openapi_file': {'val': '', 'desc': 'File containing OpenAPI data (YAML or JSON)'},
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
        'debug_endpoints': {'val': False, 'desc': 'Whether or not to add debugging endpoints.'},
        'debug_test_data_module': {'val': 'test_data', 'desc': 'Module responsible for populating test data.'},
        'debug_meta': {'val': False, 'desc': 'Whether or not to add debug information to the meta key in returned JSON.'},
    }

    def __init__(self, config, models, get_dbsession=None):
        self.config = config
        self.settings = pyramid_settings_wrapper.Settings(
            config.registry.settings,
            defaults=self.config_defaults,
            default_keys_only=True,
            prefix=['pyramid_jsonapi']
        )
        self.models = models
        self.get_dbsession = get_dbsession
        self.endpoint_data = pyramid_jsonapi.endpoints.EndpointData(self)
        self.filter_registry = pyramid_jsonapi.filters.FilterRegistry()
        self.metadata = {}

    @staticmethod
    def error(exc, request):
        """Error method to return jsonapi compliant errors."""
        request.response.content_type = 'application/vnd.api+json'
        request.response.status_code = exc.code
        return {
            'errors': [
                {
                    'code': str(exc.code),
                    'detail': exc.detail,
                    'title': exc.title,
                }
            ]
        }

    def create_jsonapi(self, engine=None, test_data=None, api_version=''):
        """Auto-create jsonapi from module or iterable of sqlAlchemy models.

        Keyword Args:
            engine: a sqlalchemy.engine.Engine instance. Only required if using the
                debug view.
            test_data: a module with an ``add_to_db()`` method which will populate
                the database.
            api_version: An optional version to be used in generating urls, docs etc.
                defaults to ''. Can also be set globally in settings ini file.
        """

        if api_version:
            self.settings.api_version = api_version

        # Build a list of declarative models to add as collections.
        if isinstance(self.models, types.ModuleType):
            model_list = []
            for attr in self.models.__dict__.values():
                if isinstance(attr, DeclarativeMeta):
                    try:
                        sqlalchemy.inspect(attr).primary_key
                    except sqlalchemy.exc.NoInspectionAvailable:
                        # Trying to inspect the declarative_base() raises this
                        # exception. We don't want to add it to the API.
                        continue
                    model_list.append(attr)
        else:
            model_list = list(self.models)

        # Add the debug endpoints if required.
        if self.settings.debug_endpoints:
            DebugView.engine = engine or model_list[0].metadata.bind
            DebugView.metadata = model_list[0].metadata
            DebugView.test_data = test_data or importlib.import_module(
                str(self.settings.debug_test_data_module)
            )
            self.config.add_route('debug', '/debug/{action}')
            self.config.add_view(
                DebugView,
                attr='drop',
                route_name='debug',
                match_param='action=drop',
                renderer='json'
            )
            self.config.add_view(
                DebugView,
                attr='populate',
                route_name='debug',
                match_param='action=populate',
                renderer='json'
            )
            self.config.add_view(
                DebugView,
                attr='reset',
                route_name='debug',
                match_param='action=reset',
                renderer='json'
            )

        # Loop through the models list. Create resource endpoints for these and
        # any relationships found.
        for model_class in model_list:
            self.create_resource(model_class)

        # Instantiate metadata now that view_class has been populated
        if self.settings.metadata_endpoints:
            self.metadata = pyramid_jsonapi.metadata.MetaData(self)

        # Add error views
        prefnames = ['api']
        if self.settings.metadata_endpoints:
            prefnames.append('metadata')
        for prefname in prefnames:
            setting_name = 'route_pattern_{}_prefix'.format(prefname)
            sep = self.settings.route_pattern_sep
            setting = str(getattr(self.settings, setting_name))
            if setting != '':
                path_info = '{}{}{}'.format(sep, setting, sep)
            else:
                path_info = sep
            self.config.add_notfound_view(
                self.error, renderer='json', path_info=path_info
            )
            self.config.add_forbidden_view(
                self.error, renderer='json', path_info=path_info
            )
            self.config.add_view(
                self.error, context=HTTPError, renderer='json',
                path_info=path_info
            )

    create_jsonapi_using_magic_and_pixie_dust = create_jsonapi  # pylint:disable=invalid-name

    def create_resource(self, model, collection_name=None, expose_fields=None):
        """Produce a set of resource endpoints.

        Arguments:
            model: a model class derived from DeclarativeMeta.

        Keyword Args:
            collection_name: string name of collection. Passed through to
                ``collection_view_factory()``
            expose_fields: set of field names to be exposed. Passed through to
                ``collection_view_factory()``
        """

        # Find the primary key column from the model and use as 'id_col_name'
        try:
            keycols = sqlalchemy.inspect(model).primary_key
        except sqlalchemy.exc.NoInspectionAvailable:
            # Trying to inspect the declarative_base() raises this exception. We
            # don't want to add it to the API.
            return
        # Only deal with one primary key column.
        if len(keycols) > 1:
            raise Exception(
                'Model {} has more than one primary key.'.format(
                    model.__name__
                )
            )

        if not hasattr(model, '__pyramid_jsonapi__'):
            model.__pyramid_jsonapi__ = {}
        if 'id_col_name' not in model.__pyramid_jsonapi__:
            model.__pyramid_jsonapi__['id_col_name'] = keycols[0].name

        # Create a view class for use in the various add_view() calls below.
        view = self.collection_view_factory(model,
                                            collection_name or
                                            getattr(
                                                model, '__pyramid_jsonapi__', {}
                                            ).get('collection_name') or
                                            sqlalchemy.inspect(model).tables[-1].name,
                                            expose_fields=expose_fields)

        self.view_classes[model] = view

        view.default_limit = int(self.settings.paging_default_limit)
        view.max_limit = int(self.settings.paging_max_limit)

        self.endpoint_data.add_routes_views(view)

    def collection_view_factory(self, model, collection_name=None, expose_fields=None):
        """Build a class to handle requests for model.

        Arguments:
            model: a model class derived from DeclarativeMeta.

        Keyword Args:
            collection_name: string name of collection.
            expose_fields: set of field names to expose.
        """

        class_attrs = {}
        class_attrs['api'] = self
        class_attrs['model'] = model
        class_attrs['key_column'] = sqlalchemy.inspect(model).primary_key[0]
        class_attrs['collection_name'] = collection_name or model.__tablename__
        class_attrs['exposed_fields'] = expose_fields
        # atts is ordinary attributes of the model.
        # hybrid_atts is any hybrid attributes defined.
        # fields is atts + hybrid_atts + relationships
        atts = {}
        hybrid_atts = {}
        fields = {}
        for key, col in sqlalchemy.inspect(model).mapper.columns.items():
            if key == class_attrs['key_column'].name:
                continue
            if col.foreign_keys and not self.settings.expose_foreign_keys:
                continue
            if expose_fields is None or key in expose_fields:
                atts[key] = col
                fields[key] = col
        class_attrs['attributes'] = atts
        for item in sqlalchemy.inspect(model).all_orm_descriptors:
            if isinstance(item, hybrid_property):
                if expose_fields is None or item.__name__ in expose_fields:
                    hybrid_atts[item.__name__] = item
                    fields[item.__name__] = item
        class_attrs['hybrid_attributes'] = hybrid_atts
        rels = {}
        for key, rel in sqlalchemy.inspect(model).mapper.relationships.items():
            if expose_fields is None or key in expose_fields:
                rels[key] = rel
        class_attrs['relationships'] = rels
        fields.update(rels)
        class_attrs['fields'] = fields

        # All callbacks have the current view as the first argument. The comments
        # below detail subsequent args.
        class_attrs['callbacks'] = {
            'after_serialise_identifier': deque(),  # args: identifier(dict)
            'after_serialise_object': deque(),      # args: object(dict)
            'after_get': deque(),                   # args: document(dict)
            'before_patch': deque(),                # args: partial_object(dict)
            'before_delete': deque(),               # args: item(sqlalchemy)
            'after_collection_get': deque(),        # args: document(dict)
            'before_collection_post': deque(),      # args: object(dict)
            'after_related_get': deque(),           # args: document(dict)
            'after_relationships_get': deque(),     # args: document(dict)
            'before_relationships_post': deque(),   # args: object(dict)
            'before_relationships_patch': deque(),  # args: partial_object(dict)
            'before_relationships_delete':
                deque(),                            # args: parent_item(sqlalchemy)
        }

        return type(
            'CollectionView<{}>'.format(collection_name),
            (pyramid_jsonapi.collection_view.CollectionViewBase, ),
            class_attrs
        )

    def append_callback_set_to_all_views(self, set_name):  # pylint:disable=invalid-name
        """Append a named set of callbacks to all view classes.

        Args:
            set_name (str): key in ``callback_sets``.
        """
        for view_class in self.view_classes.values():
            view_class.append_callback_set(set_name)


class DebugView:
    """Pyramid view class defining a debug API.

    These are available as ``/debug/{action}`` if
    ``pyramid_jsonapi.debug_endpoints == 'true'``.

    Attributes:
        engine: sqlalchemy engine with connection to the db.
        metadata: sqlalchemy model metadata
        test_data: module with an ``add_to_db()`` method which will populate
            the database
    """
    def __init__(self, request):
        self.request = request

    def drop(self):
        """Drop all tables from the database!!!
        """
        self.metadata.drop_all(self.engine)
        return 'dropped'

    def populate(self):
        """Create tables and populate with test data.
        """
        # Create or update tables and schema. Safe if tables already exist.
        self.metadata.create_all(self.engine)
        # Add test data. Safe if test data already exists.
        self.test_data.add_to_db()
        return 'populated'

    def reset(self):
        """The same as 'drop' and then 'populate'.
        """
        self.drop()
        self.populate()
        return "reset"
