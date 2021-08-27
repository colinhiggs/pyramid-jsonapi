import sqlalchemy
import pyramid_jsonapi.workflow as wf

from itertools import (
    islice,
)
from pyramid.httpexceptions import (
    HTTPInternalServerError,
    HTTPBadRequest,
)
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE,
)
from . import stages


def get_results(view, stages):
    qinfo = view.rel_view.collection_query_info(view.request)
    rel_stages = getattr(view.rel_view, 'related_get').stages
    limit = qinfo['page[limit]']
    count = None
    # We will need the original object with id view.obj_id.
    obj = wf.loop.get_one_altered_result_object(
        view, stages, view.single_item_query()
    )
    if view.rel.queryable:
        query = view.related_query(obj.object, view.rel)
    else:
        rel_objs = getattr(obj.object, view.rel.name)
    # rel_objs = getattr(obj.object, view.rel.name)

    if view.rel.direction is ONETOMANY or view.rel.direction is MANYTOMANY:
        many = True
        if view.rel.queryable:
            query = view.rel_view.query_add_sorting(query)
            query = view.rel_view.query_add_filtering(query)
            query = wf.execute_stage(view.rel_view, rel_stages, 'alter_query', query)
            rel_objs_iterable = wf.wrapped_query_all(query)
        else:
            rel_objs_iterable = rel_objs
        objects_iterator = wf.loop.altered_objects_iterator(
            view.rel_view, rel_stages, 'alter_result', rel_objs_iterable
        )
        offset_count = 0
        if 'page[offset]' in view.request.params:
            offset_count = sum(1 for _ in islice(objects_iterator, qinfo['page[offset]']))
        res_objs = list(islice(objects_iterator, limit))
        if(qinfo['pj_include_count']):
            count = offset_count + len(res_objs) + sum(1 for _ in objects_iterator)
    else:
        many = False
        if view.rel.queryable:
            query = wf.execute_stage(
                view.rel_view, rel_stages, 'alter_query', query
            )
            res_objs = [
                wf.loop.get_one_altered_result_object(
                    view.rel_view, rel_stages, query
                )
            ]
        else:
            res_objs = [wf.ResultObject(view.rel_view, rel_objs)]
        if(qinfo['pj_include_count']):
            count = 1

    results = wf.Results(
        view.rel_view,
        objects=res_objs,
        many=many,
        is_top=True,
        count=count,
        limit=limit
    )

    # Fill the relationships with related objects.
    # Stage 'alter_result' will run on each object.
    for res_obj in results.objects:
        wf.loop.fill_result_object_related(res_obj, rel_stages)

    return results


def workflow(view, stages):
    return get_results(view, stages).serialise()
