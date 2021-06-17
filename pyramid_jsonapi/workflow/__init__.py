import functools
import importlib
import json
import logging
import re
import sqlalchemy

from collections import (
    deque,
    abc,
)

from functools import (
    partial,
    partialmethod
)

from sqlalchemy.orm import load_only
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)

from pyramid.httpexceptions import (
    HTTPNotFound,
    HTTPForbidden,
    HTTPBadRequest,
    HTTPConflict,
    HTTPUnsupportedMediaType,
    HTTPNotAcceptable,
    HTTPError,
    HTTPFailedDependency,
    HTTPInternalServerError,
    status_map,
)
from sqlalchemy.orm.relationships import RelationshipProperty


import pyramid_jsonapi


def make_method(name, api):
    settings = api.settings
    wf_module = importlib.import_module(
        getattr(settings, 'workflow_{}'.format(name))
    )

    # Set up the stages.
    stages = {
        'validate_request': deque(),
        'alter_request': deque(),
        'alter_document': deque(),
        'validate_response': deque()
    }
    # stage_order = ['alter_request', 'validate_request', ]
    for stage_name in wf_module.stages:
        stages[stage_name] = deque()
        # stage_order.append(stage_name)
    # stage_order.append('alter_results')
    # stage_order.append('validate_response')
    stages['validate_request'].append(validate_request_headers)
    stages['validate_request'].append(validate_request_valid_json)
    stages['validate_request'].append(validate_request_common_validity)
    stages['validate_request'].append(validate_request_object_exists)
    stages['alter_request'].append(alter_request_add_info)
    stages['alter_document'].append(alter_document_self_link)
    if name.endswith('get'):
        stages['alter_document'].append(alter_document_add_returned_count)
    if api.settings.debug_meta:
        stages['alter_document'].append(alter_document_debug_info)

    # Stack the deques.
    for stage_name, stage_deque in stages.items():
        try:
            item = getattr(wf_module, 'stage_' + stage_name)
        except AttributeError:
            # If there isn't one, move on.
            continue
        if callable(item):
            # If item is callable just append it.
            stage_deque.append(item)
        else:
            # item should be an iterable of callables. Append them.
            for handler in item:
                stage_deque.append(handler)

    # Build a set of expected responses.
    ep_dict = api.endpoint_data.endpoints
    parts = name.split('_')
    if len(parts) == 1:
        endpoint = 'item'
        http_method = parts[0].upper()
    else:
        endpoint, http_method = parts
        http_method = http_method.upper()
    responses = set(
        ep_dict['responses'].keys() |
        ep_dict['endpoints'][endpoint]['responses'].keys() |
        ep_dict['endpoints'][endpoint]['http_methods'][http_method]['responses'].keys()
    )

    def method(view):
        view.pj_shared = SharedState(view)
        try:
            # execute_stage(view, stages, 'alter_request')
            request = execute_stage(
                view, stages, 'alter_request', view.request
            )
            request = execute_stage(
                view, stages, 'validate_request', request
            )
            view.request = request
            document = wf_module.workflow(view, stages)
            document = execute_stage(
                view, stages, 'alter_document', document
            )
            ret = execute_stage(
                view, stages, 'validate_response', document
            )
        except Exception as exc:
            if exc.__class__ not in responses:
                logging.exception(
                    "Invalid exception raised: %s for route_name: %s path: %s",
                    exc.__class__,
                    view.request.matched_route.name,
                    view.request.current_route_path()
                )
                if isinstance(exc, HTTPError):
                    if 400 <= int(exc.code) < 500:  # pylint:disable=no-member
                        raise HTTPBadRequest("Unexpected client error: {}".format(exc))
                else:
                    raise HTTPInternalServerError("Unexpected server error.")
            raise

        # Log any responses that were not expected.
        response_class = status_map[view.request.response.status_code]
        if response_class not in responses:
            logging.error(
                "Invalid response: %s for route_name: %s path: %s",
                response_class,
                view.request.matched_route.name,
                view.request.current_route_path()
            )
        return ret

    # Make stages available as an attribute of the method.
    method.stages = stages

    return method


def wrapped_query_all(query):
    """
    Wrap query.all() so that SQLAlchemy exceptions can be transformed to
    http ones.
    """
    try:
        for obj in query.all():
            yield obj
    except sqlalchemy.exc.DataError as exc:
        raise HTTPBadRequest(str(exc.orig))


def follow_rel(view, rel_name, include_path=None):
    """
    True if rel_name should be followed and added.
    """
    include_path = include_path or []
    rel_include_path = include_path + [rel_name]
    if rel_name not in view.requested_relationships and not view.path_is_included(rel_include_path):
        return False
    if not view.mapped_info_from_name(rel_name).get('visible', True):
        return False
    return True


def partition(items, predicate=bool):
    trues, falses = [], []
    for item in items:
        if predicate(item):
            trues.append(item)
        else:
            falses.append(item)
    return (trues, falses)


def execute_stage(view, stages, stage_name, arg, previous_data=None):
    for handler in stages[stage_name]:
        arg = handler(view, arg, previous_data)
    if previous_data is not None:
        previous_data[stage_name] = arg
    return arg


def partition_doc_data(doc_data, partitioner):
    if partitioner is None:
        return doc_data, []
    accepted, rejected = [], []
    for item in doc_data:
        if partitioner(item, doc_data):
            accepted.append(item)
        else:
            rejected.append(item)
    return accepted, rejected


def get_alter_document_handler(view, doc, pdata):
    data = doc['data']
    # Make it so that the data part is always a list for later code DRYness.
    # We'll put it back the way it was later. Honest ;-).
    if isinstance(data, list):
        many = True
    else:
        data = [data]
        many = False

    # Find the top level filter function to run over data.
    try:
        data_filter = partial(
            view.permission_filter('get', 'alter_document'),
            permission_sought='get',
            stage_name='alter_document',
            view_instance=view,
        )
    except KeyError:
        data_filter = None

    # Remember what was rejected so it can be removed from included later.
    rejected_set = set()
    accepted, rejected = partition_doc_data(data, data_filter)

    # Filter any related items.
    for item in data:
        for rel_name, rel_dict in item.get('relationships', {}).items():
            rel_data = rel_dict['data']
            if isinstance(rel_data, list):
                rel_many = True
            else:
                rel_data = [rel_data]
                rel_many = False
            rel_view = view.view_instance(view.relationships[rel_name].tgt_class)
            try:
                rel_filter = partial(
                    rel_view.permission_filter('get', 'alter_document'),
                    permission_sought='get',
                    stage_name='alter_document',
                    view_instance=view,
                )
            except KeyError:
                rel_filter = None
            rel_accepted, rel_rejected = partition_doc_data(rel_data, rel_filter)
            rejected_set |= {(item['type'], item['id']) for item in rel_rejected}
            if rel_many:
                rel_dict['data'] = rel_accepted
            else:
                try:
                    rel_dict['data'] = rel_accepted[0]
                except IndexError:
                    rel_dict['data'] = None

    # Time to do what we promised and put scalars back.
    if many:
        doc['data'] = accepted
    else:
        try:
            doc['data'] = accepted[0]
        except IndexError:
            if rejected:
                raise(HTTPNotFound('Object not found.'))
            else:
                doc['data'] = None

    # Remove any rejected items from included.
    included = [
        item for item in doc.get('included', {})
        if (item['type'], item['id']) not in rejected_set
    ]
    doc['included'] = included
    return doc


def collection_post_alter_request_handler(view, request, pdata):
    # Make sure there is a permission filter registered.
    try:
        pfilter = view.permission_filter('post', 'alter_request')
    except KeyError:
        return request

    obj_data = request.json_body['data']
    allowed = pfilter(obj_data)
    if allowed.get('id', True) is False:
        # Straight up forbidden to create object.
        raise HTTPForbidden('No permission to POST object:\n\n{}'.format(request.json_body['data']))
    for att_name in list(obj_data.get('attributes', {}).keys()):
        if att_name not in allowed['attributes']:
            del(obj_data['attributes'][att_name])
            # TODO: alternatively raise HTTPForbidden?
    rel_names = list(obj_data.get('relationships', {}).keys())
    for rel_name in rel_names:
        if rel_name not in allowed['relationships']:
            del(obj_data['relationships'][rel_name])
            # TODO: alternatively raise HTTPForbidden?
    # Loop through a shallow copy of obj_data['relationships'] so that we
    # can delete entries without causing problems.
    rels_copy = {}
    rels_copy.update(obj_data.get('relationships', {}))
    for rel_name, rel_dict in rels_copy.items():
        # For each of these allowed rels, look to see if the *other end*
        # of the relationship is to_one (in which case we need PATCH permission
        # to that rel in order to set it to this object) or to_many (in which
        # case we need POST permission in order to add this object to it).
        rel = view.relationships[rel_name]
        mirror_rel = rel.mirror_relationship
        # if rel.direction in (ONETOMANY, MANYTOMANY):
        #     tgt_ris = rel_dict['data']
        # else:
        #     tgt_ris = [rel_dict['data']]
        if mirror_rel:
            mirror_view = mirror_rel.view_class(view.request)
            if mirror_rel.direction in (ONETOMANY, MANYTOMANY):
                # Need POST permission on tgt_ri.mirror_rel.
                permission_sought = 'post'
            else:
                # Need PATCH permission on tgt_ri.mirror_rel.
                permission_sought = 'patch'
            try:
                mfilter = mirror_view.permission_filter(
                    permission_sought, 'alter_request'
                )
            except KeyError:
                # No filter registered - treat as always True and skip this
                # rel.
                continue
            if rel.direction in (ONETOMANY, MANYTOMANY):
                allowed_ris = []
                for tgt_ri in rel_dict['data']:
                    mallowed = mfilter(tgt_ri)
                    if mirror_rel.name in mallowed['relationships']:
                        allowed_ris.append(tgt_ri)
                    # TODO: alternatively raise HTTPForbidden?
                rel_dict['data'] = allowed_ris
            else:
                mallowed = mfilter(rel_dict['data'])
                if mirror_rel.name not in mallowed['relationships']:
                    del(obj_data['relationships'][rel_name])
                    # TODO: alternatively raise HTTPForbidden?

    request.body = json.dumps({'data': obj_data}).encode()
    return request


def relationships_post_alter_request_handler(view, request, pdata):
    # Make sure there is a permission filter registered.
    try:
        pfilter = view.permission_filter('post', 'alter_request')
    except KeyError:
        return request

    # First need permision to POST to obj.rel.
    obj_perms = pfilter({'type': view.collection_name, 'id': view.obj_id})
    if view.rel.name not in obj_perms['relationships']:
        request.body = json.dumps({'data': []}).encode()
        return request

    # We might need
    mirror_rel = view.rel.mirror_relationship
    mirror_view = mirror_rel.view_class(request)
    try:
        del_filter = view.permission_filter('delete', 'alter_request')
    except KeyError:
        del_filter = False
    try:
        m_patch_filter = mirror_view.permission_filter('patch', 'alter_request')
    except KeyError:
        m_patch_filter = False
    try:
        m_post_filter = mirror_view.permission_filter('post', 'alter_request')
    except KeyError:
        m_post_filter = False
    new_data = []
    for ri in request.json_body['data']:
        # adding = True
        if mirror_rel and (del_filter or m_patch_filter):
            # Check permission to alter other end of relationship.
            related = view.dbsession.query(
                view.rel.tgt_class
            ).filter(mirror_view.key_column == ri['id']).one_or_none()
            if related:
                related_resource = ResultObject(mirror_view, related)
            else:
                # Trying to add a related id that doesn't exist. This
                # is an error but we leave it to be caught later in the
                # standard place. In the meantime there is no point in
                # checking for permission.
                new_data.append(ri)
                continue
            if view.rel.direction is ONETOMANY:
                # Need DELETE on related.mirror.old_resource.rel
                old_resource = ResultObject(
                    view,
                    getattr(related, mirror_rel.name)
                )
                old_dict = old_resource.to_dict()
                if (
                    del_filter and old_dict and
                    view.rel.name not in del_filter(old_dict)['relationships']
                ):
                    # Not allowed to alter this relationship.
                    # print(f'No DELETE on {old_dict["type"]}/{old_dict["id"]}.{view.rel.name}')
                    continue
                # Need PATCH on related.mirror
                perms = m_patch_filter(related_resource.to_dict())
                if mirror_rel.name not in perms['relationships']:
                    # print(f'No PATCH on {related_resource.to_dict()}')
                    continue
            else:
                # MANYTOMANY
                # Need POST on related.mirror
                perms = m_post_filter(related_resource.to_dict())
                if mirror_rel.name not in perms['relationships']:
                    continue
        # if adding:
        new_data.append(ri)
    # TODO: option to select alternate behaviour
    # if len(new_data) != len(json_body['data']):
    #     raise HTTPForbidden(
    #         'No permission to POST {} to relationship {}.'.format(
    #             item, view.relname
    #         )
    #     )
    request.body = json.dumps({'data': new_data}).encode()
    return request


def patch_relationship_ar_helper(view, this_item, rel_name, rel_dict):
    rel = view.relationships[rel_name]
    mirror_rel = rel.mirror_relationship
    if not mirror_rel:
        # No mirror relationship: no need to check permissions on it.
        return rel_dict
    this_ro = ResultObject(view, this_item)
    mirror_view = mirror_rel.view_class(view.request)
    if rel.direction in (ONETOMANY, MANYTOMANY):
        # rel data will be an array of ris. We'll need permission to post,
        # delete, or patch each one on the mirror.
        # Find the current related items.
        current_related_ids = {
            str(getattr(related_item, mirror_view.key_column.name))
            for related_item in getattr(this_item, rel.name)
        }
        new_related_ids = {
            item['id'] for item in rel_dict['data']
        }
        adding = new_related_ids - current_related_ids
        removing = current_related_ids - new_related_ids
        allowed_ids = set(current_related_ids)
        # print(f'{rel.name}: cur {current_related_ids}, new {new_related_ids}')
        # print(f'  add {adding}, rem {removing}')
        if rel.direction is ONETOMANY:
            # mirror_rel is MANYTOONE and we need PATCH permission for any
            # alterations.
            try:
                m_patch_filter = mirror_view.permission_filter('patch', 'alter_request')
            except KeyError:
                return rel_dict
            for _id in adding:
                mallowed = m_patch_filter(
                    {
                        'type': mirror_view.collection_name,
                        'id': _id,
                        'relationships': {
                            mirror_rel.name: {
                                'data': this_ro.identifier()
                            }
                        }
                    }
                )
                if mirror_rel.name in mallowed['relationships']:
                    allowed_ids.add(_id)
                # TODO: alternatively raise HTTPForbidden?
            for _id in removing:
                mallowed = m_patch_filter(
                    {
                        'type': mirror_view.collection_name,
                        'id': _id,
                        'relationships': {
                            mirror_rel.name: {
                                'data': None
                            }
                        }
                    }
                )
                if mirror_rel.name in mallowed['relationships']:
                    allowed_ids.remove(_id)
                # TODO: alternatively raise HTTPForbidden?
        else:
            # mirror_rel is MANYTOMANY and we need POST permission to add or
            # DELETE permission to remove.
            try:
                m_post_filter = mirror_view.permission_filter('post', 'alter_request')
            except KeyError:
                m_post_filter = False
            try:
                m_del_filter = mirror_view.permission_filter('delete', 'alter_request')
            except KeyError:
                m_del_filter = False
            if m_post_filter:
                for _id in adding:
                    mallowed = m_post_filter(
                        {
                            'type': mirror_view.collection_name,
                            'id': _id,
                            'relationships': {
                                mirror_rel.name: {
                                    'data': this_ro.identifier()
                                }
                            }
                        }
                    )
                    if mirror_rel.name in mallowed['relationships']:
                        allowed_ids.add(_id)
                    # TODO: alternatively raise HTTPForbidden?
            if m_del_filter:
                for _id in removing:
                    mallowed = m_del_filter(
                        {
                            'type': mirror_view.collection_name,
                            'id': _id,
                            'relationships': {
                                mirror_rel.name: {
                                    'data': this_ro.identifier()
                                }
                            }
                        }
                    )
                    if mirror_rel.name in mallowed['relationships']:
                        allowed_ids.remove(_id)
                    # TODO: alternatively raise HTTPForbidden?
            else:
                allowed_ids -= removing

        rel_dict['data'] = [
            {'type': mirror_view.collection_name, 'id': _id}
            for _id in allowed_ids
        ]
    else:
        # rel.direction is MANYTOONE. There should be just one ri, or None.
        cur_related = ResultObject(mirror_view, getattr(this_item, rel.name))
        if cur_related.object is None and rel_dict['data'] is None:
            # Nothing to do.
            return rel_dict
        if str(cur_related.obj_id) == rel_dict['data'].get('id'):
            # Also nothing to do.
            return rel_dict
        if cur_related.object is not None:
            # Need DELETE permission on cur_related.mirror_rel
            try:
                m_del_filter = mirror_view.permission_filter('del', 'alter_request')
            except KeyError:
                return rel_dict
            mallowed = m_del_filter(
                {
                    'type': mirror_view.collection_name,
                    'id': cur_related.obj_id,
                    'relationships': {
                        mirror_rel.name: {
                            'data': this_ro.identifier()
                        }
                    }
                }
            )
            if mirror_rel.name not in mallowed['relationships']:
                return False
                # del(obj_data['relationships'][rel_name])
        if rel_dict['data'] is not None:
            # Need POST permission on cur_related.mirror_rel
            try:
                m_post_filter = mirror_view.permission_filter('post', 'alter_request')
            except KeyError:
                return rel_dict
            mallowed = m_post_filter(
                {
                    'type': mirror_view.collection_name,
                    'id': cur_related.obj_id,
                    'relationships': {
                        mirror_rel.name: {
                            'data': this_ro.identifier()
                        }
                    }
                }
            )
            if mirror_rel.name not in mallowed['relationships']:
                return False
                # del(obj_data['relationships'][rel_name])
    return rel_dict


def patch_alter_request_handler(view, request, pdata):
    # Make sure there is a permission filter registered.
    try:
        pfilter = view.permission_filter('patch', 'alter_request')
    except KeyError:
        return request

    obj_data = request.json_body['data']
    allowed = pfilter(obj_data)
    if allowed.get('id', True) is False:
        # Straight up forbidden to PATCH object.
        raise HTTPForbidden('No permission to PATCH object:\n\n{}'.format(request.json_body['data']))
    for att_name in list(obj_data.get('attributes', {}).keys()):
        if att_name not in allowed['attributes']:
            del(obj_data['attributes'][att_name])
            # TODO: alternatively raise HTTPForbidden?
    rel_names = list(obj_data.get('relationships', {}).keys())
    for rel_name in rel_names:
        if rel_name not in allowed['relationships']:
            del(obj_data['relationships'][rel_name])
            # TODO: alternatively raise HTTPForbidden?
    # Loop through a shallow copy of obj_data['relationships'] so that we
    # can delete entries without causing problems.
    rels_copy = {}
    rels_copy.update(obj_data.get('relationships', {}))
    this_item = view.get_item()
    for rel_name, rel_dict in rels_copy.items():
        # For each of these allowed rels, look to see if the *other end*
        # of the relationship is to_one (in which case we need PATCH permission
        # to that rel in order to set it to this object) or to_many (in which
        # case we need POST permission in order to add this object to it).
        new_rel_dict = patch_relationship_ar_helper(view, this_item, rel_name, rel_dict)
        if new_rel_dict:
            obj_data['relationships'][rel_name] = new_rel_dict
    request.body = json.dumps({'data': obj_data}).encode()
    return request


def relationships_patch_alter_request_handler(view, request, pdata):
    # Make sure there is a permission filter registered.
    try:
        pfilter = view.permission_filter('patch', 'alter_request')
    except KeyError:
        return request

    allowed = pfilter({'type': view.collection_name, 'id': view.obj_id})
    if not allowed.get('id', True):
        # Straight up forbidden to PATCH object.
        raise HTTPForbidden('No permission to PATCH object:\n\n{}'.format(request.json_body['data']))
    if view.rel.name not in allowed['relationships']:
        raise HTTPForbidden(f'No permission to PATCH {view.collection_name}/{view.obj_id}.{view.rel.name}')
    this_item = view.get_item()
    new_rel_dict = patch_relationship_ar_helper(
        view, this_item, view.rel.name,
        {'data': view.request.json_body['data']}
    )
    if new_rel_dict:
        request.body = json.dumps(new_rel_dict).encode()
    else:
        raise HTTPForbidden(f'No permission to alter remote side of {view.collection_name}/{view.obj_id}.{view.rel.name}')
    return request


def get_item(view, item_or_id=None):
    """Wrapper around view.get_item() to allow passing an item or an id."""
    if item_or_id is None:
        item_or_id = view.obj_id
    if isinstance(item_or_id, view.model):
        return item_or_id
    else:
        return view.get_item(item_or_id)


def ar_check_mirror_rel_perms(view, permission, rel, rel_dict, item_or_id=None):
    # Find the item rel is relative to.

    # Check for direct permission to alter rel.
    # filter = view.permission_filter(permission, 'alter_request', default=view.true_filter)
    # if not filter(this_item):
    #     return {'forward': False}
    mirror_rel = rel.mirror_relationship
    if not mirror_rel:
        # No mirror relationship: no need to check permissions on it. Return
        # False as a predicate value.
        return False
    # mirror_view = mirror_rel.view_class(view.request)
    report = {
        'post': {'allowed': set(), 'denied': set()},
        'patch': {'allowed': set(), 'denied': set()},
        'delete': {'allowed': set(), 'denied': set()}
    }
    # related_items = view.related_query(this_ro.obj_id, rel).all()
    rel_data = rel_dict['data']
    if rel.direction is MANYTOONE:
        # Always a list for DRYness.
        rel_data = [rel_data]
    if mirror_rel.direction is MANYTOONE:
        # Need patch permission for any alterations.
        if permission == 'post':
            adding = {'_id': 2}
    return report


def delete_alter_request_handler(view, request, pdata):
    # Make sure there is a permission filter registered.
    try:
        pfilter = view.permission_filter('delete', 'alter_request')
    except KeyError:
        return request

    this_item = view.get_item()
    this_ro = ResultObject(view, this_item)
    this_data = this_ro.serialise()
    allowed = pfilter(this_data, mask=view.everything_mask)
    if not allowed['id']:
        raise HTTPForbidden('No permission to delete {}/{}'.format(
            view.collection_name, view.obj_id
        ))
    for att_name in this_data.get('attributes', {}):
        if att_name not in allowed['attributes']:
            # Need permission to *all* attributes for delete to work sensibly.
            raise HTTPForbidden('No permission to delete {}/{}[{}]'.format(
                view.collection_name, view.obj_id, att_name
            ))
    for rel_name in this_data.get('relationships', {}):
        if rel_name not in allowed['relationships']:
            # Need permission to *all* relationships for delete to work sensibly.
            raise HTTPForbidden('No permission to delete {}/{}.{}'.format(
                view.collection_name, view.obj_id, rel_name
            ))
    for rel_name, rel_dict in this_data.get('relationships', {}).items():
        rel = view.relationships[rel_name]
        mirror_perms = ar_check_mirror_rel_perms(view, 'delete', rel, rel_dict)
        if not mirror_perms:
            # There is no mirror relationship for this rel.
            continue
        if mirror_perms['delete']['denied'] or mirror_perms['patch']['denied']:
            # At least one required delete or patch on mirror is denied.
            raise HTTPForbidden('No permission to delete {}/{}.{} by mirror relationship.'.format(
                view.collection_name, view.obj_id, rel_name
            ))
    return request


def relationships_delete_alter_request_handler(view, request, pdata):
    try:
        pfilter = partial(
            view.permission_filter('delete', 'alter_request'),
            permission_sought='delete',
            stage_name='alter_request',
            view_instance=view,
        )
    except KeyError:
        return request
    # TODO: option to select alternate behaviour
    if True:
        # Pretend that the request only contained the items which are allowed.
        new_data = [
            item for item in request.json_body['data']
            if pfilter(item, request.json_body['data'])
        ]
        request.json_body['data'] = new_data
    else:
        # Deny the whole request if we lack permission for any one item.
        for item in request.json_body['data']:
            if not pfilter(item, request.json_body['data']):
                raise HTTPForbidden(
                    'No permission to DELETE {} from relationship {}.'.format(
                        item, view.relname
                    )
                )
        return request


permission_handlers = {
    'get': {
        'alter_document': get_alter_document_handler,
    },
    'collection_get': {
        'alter_document': get_alter_document_handler,
    },
    'related_get': {
        'alter_document': get_alter_document_handler,
    },
    'relationships_get': {
        'alter_document': get_alter_document_handler,
    },
    'collection_post': {
        'alter_request': collection_post_alter_request_handler,
    },
    'relationships_post': {
        'alter_request': relationships_post_alter_request_handler,
    },
    'patch': {
        'alter_request': patch_alter_request_handler,
    },
    'relationships_patch': {
        'alter_request': relationships_patch_alter_request_handler,
    },
    'delete': {
        'alter_request': delete_alter_request_handler,
    },
    'relationships_delete': {
        'alter_request': relationships_delete_alter_request_handler,
    }
}


def permission_handler(endpoint_name, stage_name):
    return permission_handlers[endpoint_name][stage_name]


@functools.lru_cache()
def get_jsonapi_accepts(request):
    """Return a set of all 'application/vnd.api' parts of the accept
    header.
    """
    accepts = re.split(
        r',\s*',
        request.headers.get('accept', '')
    )
    return {
        a for a in accepts
        if a.startswith('application/vnd.api')
    }


def validate_request_headers(view, request, data):
    """Check that request headers comply with spec.

    Raises:
        HTTPUnsupportedMediaType
        HTTPNotAcceptable
    """
    # Spec says to reject (with 415) any request with media type
    # params.
    if len(request.headers.get('content-type', '').split(';')) > 1:
        raise HTTPUnsupportedMediaType(
            'Media Type parameters not allowed by JSONAPI ' +
            'spec (http://jsonapi.org/format).'
        )
    # Spec says throw 406 Not Acceptable if Accept header has no
    # application/vnd.api+json entry without parameters.
    jsonapi_accepts = get_jsonapi_accepts(request)
    if jsonapi_accepts and\
            'application/vnd.api+json' not in jsonapi_accepts:
        raise HTTPNotAcceptable(
            'application/vnd.api+json must appear with no ' +
            'parameters in Accepts header ' +
            '(http://jsonapi.org/format).'
        )

    return request


def validate_request_valid_json(view, request, data):
    """Check that the body of any request is valid JSON.

    Raises:
        HTTPBadRequest
    """
    if request.content_length:
        try:
            request.json_body
        except ValueError:
            raise HTTPBadRequest("Body is not valid JSON.")

    return request


def validate_request_common_validity(view, request, data):
    """Perform common request validity checks."""

    if request.content_length and view.api.settings.schema_validation:
        # Validate request JSON against the JSONAPI jsonschema
        view.api.metadata.JSONSchema.validate(request.json_body, request.method)

    # Spec says throw BadRequest if any include paths reference non
    # existent attributes or relationships.
    if view.bad_include_paths:
        raise HTTPBadRequest(
            "Bad include paths {}".format(
                view.bad_include_paths
            )
        )

    # Spec says set Content-Type to application/vnd.api+json.
    request.response.content_type = 'application/vnd.api+json'

    return request


def validate_request_object_exists(view, request, data):
    """Make sure that id exists in collection for all urls specifying an id."""
    if view.obj_id is not None:
        if not view.object_exists(view.obj_id):
            raise HTTPNotFound('No item {} in {}'.format(view.obj_id, view.collection_name))
    return request


def alter_document_self_link(view, doc, data):
    """Include a self link unless the method is PATCH."""
    if view.request.method != 'PATCH':
        doc.update_child('links', {'self': view.request.url})
    return doc


def alter_document_debug_info(view, doc, data):
    """Potentially add some debug information."""
    debug = {
        'accept_header': {
            a: None for a in get_jsonapi_accepts(view.request)
        },
        'qinfo_page':
            view.collection_query_info(view.request)['_page'],
        'atts': {k: None for k in view.attributes.keys()},
        'includes': {
            k: None for k in view.requested_include_names()
        }
    }
    doc.update_child('meta', {'debug': debug})
    return doc


def alter_document_add_returned_count(view, doc, data):
    """Add the returned count to meta."""
    # Don't add a returned count unless we're returning an array of objects.
    if not isinstance(doc['data'], abc.Sequence):
        return doc
    try:
        meta = doc['meta']
    except KeyError:
        meta = doc['meta'] = {}
    try:
        results = meta['results']
    except KeyError:
        results = meta['results'] = {}
    results['returned'] = len(doc['data'])
    return doc


def alter_document_add_denied(view, doc, data):
    try:
        meta = doc['meta']
    except KeyError:
        meta = doc['meta'] = {}
    try:
        results = meta['results']
    except KeyError:
        results = meta['results'] = {}
    rejected_dict = view.pj_shared.rejected.rejected_dict
    results['denied'] = len(rejected_dict['objects'])
    meta['rejected'] = rejected_dict

    # delete(results['available'])
    return doc


def alter_request_add_info(view, request, data):
    """Add information commonly used in view operations."""

    # Extract id and relationship from route, if provided
    view.obj_id = view.request.matchdict.get('id', None)
    view.not_found_message = f'No item {view.obj_id} in {view.collection_name}'
    view.relname = view.request.matchdict.get('relationship', None)
    if view.relname:
        # Gather relationship info
        mapper = sqlalchemy.inspect(view.model).mapper
        try:
            view.rel = view.relationships[view.relname]
        except KeyError:
            raise HTTPNotFound('No relationship {} in collection {}'.format(
                view.relname,
                view.collection_name
            ))
        view.rel_class = view.rel.tgt_class
        view.rel_view = view.view_instance(view.rel_class)
    return request


class ResultObject:
    def __init__(self, view, object, related=None):
        self.view = view
        self.object = object
        self.related = related or {}
        if object is None:
            self.obj_id = None
        else:
            self.obj_id = self.view.id_col(self.object)
        self.url = self.view.request.route_url(
            self.view.api.endpoint_data.make_route_name(
                self.view.collection_name, suffix='item'
            ),
            **{'id': self.obj_id}
        )
        self.attribute_mask = set(self.view.requested_attributes)
        self.rel_mask = set(self.view.requested_relationships)

        self._included_dict = None

    def serialise(self):
        # An object of 'None' is a special case.
        if self.object is None:
            return None
        atts = {
            key: getattr(self.object, key)
            for key in self.attribute_mask
            if self.view.mapped_info_from_name(key).get('visible', True)
        }
        rels = {
            rel_name: res.rel_dict(
                rel=self.view.relationships[rel_name],
                rel_name=rel_name,
                parent_url=self.url
            )
            for rel_name, res in self.related.items()
            if rel_name in self.rel_mask
        }
        return {
            'type': self.view.collection_name,
            'id': str(self.obj_id),
            'attributes': atts,
            'links': {'self': self.url},
            'relationships': rels,
        }

    def to_dict(self):
        if self.object is None:
            return None
        return {
            'type': self.view.collection_name,
            'id': str(self.obj_id),
            'attributes': {
                key: getattr(self.object, key) for key in self.view.all_attributes
            }
        }

    def identifier(self):
        # An object of 'None' is a special case.
        if self.object is None:
            return None
        return {
            'type': self.view.collection_name,
            'id': str(self.obj_id)
        }

    @property
    def tuple_identifier(self):
        if self.object is None:
            return None
        return (
            self.view.collection_name,
            str(self.obj_id)
        )

    @property
    def str_identifier(self):
        if self.object is None:
            return None
        return f'{self.view.collection_name}-::-{self.obj_id}'

    @property
    def included_dict(self):
        incd = {}
        for rel_name, res in self.related.items():
            if not res.is_included:
                continue
            incd.update(res.included_dict)
        return incd


class Results:
    def __init__(self, view, objects=None, many=True, count=None, limit=None, is_included=False, is_top=False, not_found_message='Object not found.'):
        self.view = view
        self.objects = objects or []
        self.rejected_objects = []
        self.many = many
        self.count = count
        self.limit = limit
        self.is_included = is_included
        self.is_top = is_top
        self.not_found_message = not_found_message

        self._meta = None
        self._included_dict = None
        self._flag_filtered = False

    def serialise(self, identifiers=False):
        doc = Doc()
        if self.many:
            # doc.collection = True
            doc['links'] = self.view.pagination_links(count=self.count)
        if identifiers:
            doc['data'] = self.identifiers()
        else:
            doc['data'] = self.data()
            doc['included'] = self.included()
        doc['meta'] = self.meta

        return doc

    def serialise_object_with(self, method_name):
        data = [getattr(o, method_name)() for o in self.objects]
        if self.many:
            return data
        else:
            try:
                return data[0]
            except IndexError:
                return None

    @property
    def meta(self):
        if self._meta is None:
            self._meta = self.compute_meta()
        return self._meta

    def compute_meta(self):
        meta = {}
        if self.many:
            meta.update(
                {
                    'results': {
                        'available': self.count,
                        'limit': self.limit,
                        # 'returned': len(self.objects)
                    }
                }
            )
        return meta

    def data(self):
        return self.serialise_object_with('serialise')

    def identifiers(self):
        return self.serialise_object_with('identifier')

    def rel_dict(self, rel, rel_name, parent_url):
        rd = {
            'data': self.identifiers(),
            'links': {
                'self': '{}/relationships/{}'.format(parent_url, rel_name),
                'related': '{}/{}'.format(parent_url, rel_name)
            },
            'meta': {
                'direction': rel.direction.name,
            }
        }
        if self.many:
            rd['meta']['results'] = {}
            rd['meta']['results']['available'] = self.count
            rd['meta']['results']['limit'] = self.limit
            rd['meta']['results']['returned'] = len(rd['data'])
        return rd

    def included(self):
        return [o.serialise() for o in self.included_dict.values()]

    @property
    def included_dict(self):
        included_dict = {}
        for o in self.objects:
            if not self.is_top:
                included_dict[(self.view.collection_name, o.obj_id)] = o
            included_dict.update(o.included_dict)
        return included_dict

    def filter(self, predicate, reason='Permission denied', force_rerun=False):
        # if self._flag_filtered and not force_rerun:
        #     return
        accepted = []
        for obj in self.objects:
            pred = self.view.permission_to_dict(predicate(obj))
            if pred['id']:
                accepted.append(obj)
                reject_atts = obj.attribute_mask - pred['attributes']
                obj.attribute_mask &= pred['attributes']
                # record rejected atts
                self.view.pj_shared.rejected.reject_attributes(
                    obj.tuple_identifier,
                    reject_atts,
                    reason,
                )
                reject_rels = obj.rel_mask - pred['relationships']
                obj.rel_mask &= pred['relationships']
                # record rejected rels
                self.view.pj_shared.rejected.reject_relationships(
                    obj.tuple_identifier,
                    reject_rels,
                    reason,
                )
            else:
                self.rejected_objects.append(obj)
                self.view.pj_shared.rejected.reject_object(obj.tuple_identifier, reason)

        self.objects = accepted
        self._flag_filtered = True


class Doc(dict):

    def update_child(self, key, value):
        try:
            self[key].update(value)
        except KeyError:
            self[key] = value


class SharedState():

    def __init__(self, view, request=None, results=None, document=None, rejected=None):
        self.view = view
        self.request = request
        self.results = results
        self.document = document
        self.rejected = rejected or Rejected(view)


class Rejected():

    def __init__(self, view, rejected=None):
        self.view = view
        self.rejected = rejected or {
            'objects': {},
            'attributes': {},
            'relationships': {},
        }

    def reject_object(self, identifier, reason):
        self.rejected['objects'][identifier] = reason

    def _reject_multiple(self, identifier, things, reason, category):
        if not things:
            return
        new = {t: reason for t in things}
        try:
            self.rejected[category][identifier].update(new)
        except KeyError:
            self.rejected[category][identifier] = new

    reject_attributes = partialmethod(_reject_multiple, category='attributes')
    reject_relationships = partialmethod(_reject_multiple, category='relationships')

    def identifier_to_str(self, identifier):
        return f'{identifier[0]}::{identifier[1]}'

    @property
    def rejected_dict(self):
        ret = {}
        for part in ['objects', 'attributes', 'relationships']:
            ret[part] = {
                self.identifier_to_str(k): v for k, v in self.rejected[part].items()
            }
        return ret
