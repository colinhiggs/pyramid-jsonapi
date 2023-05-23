import pyramid_jsonapi.workflow as wf
import sqlalchemy

from itertools import islice
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPInternalServerError,
)
from . import stages
from ...http_query import QueryInfo


def workflow(view, stages):
    query = view.base_collection_query()
    query = view.query_add_sorting(query)
    query = view.query_add_filtering(query)

    qinfo = view.query_info
    pinfo = qinfo.paging_info
    count = None

    if pinfo.start_type == 'after':
        if qinfo.pj_include_count:
            count = full_search_count(view, stages)
        # We just add filters here. The necessary joins will have been done by the
        # Sorting that after relies on.

        # Need >= or <= on all but the last prop.
        for sinfo, after in zip(qinfo.sorting_info[:-1], pinfo.after[:-1]):
            if sinfo.ascending:
                query = query.filter(sinfo.prop >= after)
            else:
                query = query.filter(sinfo.prop <= after)
        # And > or < on the last one.
        if qinfo.sorting_info[-1].ascending:
            query = query.filter(qinfo.sorting_info[-1].prop > pinfo.after[-1])
        else:
            query = query.filter(qinfo.sorting_info[-1].prop < pinfo.after[-1])

    query = wf.execute_stage(
        view, stages, 'alter_query', query
    )

    # Get the direct results from this collection (no related objects yet).
    # Stage 'alter_result' will run on each object.
    objects_iterator = wf.loop.altered_objects_iterator(
        view, stages, 'alter_result', wf.wrapped_query_all(query)
    )
    # Only do paging the slow way if page[offset] is explicitly specified in the
    # request.
    offset_count = 0
    if pinfo.start_type == 'offset':
        offset_count = sum(1 for _ in islice(objects_iterator, pinfo.offset))
    objects = list(islice(objects_iterator, pinfo.limit))
    if pinfo.start_type in ('offset', None) and qinfo.pj_include_count:
        count = offset_count + len(objects) + sum(1 for _ in objects_iterator)
    results = wf.Results(
        view,
        objects=objects,
        many=True,
        is_top=True,
        count=count,
        limit=pinfo.limit
    )

    # Fill the relationships with related objects.
    # Stage 'alter_result' will run on each object.
    for res_obj in results.objects:
        wf.loop.fill_result_object_related(res_obj, stages)

    return results.serialise()


def full_search_count(view, stages):
    # Same as normal query but only id column and don't bother with sorting.
    query = view.base_collection_query(loadonly=[view.key_column.name])
    query = view.query_add_filtering(query)
    query = wf.execute_stage(
        view, stages, 'alter_query', query
    )
    objects_iterator = wf.loop.altered_objects_iterator(
        view, stages, 'alter_result', wf.wrapped_query_all(query)
    )
    return sum(1 for _ in objects_iterator)
