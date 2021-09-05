import pyramid_jsonapi.workflow as wf
import sqlalchemy

from functools import (
    partial
)
from itertools import (
    islice,
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

from pyramid_jsonapi.permissions import (
    PermissionTarget,
    Targets,
)

stages = (
    'alter_query',
    'alter_related_query',
    'alter_result',
    'before_write_item',
)


def get_one_altered_result_object(view, stages, query):
    res_obj = wf.execute_stage(
        view, stages, 'alter_result',
        wf.ResultObject(view, view.get_one(query, view.not_found_message))
    )
    if res_obj.tuple_identifier in view.pj_shared.rejected.rejected['objects']:
        raise HTTPForbidden(view.not_found_message)
    return res_obj


def altered_objects_iterator(view, stages, stage_name, objects_iterable):
    """
    Return an iterator of objects from objects_iterable filtered and altered by
    the stage_name stage.
    """
    return filter(
        lambda o: o.tuple_identifier not in view.pj_shared.rejected.rejected['objects'],
        map(
            partial(wf.execute_stage, view, stages, stage_name),
            (wf.ResultObject(view, o) for o in objects_iterable)
        )
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
    if rel.queryable:
        query = view.related_query(obj.object, rel, full_object=is_included)
        # print(query)
        query = wf.execute_stage(
            view, stages, 'alter_related_query', query
        )
        # print('*' * 80)
        # print(rel_name)
        # print(query.statement.compile(view.dbsession.bind))
        # print('*' * 80)
        objects_iterable = wf.wrapped_query_all(query)
    else:
        objects_iterable = getattr(obj.object, rel_name)
        if not many:
            objects_iterable = [objects_iterable]
    rel_objs = list(
        islice(
            altered_objects_iterator(
                rel_view, stages,
                'alter_result',
                objects_iterable,
            ),
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


def fill_result_object_related(res_obj, stages):
    view = res_obj.view
    for rel_name in view.relationships:
        if wf.follow_rel(view, rel_name):
            res_obj.related[rel_name] = get_related(
                res_obj, rel_name, stages
            )


def shp_get_item_alter_result(obj, view, stage, view_method):
    reason = "Permission denied."
    item_pf = view.permission_filter('get', Targets.item, stage)
    # pred = view.permission_to_dict(predicate(obj))
    pred = item_pf(obj, PermissionTarget(Targets.item))
    if not pred.id:
        view.pj_shared.rejected.reject_object(obj.tuple_identifier, reason)

    reject_atts = obj.attribute_mask - pred.attributes
    obj.attribute_mask &= pred.attributes
    # record rejected atts
    view.pj_shared.rejected.reject_attributes(
        obj.tuple_identifier,
        reject_atts,
        reason,
    )

    rel_pf = view.permission_filter('get', Targets.relationship, stage)
    reject_rels = {
        rel for rel in obj.rel_mask
        if not rel_pf(obj, PermissionTarget(Targets.relationship, rel))
    }
    obj.rel_mask -= reject_rels
    # record rejected rels
    view.pj_shared.rejected.reject_relationships(
        obj.tuple_identifier,
        reject_rels,
        reason,
    )
    return obj


def permission_handler(endpoint_name, stage_name):
    handlers = {
        'item_get': {
            'alter_result': shp_get_item_alter_result,
        },
        'collection_get': {
            'alter_result': shp_get_item_alter_result,
        },
        'related_get': {
            'alter_result': shp_get_item_alter_result,
        },
        'relationships_get': {
            'alter_result': shp_get_item_alter_result,
        },
    }
    # for ep in ('collection_get', 'related_get', 'relationships_get'):
    #     handlers[ep] = handlers['item_get']
    return handlers[endpoint_name][stage_name]
