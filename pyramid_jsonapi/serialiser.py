import pyramid_jsonapi.workflow as wf

from typing import Sequence
from pyramid_jsonapi.http_query import longest_includes, includes
from pyramid_jsonapi.permissions import Targets, PermissionTarget


class Serialiser:
    def __init__(self, view, authoriser=None) -> None:
        self.view = view
        self.authoriser = authoriser
        self.serialised_id_count = 0
        self.serialised_count = 0

    def serialise_item(self, item, errors=None, as_identifier=False):
        if item is None:
            return None
        view = self.view.view_instance(item.__class__)
        ser = {
            'type': view.collection_name,
            'id': str(view.item_id(item))
        }
        if as_identifier:
            self.serialised_id_count += 1
            return ser
        perms = self.item_permissions(item)
        ser['attributes'] = {}
        ser['relationships'] = {}
        for attr in view.requested_attributes:
            if attr not in perms.attributes:
                continue
            ser['attributes'][attr] = getattr(item, attr)
        for rel_name, rel in view.requested_relationships.items():
            if rel_name not in perms.relationships:
                continue
            ser['relationships'][rel_name] = rel_dict = {}
            if rel.to_many:
                rel_dict['data'] = [
                    self.serialise_item(rel_item, errors=errors, as_identifier=True)
                    for rel_item in
                    self.authorised_seq(getattr(item, rel_name), errors)
                ]
            else:
                rel_item = getattr(item, rel_name)
                if self.authoriser:
                    rel_dict['data'] = self.serialise_item(
                        self.authoriser.authorised_item(rel_item, errors), as_identifier=True
                    )
                else:
                    rel_dict['data'] = self.serialise_item(rel_item, as_identifier=True)
        self.serialised_count += 1
        return ser

    def include(self, item, include_list, included_dict):
        if not include_list:
            return
        view = self.view.view_instance(item.__class__)
        rel_name = include_list[0]
        rel = view.relationships[rel_name]
        rel_view = view.view_instance(rel.tgt_class)
        rel_include_list = include_list[1:]
        rel_items = getattr(item, rel_name)
        if rel.to_one:
            rel_items = [rel_items]
        for rel_item in rel_items:
            if rel_item is None:
                continue
            ref_tuple = (rel_view.collection_name, str(getattr(rel_item, rel_view.key_column.name)))
            if ref_tuple not in included_dict:
                included_dict[ref_tuple] = rel_item
            if rel_include_list:
                self.include(rel_item, rel_include_list, included_dict)

    def item_permissions(self, item):
        if self.authoriser:
            return self.authoriser.item_permissions(item)
        return self.view.view_instance(item.__class__).permission_all

    def authorised_seq(self, seq, errors):
        if self.authoriser:
            return self.authoriser.iterate_authorised_items(seq, errors)
        return seq

    def serialise(self, data, limit, available=None, errors=None):
        ser = wf.Doc()
        included_dict = {}
        self.serialised_id_count = 0
        self.serialised_count = 0
        if isinstance(data, Sequence):
            many = True
            my_data = data
        else:
            many = False
            my_data = [data]
        ser_data = [self.serialise_item(item, errors) for item in my_data]
        if many:
            ser['data'] = ser_data
        else:
            ser['data'] = ser_data[0]
        for item in my_data:
            for inc in longest_includes(includes(self.view.request)):
                self.include(item, inc, included_dict)
            ser['included'] = [
                self.serialise_item(o) for o in self.authorised_seq(included_dict.values(), errors)
            ]
        ser['meta'] = {
            'serialised_count': self.serialised_count,
            'serialised_id_count': self.serialised_id_count,
            'rejected': errors,
        }
        ser['meta'].update(
            {
                'results': {
                    'available': available,
                    'limit': limit,
                    # 'returned': len(self.objects)
                }
            }
        )
        if many:
            ser['links'] = links = {}
            if self.view.query_info.paging_info.start_type == 'offset':
                links.update(self.offset_pagination_links(available))
            elif self.view.query_info.paging_info.is_relative:
                links.update(self.before_after_pagination_links(my_data))
        return ser

    def offset_pagination_links(self, count):
        links = {}
        req = self.view.request
        route_name = req.matched_route.name
        qinfo = self.view.query_info
        _query = {'page[limit]': qinfo.paging_info.limit}
        _query['sort'] = ','.join(qi.value for qi in qinfo.sorting_info)
        if req.params.get('include'):
            _query['include'] = req.params.get('include')
        for finfo in qinfo.field_info:
            _query[finfo.key] = finfo.val
        for filtr in qinfo.filter_info:
            _query[filtr.pname] = filtr.value

        # First link.
        links['first'] = req.route_url(
            route_name, _query={**_query, 'page[offset]': 0}, **req.matchdict
        )

        # Next link.
        next_offset = qinfo.paging_info.offset + qinfo.paging_info.limit
        if count is None or next_offset < count:
            _query['page[offset]'] = next_offset
            links['next'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Previous link.
        if qinfo.paging_info.offset > 0:
            prev_offset = qinfo.paging_info.offset - qinfo.paging_info.limit
            if prev_offset < 0:
                prev_offset = 0
            _query['page[offset]'] = prev_offset
            links['prev'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        # Last link.
        if count is not None:
            _query['page[offset]'] = (
                max((count - 1), 0) //
                qinfo.paging_info.limit
            ) * qinfo.paging_info.limit
            links['last'] = req.route_url(
                route_name, _query=_query, **req.matchdict
            )

        return links

    def before_after_pagination_links(self, data):
        links = {}
        req = self.view.request
        route_name = req.matched_route.name
        qinfo = self.view.query_info
        _query = {'page[limit]': qinfo.paging_info.limit}
        _query['sort'] = ','.join(str(qi) for qi in qinfo.sorting_info)
        for filtr in qinfo.filter_info:
            _query[filtr.pname] = filtr.value
        if req.params.get('include'):
            _query['include'] = req.params.get('include')
        for finfo in qinfo.field_info:
            _query[finfo.key] = finfo.val
        for filtr in qinfo.filter_info:
            _query[filtr.pname] = filtr.value

        # First link.
        links['first'] = req.route_url(
            route_name, _query={**_query, 'page[first]': 1}, **req.matchdict
        )

        # Previous link.
        # vals = []
        # for sinfo in qinfo.sorting_info:
        #     val = self.objects[0].object
        #     for col in sinfo.colspec:
        #         val = getattr(val, col)
        #     vals.append(str(val))
        # _query['page[before]'] = ','.join(vals)
        _query_prev = None
        if data:
            _query_prev = {**_query, 'page[before_id]': str(self.view.item_id(data[0]))}
        else:
            if qinfo.paging_info.start_type in ('after', 'after_id', 'last'):
                # off the end of a list of pages. Link to last page.
                _query_prev = {**_query, 'page[last]': 1}
            # Otherwise either an empty search (no prev or next) or before beginning (no prev)
        if qinfo.paging_info.start_type == 'first':
            _query_prev = None
        if _query_prev:
            links['prev'] = req.route_url(
                route_name, _query=_query_prev, **req.matchdict
            )

        # Next link.
        # vals = []
        # for sinfo in qinfo.sorting_info:
        #     val = self.objects[-1].object
        #     for col in sinfo.colspec:
        #         val = getattr(val, col)
        #     vals.append(str(val))
        # _query['page[after]'] = ','.join(vals)
        _query_next = None
        if data:
            _query_next = {**_query, 'page[after_id]': str(self.view.item_id(data[-1]))}
        else:
            if qinfo.paging_info.start_type in ('before', 'before_id', 'first'):
                # before beginning of a list of pages. Link to first page.
                _query_next = {**_query, 'page[first]': 1}
            # Otherwise either an empty search (no prev or next) or after end (no next)
        if qinfo.paging_info.start_type == 'last':
            _query_next = None
        if _query_next:
            links['next'] = req.route_url(
                route_name, _query=_query_next, **req.matchdict
            )

        # Last link.
        _query['page[last]'] = '1'
        _query_last = {**_query, 'page[last]': 1}
        links['last'] = req.route_url(
            route_name, _query=_query_last, **req.matchdict
        )

        return links
