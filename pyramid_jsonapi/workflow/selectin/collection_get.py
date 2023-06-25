import logging
import pyramid_jsonapi.workflow as wf
import sqlalchemy
import time

from dataclasses import dataclass
from itertools import islice
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPInternalServerError,
)
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.associationproxy import ASSOCIATION_PROXY
from sqlalchemy.orm.relationships import RelationshipProperty

from . import stages
from pyramid_jsonapi.authoriser import Authoriser
from pyramid_jsonapi.db_query import RQLQuery
from pyramid_jsonapi.http_query import QueryInfo, longest_includes, includes
from pyramid_jsonapi.serialiser import Serialiser

log = logging.getLogger(__name__)


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
    return None


def rel_opts(view, so_far=None):
    options = []
    for rel_name in view.requested_relationships.keys() & view.allowed_fields:
        rel = view.relationships[rel_name]
        opt = rel_opt(rel, so_far)
        if opt is not None:
            options.append(opt)
    return options


def selectin_options(view):
    options = []
    options.extend(rel_opts(view))
    longest = longest_includes(includes(view.request))
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
    # qinfo = view.query_info
    qinfo = QueryInfo(view.__class__, view.request)
    pinfo = qinfo.paging_info
    count = None

    # query = view.base_collection_query()
    query = RQLQuery.from_view(view, loadonly=None)
    query = view.query_add_sorting(query, reversed=pinfo.needs_reversed)
    query = view.query_add_filtering(query)
    if pinfo.is_relative:
        query = query.add_relative_paging()

    query = query.options(*selectin_options(view))

    items_iterator = query.iterate_paged(pinfo.limit)
    before_items = time.time()
    authoriser = Authoriser(view)
    if pinfo.start_type == 'offset' and pinfo.offset > 0:
        authz_items_no_record = authoriser.iterate_authorised_items(items_iterator, errors=None)
        next(islice(authz_items_no_record, pinfo.offset, pinfo.offset), None)
    errors = {}
    authz_items = authoriser.iterate_authorised_items(items_iterator, errors)
    items = list(islice(authz_items, pinfo.limit))
    log.debug(f'items fetched in {time.time() - before_items}')
    if pinfo.needs_reversed:
        items.reverse()

    if qinfo.pj_include_count:
        count = RQLQuery.from_view(view).id_only().add_filtering().pj_count()
    before_serialise = time.time()
    doc = Serialiser(view, authoriser).serialise(items, pinfo.limit, available=count, errors=errors)
    log.debug(f'items serialised in {time.time() - before_serialise}')
    return doc


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
