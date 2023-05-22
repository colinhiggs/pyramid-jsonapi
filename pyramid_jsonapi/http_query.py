import re

from dataclasses import dataclass, field
from functools import cached_property
from pyramid.request import Request
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
            vc = rel.tgt_class
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
        # return PagingInfo(self.view_class, self.request)
        pass


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
    pass
