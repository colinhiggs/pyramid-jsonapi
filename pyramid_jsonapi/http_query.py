import re

from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import cached_property, cache
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

    @cache
    def rel_paging_info(self, rel_path):
        return PagingInfo(self.view_class, self.request, self.sorting_info, rel_path)

    @cached_property
    def pj_include_count(self):
        return asbool(
            self.request.params.get('pj_include_count', 'false')
        )

    @cached_property
    def field_info(self):
        return tuple(
            FieldInfo(key, val) for key, val in self.request.params.items()
            if key.startswith('fields[')
        )


@dataclass
class FieldInfo:
    key: str
    val: str

    @cached_property
    def collection_name(self):
        # Remove "fields[" from the start and "]" from the end.
        return self.key[7:-1]

    @cached_property
    def field_names(self):
        return ','.split(self.val)


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
    rel_path: str = None
    start_type: str = field(init=False, default=None)
    limit: int = field(init=False)
    prefix: str = ''

    def __post_init__(self):
        # We need params a lot so shorten some lines:
        if self.rel_path:
            self.prefix = f'{self.rel_path}:'
        else:
            self.prefix = ''
        prefix = self.prefix
        params = self.request.params
        self.limit = min(
            self.view_class.max_limit,
            int(params.get(f'page[{prefix}limit]', self.view_class.default_limit))
        )
        if self.limit < 0:
            raise HTTPBadRequest(f'page[{prefix}limit] must not be negative.')

        possible_start_types = (
            'before', 'after', 'before_id', 'after_id',
            'first', 'last',
            'offset'
        )
        start_types_found = [st for st in possible_start_types if f'page[{prefix}{st}]' in params]
        if len(start_types_found) > 1:
            raise HTTPBadRequest(
                f'You cannot provide multiple start types: {[f"page[{prefix}{st}]" for st in start_types_found]}'
            )
        if len(start_types_found) == 1:
            self.start_type = start_types_found[0]
        self.start_type = self.start_type or 'first'

    @cached_property
    def start_arg(self):
        return self.request.params.get(f'page[{self.prefix}{self.start_type}]')

    @cached_property
    def before_after(self):
        if self.is_terminal:
            return []
        args = self.start_arg.split(',')
        if len(args) != len(self.sorting_info):
            raise HTTPBadRequest(f'page[{self.prefix}{self.start_type}] list must match sort column list.')
        return args

    @cached_property
    def before(self):
        return self.before_after

    @cached_property
    def after(self):
        return self.before_after

    @cached_property
    def item_id(self):
        return self.start_arg

    @cached_property
    def offset(self):
        offset = int(self.request.params.get('page[offset]', 0))
        if offset < 0:
            raise HTTPBadRequest('page[offset] must not be negative.')
        return offset

    @cached_property
    def is_relative(self):
        return self.start_type in {'before', 'after', 'before_id', 'after_id', 'first', 'last'}
    
    @cached_property
    def is_terminal(self):
        return self.start_type in {'first', 'last'}

    @cached_property
    def needs_reversed(self):
        if self.start_type in {'before', 'before_id', 'last'}:
            return True
        return False

    @cached_property
    def page_start(self):
        return getattr(self, self.start_type)


def includes(request):
    incs = request.params.get('include')
    if not incs:
        return []
    return incs.split(',')


def include_chain(include):
    chain = []
    names = include.split('.')
    for i in range(len(names)):
        chain.append(tuple(names[:i + 1]))
    return chain


def longest_includes(includes):
    seen = set()
    longest = set()
    for inc in includes:
        inc_chain = include_chain(inc)
        if inc_chain[-1] in seen:
            continue
        seen |= set(inc_chain)
        longest -= set(inc_chain[:-1])
        longest.add(inc_chain[-1])
    return longest
