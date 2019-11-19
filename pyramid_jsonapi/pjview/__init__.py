import importlib
import inspect
import itertools
import logging
from collections import deque
from functools import wraps

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

#from pyramid_jsonapi.results import Results
from pyramid_jsonapi.pjview import all
import pyramid_jsonapi

def view_attr(func, settings):
    stage_module = importlib.import_module('pyramid_jsonapi.pjview.{}'.format(func.__name__))
    stages = {}
    print(dir(func))
    for module in (all, stage_module,):
        for stage_name in module.stages:
            # Make sure there is a deque for this stage.
            try:
                stage_deque = stages[stage_name]
            except KeyError:
                stage_deque = deque()
                stages[stage_name] = stage_deque
            # Find the module entry for this stage.
            try:
                item = getattr(module, 'stage_' + stage_name)
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

    @wraps(func)
    def new_func(view):
        # Build a set of expected responses.
        ep_dict = view.api.endpoint_data.endpoints
        # Get route_name from route
        _, _, endpoint = view.request.matched_route.name.split(':')
        http_method = view.request.method
        responses = set(
            ep_dict['responses'].keys() |
            ep_dict['endpoints'][endpoint]['responses'].keys() |
            ep_dict['endpoints'][endpoint]['http_methods'][http_method]['responses'].keys()
        )

        try:
            document = func(view, stages)
        except Exception as exc:
            if exc.__class__ not in responses:
                logging.exception(
                    "Invalid exception raised: %s for route_name: %s path: %s",
                    exc.__class__,
                    view.request.matched_route.name,
                    view.request.current_route_path()
                )
                if hasattr(exc, 'code'):
                    if 400 <= exc.code < 500:  # pylint:disable=no-member
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
        return document.as_dict()
        #return document

    # Add stage deques/funcs as attribute of new_func.
    for stage_name, stage in stages.items():
        setattr(new_func, stage_name, stage)
    return new_func

def execute_stage(view, stage, arg):
    for handler in stage:
        arg = handler(view, arg)
    return arg

def initial_related_queries(view, results):
    rq = {}
    return rq

def add_related_results(view, results, related_queries):
    pass

def serialise_results(view, results):
    doc = pyramid_jsonapi.jsonapi.Document()
    return doc
