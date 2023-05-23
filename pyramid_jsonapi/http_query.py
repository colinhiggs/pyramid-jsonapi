import re

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property
from pyramid.request import Request
from pyramid.settings import asbool
from pyramid.httpexceptions import HTTPBadRequest


class ColspecMixin:

    @cached_property
    def colspec(self):
        return self._colspec_value.split(':')[0].split('.')

    @cached_property
    def rels(self):
        rels = []
        vc = self.view_class
        for rname in self.colspec[:-1]:
            try:
                rel = vc.relationships[rname]
            except KeyError:
                HTTPBadRequest(f"{vc.collection_name} has no relationship {rname}")
            rels.append(rel)
            vc = self.view_class.api.view_classes[rel.tgt_class]
        return rels

    @cached_property
    def prop(self):
        if self.rels:
            vc = self.view_class.api.view_classes[self.rels[-1].tgt_class]
        else:
            vc = self.view_class
        try:
            return getattr(vc.model, self.colspec[-1])
        except AttributeError:
            raise HTTPBadRequest(f"Collection '{vc.collection_name}' has no attribute '{self.colspec[-1]}'")


@dataclass
class QueryInfo:
    view_class: 'CollectionViewBase'
    request: Request

    @cached_property
    def filter_info(self):
        return tuple(
            FilterInfo(self.view_class, pname, pval)
            for pname, pval in self.request.params.items()
            if pname.startswith('filter[')
        )

    @cached_property
    def sorting_info(self):
        return tuple(
            SortingInfo(self.view_class, value)
            for value in self.request.params.get('sort', self.view_class.key_column.name).split(',')
        )

    @cached_property
    def paging_info(self):
        return PagingInfo(self.view_class, self.request, self.sorting_info)

    @cached_property
    def pj_include_count(self):
        return asbool(
            self.request.params.get('pj_include_count', 'false')
        )


@dataclass
class FilterInfo(ColspecMixin):
    view_class: 'CollectionViewBase'
    pname: str
    value: str

    @cached_property
    def _colspec_value(self):
        return self.filter_key

    @cached_property
    def filter_key(self):
        # Remove "filter[" from the start and "]" from the end of the param name.
        return self.pname[7:-1]

    @cached_property
    def filter_type(self):
        if self.filter_key.startswith('*'):
            return self.filter_key[1:]
        else:
            return 'native'

    @cached_property
    def op(self):
        try:
            _, op = self.filter_key.split(':')
        except ValueError:
            return 'eq'
        return op


@dataclass
class SortingInfo(ColspecMixin):
    view_class: 'CollectionViewBase'
    value: str
    ascending: bool = field(init=False)

    def __post_init__(self):
        if self.value.startswith('-'):
            self.ascending = False
            self.value = self.value[1:]
        else:
            self.ascending = True

    @cached_property
    def colspec(self):
        return tuple(
            self.view_class.key_column.name if cname == 'id' else cname
            for cname in self.value.split('.')
        )


@dataclass
class PagingInfo:
    view_class: 'CollectionViewBase'
    request: Request
    sorting_info: Iterable[SortingInfo] = tuple()
    start_type: str = field(init=False, default=None)
    limit: int = field(init=False)
    offset: int = field(init=False)
    before: tuple = field(init=False)
    after: tuple = field(init=False)

    def __post_init__(self):
        # We need params a lot so shorten some lines:
        params = self.request.params
        self.limit = min(
            self.view_class.max_limit,
            int(params.get('page[limit]', self.view_class.default_limit))
        )
        if self.limit < 0:
            raise HTTPBadRequest('page[limit] must not be negative.')

        possible_start_types = ('before', 'after', 'last', 'offset')
        start_types_found = [st for st in possible_start_types if f'page[{st}]' in params]
        if len(start_types_found) > 1:
            raise HTTPBadRequest(
                f'You cannot provide multiple start types: {[f"page[{st}]" for st in start_types_found]}'
            )
        if len(start_types_found) == 1:
            self.start_type = start_types_found[0]

        if self.start_type == 'before':
            self.before = params.get('page[before]').split(',')
            if len(self.before) != len(self.sorting_info):
                raise HTTPBadRequest('page[before] list must match sort column list.')
        elif self.start_type == 'after':
            self.after = params.get('page[after]').split(',')
            if len(self.after) != len(self.sorting_info):
                raise HTTPBadRequest('page[after] list must match sort column list.')
        elif self.start_type == 'offset':
            self.offset = int(params.get('page[offset]', 0))
            if self.offset < 0:
                raise HTTPBadRequest('page[offset] must not be negative.')
