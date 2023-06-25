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

from . import stages, Serialiser, longest_includes, includes
from ...db_query import RQLQuery
from ...http_query import QueryInfo

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


def rel_opts(view, so_far=None):
    options = []
    for rel_name in view.requested_relationships.keys() & view.allowed_fields:
        rel = view.relationships[rel_name]
        options.append(rel_opt(rel, so_far))
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


from cachetools import cached
from cachetools.keys import hashkey
from functools import partial
from pyramid_jsonapi.permissions import Targets, PermissionTarget
from ...collection_view import CollectionViewBase
@dataclass
class Authoriser:
    view: CollectionViewBase

    def iterate_authorised_items(self, it, errors):
        return filter(partial(self.authorise_item, errors=errors), it)
    
    def authorise_item(self, item, errors):
        if item is None:
            return True
        perms = self.item_permissions(item)
        if not perms.id and errors is not None:
            view = self.view.view_instance(item.__class__)
            ref = f'{view.collection_name}[{view.get_id(item)}]'
            errors[ref] = 'GET id denied'
            return False
        return True

    def authorised_item(self, item, errors):
        if self.authorise_item(item, errors):
            return item
        return None

    def item_permissions_key(self, item):
        return (
            self.view.collection_name,
            str(getattr(item, self.view.key_column.name))
        )

    @cached(cache={}, key=item_permissions_key)
    def item_permissions(self, item):
        view = self.view.view_instance(item.__class__)
        pf = view.permission_filter('get', Targets.item, 'alter_item')
        return pf(item, PermissionTarget(Targets.item))


def workflow(view, stages):
    wf_start = time.time()
    log.debug(f'{wf_start} start selectin workflow')
    qinfo = view.query_info
    pinfo = qinfo.paging_info
    count = None

    # query = view.base_collection_query()
    query = RQLQuery.from_view(view, loadonly=None)
    query_reversed = False
    if pinfo.start_type in ('last', 'before'):
        # These start types need to fetch records backwards (relative to their
        # nominal sort order) and reverse them before serialising.
        query_reversed = True
    query = view.query_add_sorting(query, reversed=query_reversed)
    query = view.query_add_filtering(query)

    if pinfo.start_type in ('after', 'before'):

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

    items_iterator = query.iterate_paged(pinfo.limit)
    before_items = time.time()
    authoriser = Authoriser(view)
    if pinfo.start_type == 'offset':
        authz_items_no_record = authoriser.iterate_authorised_items(items_iterator, errors=None)
        next(islice(authz_items_no_record, pinfo.offset, pinfo.offset), None)
    errors = {}
    authz_items = authoriser.iterate_authorised_items(items_iterator, errors)
    items = list(islice(authz_items, pinfo.limit))
    log.debug(f'items fetched in {time.time() - before_items}')
    if query_reversed:
        items.reverse()

    if qinfo.pj_include_count:
        count = RQLQuery.from_view(view).id_only().add_filtering().pj_count()
    before_serialise = time.time()
    doc = Serialiser(view, authoriser).serialise(items, pinfo.limit, available=count, errors=errors)
    log.debug(f'items serialised in {time.time() - before_serialise}')
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
