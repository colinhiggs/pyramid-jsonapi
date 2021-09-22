"""Tools for constructing a JSON-API from sqlalchemy models in Pyramid."""

# pylint:disable=line-too-long

import copy
import importlib
import re
import traceback
import types
from collections import deque

from pyramid.settings import asbool

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
from sqlalchemy.ext.associationproxy import ASSOCIATION_PROXY
# DeclarativeMeta moved between sqlalchemy 1.3 and 1.4
try:
    # <= 1.3
    from sqlalchemy.ext.declarative.api import DeclarativeMeta
except ImportError:
    # 1.4+
    from sqlalchemy.orm import DeclarativeMeta
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm.interfaces import (
    MANYTOMANY,
    MANYTOONE,
    ONETOMANY,
)
from sqlalchemy.orm.relationships import RelationshipProperty

import pyramid_jsonapi.collection_view
import pyramid_jsonapi.endpoints
import pyramid_jsonapi.filters
import pyramid_jsonapi.metadata
from pyramid_jsonapi.permissions import (
    Permission,
    Targets,
)
import pyramid_jsonapi.version
import pyramid_jsonapi.workflow as wf

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
        'inform_of_get_authz_failures': {'val': True, 'desc': 'True = return information in meta about authz failures; False = pretend items don\'t exist'},
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
        'debug_traceback': {'val': False, 'desc': 'Whether or not to add a stack traceback to errors.'},
        'debug_meta': {'val': False, 'desc': 'Whether or not to add debug information to the meta key in returned JSON.'},
        'workflow_item_get': {'val': 'pyramid_jsonapi.workflow.loop.item_get', 'desc': 'Module implementing the item_get workflow.'},
        'workflow_item_patch': {'val': 'pyramid_jsonapi.workflow.loop.item_patch', 'desc': 'Module implementing the item_patch workflow.'},
        'workflow_item_delete': {'val': 'pyramid_jsonapi.workflow.loop.item_delete', 'desc': 'Module implementing the item_delete workflow.'},
        'workflow_collection_get': {'val': 'pyramid_jsonapi.workflow.loop.collection_get', 'desc': 'Module implementing the collection_get workflow.'},
        'workflow_collection_post': {'val': 'pyramid_jsonapi.workflow.loop.collection_post', 'desc': 'Module implementing the collection_post workflow.'},
        'workflow_related_get': {'val': 'pyramid_jsonapi.workflow.loop.related_get', 'desc': 'Module implementing the related_get workflow.'},
        'workflow_relationships_get': {'val': 'pyramid_jsonapi.workflow.loop.relationships_get', 'desc': 'Module implementing the relationships_get workflow.'},
        'workflow_relationships_post': {'val': 'pyramid_jsonapi.workflow.loop.relationships_post', 'desc': 'Module implementing the relationships_post workflow.'},
        'workflow_relationships_patch': {'val': 'pyramid_jsonapi.workflow.loop.relationships_patch', 'desc': 'Module implementing the relationships_patch workflow.'},
        'workflow_relationships_delete': {'val': 'pyramid_jsonapi.workflow.loop.relationships_delete', 'desc': 'Module implementing the relationships_delete workflow.'},
    }
    config_defaults['paging_related_default_limit'] = {
        'val': config_defaults['paging_default_limit'],
        'desc': 'Default limit on the number of related items to fetch.'
    }
    config_defaults['paging_related_max_limit'] = {
        'val': config_defaults['paging_max_limit'],
        'desc': 'Limit on the maximim number of related items which can be fetched.'
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
        errors = {
            'errors': [
                {
                    'code': str(exc.code),
                    'detail': exc.detail,
                    'title': exc.title,
                }
            ]
        }
        if asbool(request.registry.settings.get('pyramid_jsonapi.debug_traceback', False)):
            errors['traceback'] = traceback.format_exc()
        return errors

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
            path_info = self.endpoint_data.rp_constructor.pattern_from_components(
                str(getattr(self.settings, 'route_pattern_prefix')),
                str(getattr(self.settings, 'api_version')),
                str(getattr(self.settings, 'route_pattern_{}_prefix'.format(prefname))),
                start_sep=True,
                end_sep=True
            )
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

        if not hasattr(model, '__pyramid_jsonapi__'):
            model.__pyramid_jsonapi__ = {}

        if 'id_col_name' not in model.__pyramid_jsonapi__:
            # Find the primary key column from the model and use as 'id_col_name'
            try:
                keycols = sqlalchemy.inspect(model).primary_key
            except sqlalchemy.exc.NoInspectionAvailable:
                # Trying to inspect the declarative_base() raises this exception.
                # We don't want to add it to the API.
                return
            # Only deal with one primary key column.
            if len(keycols) > 1:
                raise Exception(
                    'Model {} has more than one primary key.'.format(
                        model.__name__
                    )
                )
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

        for vm in self.endpoint_data.http_to_view_methods['all']:
            setattr(view, vm, wf.make_method(vm, self))
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
        rels = {}
        for key, item in sqlalchemy.inspect(model).all_orm_descriptors.items():
            if isinstance(item, hybrid_property):
                if expose_fields is None or item.__name__ in expose_fields:
                    if item.info.get('pyramid_jsonapi', {}).get('relationship', False):
                        rels[key] = item
                    else:
                        hybrid_atts[item.__name__] = item
                        fields[item.__name__] = item
            if item.extension_type is ASSOCIATION_PROXY:
                rels[key] = item
        class_attrs['hybrid_attributes'] = hybrid_atts
        class_attrs['all_attributes'] = atts.copy()
        class_attrs['all_attributes'].update(hybrid_atts)
        for key, rel in sqlalchemy.inspect(model).mapper.relationships.items():
            if expose_fields is None or key in expose_fields:
                rels[key] = rel
        view_rels = {}
        class_attrs['relationships'] = view_rels
        fields.update(rels)
        class_attrs['fields'] = fields
        vm_map = copy.deepcopy(
            self.endpoint_data.http_to_view_methods
        )
        class_attrs['permission_filters'] = {
            hm: {t: {} for t in Targets}
            for hm in self.endpoint_data.http_methods
        }
        for vm in vm_map['all']:
            vm_map[vm] = {vm}
        class_attrs['methods'] = vm_map

        view_class = type(
            'CollectionView<{}>'.format(collection_name),
            (pyramid_jsonapi.collection_view.CollectionViewBase, ),
            class_attrs
        )
        # Relationships have to be added after view_class has been constructed
        # because they need a reference to it.
        for key, rel in rels.items():
            view_rels[key] = StdRelationship(key, rel, view_class)
        view_class.permission_template = Permission.template_from_view(view_class)

        return view_class

    def enable_permission_handlers(self, stage_names):
        '''
        Add permission handlers to all views.

        Permission handlers are not added to views by default for performance
        reasons. Call this function to add permission handlers to *all* views
        for the stage names specified.

        Arguments:
            stage_names: an iterable of stage names to enable.

        '''
        # Build a set of all the end points from permissions.
        ep_names = self.endpoint_data.http_to_view_methods['all']

        # Add permission handlers for all view classes.
        for model, view_class in self.view_classes.items():
            for ep_name in ep_names:
                ep_func = getattr(view_class, ep_name)
                ep_func.stages['alter_document'].append(
                    wf.sh_alter_document_add_denied
                )
                for stage_name in stage_names:
                    view_class.add_stage_handler(
                        [ep_name], [stage_name],
                        view_class.permission_handler(ep_name, stage_name)
                    )


class StdRelationship:
    """Standardise access to relationship information.

    Attributes:
        obj: the actual object representing the relationship.
    """

    def __init__(self, name, obj, view_class):
        self.name = name
        self.obj = obj
        self.view_class = view_class
        self.src_class = self.view_class.model
        if isinstance(obj, RelationshipProperty):
            self.direction = self.rel_direction
            self.tgt_class = self.rel_tgt_class
            self.instrumented = getattr(self.src_class, self.name)
            self.queryable = True
        elif isinstance(obj, hybrid_property):
            pj_info = obj.info['pyramid_jsonapi']['relationship']
            self.direction = pj_info.get('direction', ONETOMANY)
            self.queryable = pj_info.get('queryable', False)
            tgt_class = pj_info.get('tgt_class')
            if isinstance(tgt_class, str):
                for mapper in view_class.model.registry.mappers:
                    if mapper.class_.__name__ == tgt_class:
                        tgt_class = mapper.class_
                        break
            self.tgt_class = tgt_class
        elif obj.extension_type is ASSOCIATION_PROXY:
            self.direction = self.proxy_direction
            self.tgt_class = self.proxy_tgt_class
            self.queryable = True

    @property
    def rel_direction(self):
        return self.obj.direction

    @property
    def to_many(self):
        return self.direction in (ONETOMANY, MANYTOMANY)

    @property
    def to_one(self):
        return not self.to_many

    @property
    def proxy_direction(self):
        ps = self.obj.for_class(self.src_class)
        if ps.scalar:
            return MANYTOONE
        else:
            return MANYTOMANY

    @property
    def rel_tgt_class(self):
        return self.obj.mapper.class_

    @property
    def proxy_tgt_class(self):
        ps = self.obj.for_class(self.src_class)
        return getattr(ps.target_class, ps.value_attr).mapper.class_

    @property
    def rel_mirror_relationship(self):
        tgt_view = self.view_class.api.view_classes[self.tgt_class]
        found = None
        for rname, r in tgt_view.relationships.items():
            if not isinstance(r.obj, RelationshipProperty):
                # Making the assumption that the mirror of any normal rel
                # will be another normal rel.
                continue
            if self.direction is MANYTOMANY:
                # For MANYTOMANY we need to look at the secondaryjoin.
                if (
                    self.obj.primaryjoin.left == r.obj.secondaryjoin.left and
                    self.obj.primaryjoin.right == r.obj.secondaryjoin.right and
                    self.obj.secondaryjoin.left == r.obj.primaryjoin.left and
                    self.obj.secondaryjoin.right == r.obj.primaryjoin.right
                ):
                    return StdRelationship(rname, r.obj, tgt_view)
            else:
                if (
                    self.obj.primaryjoin.left == r.obj.primaryjoin.left and
                    self.obj.primaryjoin.right == r.obj.primaryjoin.right
                ):
                    # Done.
                    return StdRelationship(rname, r.obj, tgt_view)
        return None

    @property
    def proxy_mirror_relationship(self):
        tgt_view = self.view_class.api.view_classes[self.tgt_class]
        pi = self.obj.for_class(self.src_class)
        for rname, r in tgt_view.relationships.items():
            if r.obj.extension_type is not ASSOCIATION_PROXY:
                # Assume that the mirror of any association proxy rel
                # will be another association proxy.
                continue
            rpi = r.obj.for_class(r.src_class)
            if (
                pi.local_attr.property.primaryjoin.left == rpi.remote_attr.property.primaryjoin.left and
                pi.local_attr.property.primaryjoin.right == rpi.remote_attr.property.primaryjoin.right and
                pi.remote_attr.property.primaryjoin.left == rpi.local_attr.property.primaryjoin.left and
                pi.remote_attr.property.primaryjoin.right == rpi.local_attr.property.primaryjoin.right
            ):
                return StdRelationship(rname, r.obj, tgt_view)
        return None

    @property
    def mirror_relationship(self):
        if isinstance(self.obj, RelationshipProperty):
            return self.rel_mirror_relationship
        elif self.obj.extension_type is ASSOCIATION_PROXY:
            return self.proxy_mirror_relationship
        else:
            return None


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
        self.test_data.add_to_db(self.engine)
        return 'populated'

    def reset(self):
        """The same as 'drop' and then 'populate'.
        """
        self.drop()
        self.populate()
        return "reset"


def get_class_by_tablename(tablename, registry):
    """Return class reference mapped to table.

        Args:
            tablename: String with name of table.
            registry: metadata registry

        return: Class reference or None.
    """
    for c in registry._decl_class_registry.values():
        if hasattr(c, '__tablename__') and c.__tablename__ == tablename:
            return c
