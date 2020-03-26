import functools
import importlib
import logging
import re
import sqlalchemy

from collections import (
    deque,
)

from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)

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

import pyramid_jsonapi


def make_method(name, api):
    settings = api.settings
    wf_module = importlib.import_module(
        getattr(settings, 'workflow_{}'.format(name))
    )

    # Set up the stages.
    stages = {
        'validate_request': deque(),
        'alter_request': deque(),
        'alter_document': deque(),
        'validate_response': deque()
    }
    stage_order = ['alter_request', 'validate_request']
    for stage_name in wf_module.stages:
        stages[stage_name] = deque()
        stage_order.append(stage_name)
    stage_order.append('alter_document')
    stage_order.append('validate_response')
    stages['validate_request'].append(validate_request_headers)
    stages['validate_request'].append(validate_request_valid_json)
    stages['validate_request'].append(validate_request_common_validity)
    stages['validate_request'].append(validate_request_object_exists)
    stages['alter_request'].append(alter_request_add_info)
    stages['alter_document'].append(alter_document_self_link)
    if api.settings.debug_meta:
        stages['alter_document'].append(alter_document_debug_info)

    # Stack the deques.
    for stage_name, stage_deque in stages.items():
        try:
            item = getattr(wf_module, 'stage_' + stage_name)
        except AttributeError:
            # If there isn't one, move on.
            continue
        if callable(item):
            # If item is callable just append it.
            stage_deque.append(item)
        else:
            # item should be an iterable of callables. Append them.
            for handler in item:
                stage_deque.append(handler)

    # Build a set of expected responses.
    ep_dict = api.endpoint_data.endpoints
    parts = name.split('_')
    if len(parts) == 1:
        endpoint = 'item'
        http_method = parts[0].upper()
    else:
        endpoint, http_method = parts
        http_method = http_method.upper()
    responses = set(
        ep_dict['responses'].keys() |
        ep_dict['endpoints'][endpoint]['responses'].keys() |
        ep_dict['endpoints'][endpoint]['http_methods'][http_method]['responses'].keys()
    )

    def method(view):
        data = {}
        try:
            request = execute_stage(
                view, stages, 'alter_request', view.request
            )
            request = execute_stage(
                view, stages, 'validate_request', request
            )
            view.request = request
            document = wf_module.workflow(view, stages, data)
            document = execute_stage(
                view, stages, 'alter_document', document
            )
            ret = execute_stage(
                view, stages, 'validate_response', document, data
            )
        except Exception as exc:
            if exc.__class__ not in responses:
                logging.exception(
                    "Invalid exception raised: %s for route_name: %s path: %s",
                    exc.__class__,
                    view.request.matched_route.name,
                    view.request.current_route_path()
                )
                if isinstance(exc, HTTPError):
                    if 400 <= int(exc.code) < 500:  # pylint:disable=no-member
                        raise HTTPBadRequest("Unexpected client error: {}".format(exc))
                else:
                    raise HTTPInternalServerError("Unexpected server error.")
            raise

        # Log any responses that were not expected.
        response_class = status_map[view.request.response.status_code]
        if response_class not in responses:
            logging.error(
                "Invalid response: %s for route_name: %s path: %s",
                response_class,
                view.request.matched_route.name,
                view.request.current_route_path()
            )
        return ret

    return method


def execute_stage(view, stages, stage_name, arg, previous_data=None):
    for handler in stages[stage_name]:
        arg = handler(view, arg, previous_data)
    if previous_data is not None:
        previous_data[stage_name] = arg
    return arg


@functools.lru_cache()
def get_jsonapi_accepts(request):
    """Return a set of all 'application/vnd.api' parts of the accept
    header.
    """
    accepts = re.split(
        r',\s*',
        request.headers.get('accept', '')
    )
    return {
        a for a in accepts
        if a.startswith('application/vnd.api')
    }


def validate_request_headers(view, request, data):
    """Check that request headers comply with spec.

    Raises:
        HTTPUnsupportedMediaType
        HTTPNotAcceptable
    """
    # Spec says to reject (with 415) any request with media type
    # params.
    if len(request.headers.get('content-type', '').split(';')) > 1:
        raise HTTPUnsupportedMediaType(
            'Media Type parameters not allowed by JSONAPI ' +
            'spec (http://jsonapi.org/format).'
        )
    # Spec says throw 406 Not Acceptable if Accept header has no
    # application/vnd.api+json entry without parameters.
    jsonapi_accepts = get_jsonapi_accepts(request)
    if jsonapi_accepts and\
            'application/vnd.api+json' not in jsonapi_accepts:
        raise HTTPNotAcceptable(
            'application/vnd.api+json must appear with no ' +
            'parameters in Accepts header ' +
            '(http://jsonapi.org/format).'
        )

    return request


def validate_request_valid_json(view, request, data):
    """Check that the body of any request is valid JSON.

    Raises:
        HTTPBadRequest
    """
    if request.content_length:
        try:
            request.json_body
        except ValueError:
            raise HTTPBadRequest("Body is not valid JSON.")

    return request


def validate_request_common_validity(view, request, data):
    """Perform common request validity checks."""

    if request.content_length and view.api.settings.schema_validation:
        # Validate request JSON against the JSONAPI jsonschema
        view.api.metadata.JSONSchema.validate(request.json_body, request.method)

    # Spec says throw BadRequest if any include paths reference non
    # existent attributes or relationships.
    if view.bad_include_paths:
        raise HTTPBadRequest(
            "Bad include paths {}".format(
                view.bad_include_paths
            )
        )

    # Spec says set Content-Type to application/vnd.api+json.
    request.response.content_type = 'application/vnd.api+json'

    return request


def validate_request_object_exists(view, request, data):
    """Make sure that id exists in collection for all urls specifying an id."""
    if view.obj_id is not None:
        if not view.object_exists(view.obj_id):
            raise HTTPNotFound('No item {} in {}'.format(view.obj_id, view.collection_name))
    return request


def alter_document_self_link(view, doc, data):
    """Include a self link unless the method is PATCH."""
    if view.request.method != 'PATCH':
        doc.update_child('links', {'self': view.request.url})
    return doc


def alter_document_debug_info(view, doc, data):
    """Potentially add some debug information."""
    debug = {
        'accept_header': {
            a: None for a in get_jsonapi_accepts(view.request)
        },
        'qinfo_page':
            view.collection_query_info(view.request)['_page'],
        'atts': {k: None for k in view.attributes.keys()},
        'includes': {
            k: None for k in view.requested_include_names()
        }
    }
    doc.update_child('meta', {'debug': debug})
    return doc


def alter_request_add_info(view, request, data):
    """Add information commonly used in view operations."""

    # Extract id and relationship from route, if provided
    view.obj_id = view.request.matchdict.get('id', None)
    view.relname = view.request.matchdict.get('relationship', None)
    if view.relname:
        # Gather relationship info
        mapper = sqlalchemy.inspect(view.model).mapper
        try:
            view.rel = view.relationships[view.relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                view.relname,
                view.collection_name
            ))
        view.rel_class = view.rel.tgt_class
        view.rel_view = view.view_instance(view.rel_class)
    return request


class ResultObject:
    def __init__(self, view, object, related=None):
        self.view = view
        self.object = object
        self.related = related or {}
        if object is None:
            self.obj_id = None
        else:
            self.obj_id = self.view.id_col(self.object)

    def serialise(self):
        # An object of 'None' is a special case.
        if self.object is None:
            return None
        # Object's id and type are required at the top level of json-api
        # objects.
        obj_url = self.view.request.route_url(
            self.view.api.endpoint_data.make_route_name(
                self.view.collection_name, suffix='item'
            ),
            **{'id': self.obj_id}
        )
        atts = {
            key: getattr(self.object, key)
            for key in self.view.requested_attributes.keys()
            if self.view.mapped_info_from_name(key).get('visible', True)
        }
        rels = {
            rel_name: res.rel_dict(
                rel=self.view.relationships[rel_name],
                rel_name=rel_name,
                parent_url=obj_url
            )
            for rel_name, res in self.related.items()
        }
        return {
            'type': self.view.collection_name,
            'id': str(self.obj_id),
            'attributes': atts,
            'links': {'self': obj_url},
            'relationships': rels,
        }

    def identifier(self):
        return {
            'type': self.view.collection_name,
            'id': str(self.obj_id)
        }

    def included_dict(self):
        incd = {}
        for rel_name, res in self.related.items():
            if not res.is_included:
                continue
            incd.update(res.included_dict())
        return incd


class Results:
    def __init__(self, view, objects=None, many=True, count=None, limit=None, is_included=False, is_top=False):
        self.view = view
        self.objects = objects or []
        self.many = many
        self.count = count
        self.limit = limit
        self.is_included = is_included
        self.is_top = is_top

    def serialise(self):
        doc = Doc()
        if self.many:
            # doc.collection = True
            doc['links'] = self.view.pagination_links(count=self.count)
        doc['data'] = self.data()
        doc['meta'] = self.meta()
        doc['included'] = self.included()
        return doc

    def serialise_object_with(self, method_name):
        data = [getattr(o, method_name)() for o in self.objects]
        if self.many:
            return data
        else:
            try:
                return data[0]
            except IndexError:
                return None

    def meta(self):
        meta = {}
        if self.many:
            meta.update(
                {
                    'results': {
                        'available': self.count,
                        'limit': self.limit,
                        'returned': len(self.objects)
                    }
                }
            )
        return meta

    def data(self):
        return self.serialise_object_with('serialise')

    def identifiers(self):
        return self.serialise_object_with('identifier')

    def rel_dict(self, rel, rel_name, parent_url):
        rd = {
            'data': self.identifiers(),
            'links': {
                'self': '{}/relationships/{}'.format(parent_url, rel_name),
                'related': '{}/{}'.format(parent_url, rel_name)
            },
            'meta': {
                'direction': rel.direction.name,
            }
        }
        if self.many:
            rd['meta']['results'] = {}
            rd['meta']['results']['available'] = self.count
            rd['meta']['results']['limit'] = self.limit
            rd['meta']['results']['returned'] = len(rd['data'])
        return rd

    def included(self):
        return [o.serialise() for o in self.included_dict().values()]

    def included_dict(self):
        if self.is_top:
            included_dict = {}
        else:
            included_dict = {
                (self.view.collection_name, o.obj_id): o for o in self.objects
            }
        for o in self.objects:
            included_dict.update(o.included_dict())
        return included_dict


class Doc(dict):

    def update_child(self, key, value):
        try:
            self[key].update(value)
        except KeyError:
            self[key] = value
