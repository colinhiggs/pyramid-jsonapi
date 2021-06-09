import pyramid_jsonapi.workflow as wf
import sqlalchemy
import itertools

from functools import (
    partial
)

from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPForbidden,
    HTTPNotFound,
)
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)


def get_altered_objects(view, stages, stage_name, query, limit):
    return itertools.islice(
        filter(
            lambda o: o.tuple_identifier not in view.pj_shared.rejected.rejected['objects'],
            map(
                partial(wf.execute_stage, view, stages, stage_name),
                (wf.ResultObject(view, o) for o in wf.wrapped_query_all(query))
            )
        ),
        limit
    )


def get_related(obj, rel_name, stages, include_path=None):
    """
    Get the objects related to obj via the relationship rel_name.
    """
    view = obj.view
    include_path = include_path or []
    rel_include_path = include_path + [rel_name]
    rel = view.relationships[rel_name]
    rel_view = view.view_instance(rel.tgt_class)
    many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
    is_included = view.path_is_included(rel_include_path)
    query = view.related_query(obj.obj_id, rel, full_object=is_included)
    query = wf.execute_stage(
        view, stages, 'alter_related_query', query
    )
    rel_objs = list(
        get_altered_objects(
            view,
            stages,
            'alter_related_result',
            query,
            view.related_limit(rel)
        )
    )
    rel_results = wf.Results(
        rel_view,
        objects=rel_objs,
        many=many,
        is_included=is_included
    )
    if is_included:
        for rel_obj in rel_results.objects:
            for rel_rel_name in rel_obj.view.relationships:
                if wf.follow_rel(rel_obj.view, rel_rel_name, include_path=rel_include_path):
                    rel_obj.related[rel_rel_name] = get_related(
                        rel_obj,
                        rel_rel_name,
                        stages,
                        include_path=rel_include_path
                    )
    if many:
        rel_results.limit = view.related_limit(rel)
    return rel_results


def fill_related(stages, obj, include_path=None):
    view = obj.view
    if include_path is None:
        include_path = []
    for rel_name, rel in view.relationships.items():
        rel_include_path = include_path + [rel_name]
        is_included = False
        if '.'.join(rel_include_path) in view.requested_include_names():
            is_included = True
        if rel_name not in view.requested_relationships and not is_included:
            continue
        if not view.mapped_info_from_name(rel_name).get('visible', True):
            continue

        rel_view = view.view_instance(rel.tgt_class)
        query = view.related_query(obj.obj_id, rel, full_object=is_included)
        many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
        if many:
            count = query.count()
            limit = view.related_limit(rel)
            query = query.limit(limit)
        query = wf.execute_stage(
            view, stages, 'alter_related_query', query
        )

        try:
            rel_results_objs = [wf.ResultObject(rel_view, o) for o in query.all()]
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest(str(exc.orig))
        rel_results = wf.Results(
            rel_view,
            objects=rel_results_objs,
            many=many,
            is_included=is_included
        )
        rel_results = wf.execute_stage(
            view, stages, 'alter_related_results', rel_results
        )
        if is_included:
            for rel_obj in rel_results.objects:
                fill_related(stages, rel_obj, include_path=rel_include_path)
        obj.related[rel_name] = rel_results
        if many:
            obj.related[rel_name].count = count
            obj.related[rel_name].limit = limit


def get_alter_handler(view, obj, pdata, stage_name='alter_data'):
    reason = "Permission denied."
    predicate = view.permission_filter('get', stage_name)
    pred = view.permission_to_dict(predicate(obj))
    if pred['id']:
        reject_atts = obj.attribute_mask - pred['attributes']
        obj.attribute_mask &= pred['attributes']
        # record rejected atts
        view.pj_shared.rejected.reject_attributes(
            obj.tuple_identifier,
            reject_atts,
            reason,
        )
        reject_rels = obj.rel_mask - pred['relationships']
        obj.rel_mask &= pred['relationships']
        # record rejected rels
        view.pj_shared.rejected.reject_relationships(
            obj.tuple_identifier,
            reject_rels,
            reason,
        )
    else:
        view.pj_shared.rejected.reject_object(obj.tuple_identifier, reason)
    return obj


def permission_handler(endpoint_name, stage_name):
    def apply_results_filter(results, stage_name, view):
        try:
            filter = results.view.permission_filter('get', stage_name)
        except KeyError:
            return results
        results.filter(filter)
        try:
            obj = results.objects[0].object
        except IndexError:
            pass
        return results

    def get_alter_direct_results_handler(view, results, pdata):
        results = apply_results_filter(results, 'alter_direct_results', view)
        if not results.many and results.rejected_objects:
            raise HTTPNotFound('No item {} in {}'.format(view.obj_id, view.collection_name))
        return results

    def get_alter_related_results_handler(view, results, pdata):
        return apply_results_filter(results, 'alter_related_results', view)

    def get_alter_results_handler(view, results, pdata):
        apply_results_filter(results, 'alter_results', view)
        if not results.many and results.rejected_objects:
            raise HTTPNotFound('No item {} in {}'.format(view.obj_id, view.collection_name))
        for obj in results.objects:
            for (rel_name, rel_results) in obj.related.items():
                apply_results_filter(rel_results, 'alter_results', view)
        return results

    handlers = {
        'get': {
            'alter_direct_results': get_alter_direct_results_handler,
            'alter_related_results': get_alter_related_results_handler,
            'alter_result': get_alter_handler,
            'alter_related_result': partial(get_alter_handler, stage_name='alter_related_result'),
            'alter_results': get_alter_results_handler,
        }
    }
    for ep in ('collection_get', 'related_get', 'relationships_get'):
        handlers[ep] = handlers['get']
    return handlers[endpoint_name][stage_name]
