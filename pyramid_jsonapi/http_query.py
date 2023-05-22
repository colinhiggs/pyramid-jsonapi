import re

from dataclasses import dataclass
from functools import cached_property
from pyramid.request import Request
from pyramid.httpexceptions import HTTPBadRequest


@dataclass
class InfoBase:
    view_class: 'CollectionViewBase'
    request: Request


@dataclass
class QueryInfo(InfoBase):

    @cached_property
    def filters(self):
        return tuple(
            FilterInfo(self.view_class, pname, pval)
            for pname, pval in self.request.params.items()
            if pname.startswith('filter[')
        )

    @cached_property
    def sorting(self):
        return SortingInfo(self.view_class, self.request)

    @cached_property
    def paging(self):
        return PagingInfo(self.view_class, self.request)


@dataclass
class FilterInfo:
    view_class: 'CollectionViewBase'
    pname: str
    value: str

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
    def colspec(self):
        return self.filter_key.split(':')[0].split('.')

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

    @cached_property
    def op(self):
        try:
            _, op = self.filter_key.split(':')
        except ValueError:
            return 'eq'
        return op


@dataclass
class SortingInfo(InfoBase):
    pass


@dataclass
class PagingInfo(InfoBase):
    pass
