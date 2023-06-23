import pyramid_jsonapi.workflow as wf
import sqlalchemy

from typing import Sequence

stages = (
    'alter_result',
)


def serialise_item(item, view, as_identifier=False):
    if item is None:
        return None
    ser = {
        'type': view.collection_name,
        'id': str(getattr(item, view.key_column.name))
    }
    if as_identifier:
        return ser
    ser['attributes'] = {}
    ser['relationships'] = {}
    for attr in view.requested_attributes:
        ser['attributes'][attr] = getattr(item, attr)
    for rel_name, rel in view.requested_relationships.items():
        ser['relationships'][rel_name] = rel_dict = {}
        rel_view = view.view_instance(rel.tgt_class)
        if rel.to_many:
            rel_dict['data'] = [
                serialise_item(rel_item, rel_view, as_identifier=True)
                for rel_item in getattr(item, rel_name)
            ]
        else:
            rel_dict['data'] = serialise_item(getattr(item, rel_name), rel_view, as_identifier=True)
    return ser


def include(view, item, include_list, included_dict):
    if not include_list:
        return
    rel_name = include_list[0]
    rel = view.relationships[rel_name]
    rel_view = view.view_instance(rel.tgt_class)
    rel_include_list = include_list[1:]
    rel_items = getattr(item, rel_name)
    if rel.to_one:
        rel_items = [rel_items]
    for rel_item in rel_items:
        ref_tuple = (rel_view.collection_name, str(getattr(rel_item, rel_view.key_column.name)))
        if ref_tuple not in included_dict:
            included_dict[ref_tuple] = serialise_item(rel_item, rel_view)
        if rel_include_list:
            include(rel_view, rel_item, rel_include_list, included_dict)


def serialise(data, view, includes, is_top=True, included=None):
    ser = wf.Doc()
    included_dict = {}
    if isinstance(data, Sequence):
        many = True
        my_data = data
    else:
        many = False
        my_data = [data]
    ser_data = [serialise_item(item, view) for item in my_data]
    if many:
        ser['data'] = ser_data
    else:
        ser['data'] = ser_data[0]
    for item in my_data:
        for inc in longest_includes(view.request.params.get('include').split(',')):
            include(view, item, inc, included_dict)
        ser['included'] = [o for o in included_dict.values()]
    return ser


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
