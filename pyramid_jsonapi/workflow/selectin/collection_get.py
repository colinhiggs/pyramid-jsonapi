import logging
import pyramid_jsonapi.workflow as wf
import sqlalchemy
import time

from itertools import islice
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPInternalServerError,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.associationproxy import ASSOCIATION_PROXY
from sqlalchemy.orm.relationships import RelationshipProperty

from . import stages, serialise, longest_includes
from ...http_query import QueryInfo

log = logging.getLogger(__name__)


def query_results(query, limit, page_size=None):
    page_size = page_size or limit
    records_yielded = 0
    # last_record = None
    cur_query = query.limit(page_size)
    records_from_cur = 0
    while records_yielded < limit:
        # Loop through records in a page:
        for record in cur_query:
            if records_yielded >= limit:
                continue
            records_yielded += 1
            records_from_cur += 1
            yield record
        # End of a page
        if records_from_cur == 0:
            break
        cur_query = query.offset(records_yielded).limit(page_size)


def rel_opt(rel, so_far=None):
    if isinstance(rel.obj, RelationshipProperty):
        if so_far:
            return so_far.selectinload(rel.instrumented)
        return selectinload(rel.instrumented)
    elif rel.obj.extension_type is ASSOCIATION_PROXY:
        ps = rel.obj.for_class(rel.src_class)
        if so_far:
            return so_far.selectinload(ps.local_attr).selectinload(ps.remote_attr)
        return selectinload(ps.local_attr).selectinload(ps.remote_attr)


def rel_opts(view, so_far=None):
    options = []
    for rel_name in view.requested_relationships.keys() & view.allowed_fields:
        rel = view.relationships[rel_name]
        options.append(rel_opt(rel, so_far))
    return options


def selectin_options(view):
    options = []
    options.extend(rel_opts(view))
    longest = longest_includes(view.request.params.get('include').split(','))
    for include in longest:
        cur_view = view
        so_far = None
        for rel_name in include:
            rel = cur_view.relationships[rel_name]
            so_far = rel_opt(rel, so_far)
            rel_view = cur_view.view_instance(rel.tgt_class)
            options.extend(rel_opts(rel_view, so_far))
            cur_view = rel_view
    return options


def workflow(view, stages):
    wf_start = time.time()
    log.debug(f'{wf_start} start selectin workflow')
    qinfo = view.query_info
    pinfo = qinfo.paging_info
    count = None

    query = view.base_collection_query()
    query_reversed = False
    if pinfo.start_type in ('last', 'before'):
        # These start types need to fetch records backwards (relative to their
        # nominal sort order) and reverse them before serialising.
        query_reversed = True
    query = view.query_add_sorting(query, reversed=query_reversed)
    query = view.query_add_filtering(query)

    if pinfo.start_type in ('after', 'before'):
        if qinfo.pj_include_count:
            count = full_search_count(view, stages)

        # We just add filters here. The necessary joins will have been done by the
        # Sorting that after relies on.
        # Need >= or <= on all but the last prop.
        for sinfo, after in zip(qinfo.sorting_info[:-1], pinfo.page_start[:-1]):
            ascending = not sinfo.ascending if query._pj_reversed else sinfo.ascending
            if ascending:
                query = query.filter(sinfo.prop >= after)
            else:
                query = query.filter(sinfo.prop <= after)
        # And > or < on the last one.
        ascending = qinfo.sorting_info[-1].ascending
        ascending = not ascending if query._pj_reversed else ascending
        if ascending:
            query = query.filter(qinfo.sorting_info[-1].prop > pinfo.page_start[-1])
        else:
            query = query.filter(qinfo.sorting_info[-1].prop < pinfo.page_start[-1])

    query = query.options(*selectin_options(view))

    incs = {}
    inc_paths = []
    inc_paths_str = view.request.params.get('include')
    if inc_paths_str:
        inc_paths = inc_paths_str.split(',')
    for inc in inc_paths:
        cur_view = view
        rel_names = inc.split('.')
        cur_path = []
        for rel_name in rel_names:
            cur_path.append(rel_name)
            cur_path_str = '.'.join(cur_path)
            if cur_path_str not in incs:
                rel = cur_view.relationships[rel_name]
                rel_view = cur_view.view_instance(rel.tgt_class)
                incs[cur_path_str] = dict(rel=rel, view=rel_view)
            cur_view = rel_view

    # for val in incs.values():
    #     rel_view = val['view']
    #     for rel_name in rel_view.requested_relationships.keys() & rel_view.allowed_fields:
    #         rel = rel_view.relationships[rel_name]
    #         query.options(selectinload(rel))

    items_iterator = query_results(query, pinfo.limit)
    offset_count = 0
    if pinfo.start_type == 'offset':
        offset_count = sum(1 for _ in islice(items_iterator, pinfo.offset))
    items = list(items_iterator)
    if query_reversed:
        items.reverse()
    if pinfo.start_type in ('offset', None) and qinfo.pj_include_count:
        count = offset_count + len(items) + sum(1 for _ in items_iterator)

    doc = serialise(items, view, incs)
    return doc

    # log.debug(f'  {time.time() - wf_start} start gathering direct results')
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
    # log.debug(objects[0].object.uuns)
    # log.debug(objects[0].object.jobs)
    # log.debug(f'  {time.time() - wf_start} got the objects')
    if query_reversed:
        objects.reverse()
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

    # for res_obj in results.objects:
    #     wf.loop.fill_result_object_related(res_obj, stages)
    # log.debug(f'  {time.time() - wf_start} filled_related')

    doc = results.serialise()
    # log.debug(f'  {time.time() - wf_start} serialised')
    return wf.Doc(doc)


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
