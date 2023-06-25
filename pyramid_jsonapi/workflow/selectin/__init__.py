import pyramid_jsonapi.workflow as wf
import sqlalchemy

from typing import Sequence
from pyramid_jsonapi.permissions import Targets, PermissionTarget

stages = (
    'alter_result',
)


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
            # rel_view = view.view_instance(rel.tgt_class)
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
        ser_data = [self.serialise_item(item) for item in my_data]
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
            'errors': errors,
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
        return ser


def includes(request):
    incs = request.params.get('include')
    if not incs:
        return []
    return incs.split(',')


def include_chain(include):
    chain = []
    names = include.split('.')
    for i in range(len(names)):
        chain.append(tuple(names[:i+1]))
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
