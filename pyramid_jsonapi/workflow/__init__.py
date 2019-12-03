import importlib
import logging
from collections import (
    deque,
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
        'serialise': deque(),
        'validate_response': deque()
    }
    stage_order = ['validate_request', 'alter_request']
    for stage_name in wf_module.stages:
        stages[stage_name] = deque()
        stage_order.append(stage_name)
    stage_order.append('serialise')
    stage_order.append('validate_response')
    stages['validate_request'].append(request_valid_json)
    stages['validate_request'].append(not_item_3)
    stages['alter_request'].append(alter_request_add_info)

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
                view, stages, 'validate_request', view.request
            )
            request = execute_stage(
                view, stages, 'alter_request', request
            )
            view.request = request
            document = wf_module.workflow(view, stages, data)
            ret = execute_stage(
                view, stages, 'validate_response', document.as_dict(), data
            )
        except Exception as exc:
            if exc.__class__ not in responses:
                logging.exception(
                    "Invalid exception raised: %s for route_name: %s path: %s",
                    exc.__class__,
                    view.request.matched_route.name,
                    view.request.current_route_path()
                )
                if hasattr(exc, 'code'):
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

def request_valid_json(view, request, data):
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

def not_item_3(view, request, data):
    if request.matchdict.get('id', None) == '3':
        raise HTTPForbidden('Item 3 is off limits.')
    return request

def alter_request_add_info(view, request, data):
    """Add information commonly used in view operations."""

    # Extract id and relationship from route, if provided
    view.obj_id = view.request.matchdict.get('id', None)
    view.relname = view.request.matchdict.get('relationship', None)
    return request


class ResultObject:
    def __init__(self, view, object, related=None):
        self.view = view
        self.object = object
        self.related = related or {}
        self.obj_id = self.view.id_col(self.object)

    def serialise(self):
        # Object's id and type are required at the top level of json-api
        # objects.
        obj_url = self.view.request.route_url(
            self.view.api.endpoint_data.make_route_name(
                self.view.collection_name, suffix='item'
            ),
            **{'id': self.obj_id}
        )

        resource = pyramid_jsonapi.jsonapi.Resource(self.view)
        resource.id = str(self.obj_id)
        resource.attributes = {
            key: getattr(self.object, key)
            for key in self.view.requested_attributes.keys()
            if self.view.mapped_info_from_name(key).get('visible', True)
        }
        resource.links = {'self': obj_url}
        resource.relationships = {
            rel_name: res.identifiers() for rel_name, res in self.related.items()
        }

        return resource.as_dict()

    def identifier(self):
        return {
            'type': self.view.collection_name,
            'id': self.obj_id
        }

    def included_dict(self):
        incd = {}
        for rel_name, res in self.related.items():
            if not res.is_included:
                continue
            incd.update(res.included_dict())
        return incd


class Results:
    def __init__(self, view, objects=None, many=True, count=None, is_included=False, is_top=False):
        self.view = view
        self.objects = objects or []
        self.many = many
        self.count = count
        self.is_included = is_included
        self.is_top = is_top

    def data(self):
        data = [o.serialise() for o in self.objects]
        if self.many:
            return data
        else:
            return data or None

    def identifiers(self):
        data = [o.identifier() for o in self.objects]
        if self.many:
            return data
        else:
            return data or None

    def included(self):
        return [o.serialise() for o in self.included_dict().values()]

    def included_dict(self):
        if self.is_top:
            included_dict = {}
        else:
            included_dict = {
                (self.view.collection_name, o.obj_id):o for o in self.objects
            }
        for o in self.objects:
            included_dict.update(o.included_dict())
        return included_dict
