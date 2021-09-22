import itertools
import pyramid_jsonapi.workflow as wf
import sqlalchemy

from json.decoder import (
    JSONDecodeError,
)
from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPConflict,
    HTTPNotFound,
)
from sqlalchemy.orm import (
    load_only,
)
from . import stages
from .item_get import (
    get_doc,
)


def workflow(view, stages):
    validate_patch_request(view)
    data = view.request.json_body['data']
    atts = {}
    hybrid_atts = {}
    for key, value in data.get('attributes', {}).items():
        if key in view.attributes:
            atts[key] = value
        elif key in view.hybrid_attributes:
            hybrid_atts[key] = value
        else:
            raise HTTPNotFound(
                'Collection {} has no attribute {}'.format(
                    view.collection_name, key
                )
            )
    atts[view.key_column.name] = view.obj_id
    item = view.dbsession.merge(view.model(**atts))
    for att, value in hybrid_atts.items():
        try:
            setattr(item, att, value)
        except AttributeError:
            raise HTTPConflict(
                'Attribute {} is read only.'.format(
                    att
                )
            )

    rels = data.get('relationships', {})
    for relname, reldict in rels.items():
        try:
            rel = view.relationships[relname]
        except KeyError:
            raise HTTPNotFound(
                'Collection {} has no relationship {}'.format(
                    view.collection_name, relname
                )
            )
        rel_view = view.view_instance(rel.tgt_class)
        try:
            reldata = reldict['data']
        except KeyError:
            raise HTTPBadRequest(
                "Relationship '{}' has no 'data' member.".format(relname)
            )
        except TypeError:
            raise HTTPBadRequest(
                "Relationship '{}' is not a dictionary with a data member.".format(relname)
            )
        if reldata is None:
            setattr(item, relname, None)
        elif isinstance(reldata, dict):
            if reldata.get('type') != rel_view.collection_name:
                raise HTTPConflict(
                    'Type {} does not match relationship type {}'.format(
                        reldata.get('type', None), rel_view.collection_name
                    )
                )
            if reldata.get('id') is None:
                raise HTTPBadRequest(
                    'An id is required in a resource identifier.'
                )
            rel_item = view.dbsession.query(
                rel.tgt_class
            ).options(
                load_only(rel_view.key_column.name)
            ).get(reldata['id'])
            if not rel_item:
                raise HTTPNotFound('{}/{} not found'.format(
                    rel_view.collection_name, reldata['id']
                ))
            setattr(item, relname, rel_item)
        elif isinstance(reldata, list):
            rel_items = []
            for res_ident in reldata:
                rel_item = view.dbsession.query(
                    rel.tgt_class
                ).options(
                    load_only(rel_view.key_column.name)
                ).get(res_ident['id'])
                if not rel_item:
                    raise HTTPNotFound('{}/{} not found'.format(
                        rel_view.collection_name, res_ident['id']
                    ))
                rel_items.append(rel_item)
            setattr(item, relname, rel_items)
    item = wf.execute_stage(
        view, stages, 'before_write_item', item
    )
    try:
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPConflict(str(exc))
    doc = get_doc(
        view, getattr(view, 'item_get').stages, view.single_item_query(view.obj_id)
    )
    doc['meta'] = {
        'updated': {
            'attributes': [
                att for att in itertools.chain(atts, hybrid_atts)
                if att != view.key_column.name
            ],
            'relationships': [r for r in rels]
        }
    }
    # if an update is successful ... the server
    # responds only with top-level meta data
    return doc


def validate_patch_request(view):
    request = view.request
    try:
        data = request.json_body['data']
    except KeyError:
        raise HTTPBadRequest('data attribute required in PATCHes.')
    except JSONDecodeError as exc:
        raise HTTPBadRequest('Error decoding JSON body: {}.'.format(exc))
    data_id = data.get('id')
    if view.collection_name != data.get('type'):
        raise HTTPConflict(
            'JSON type ({}) does not match URL type ({}).'.format(
                data.get('type'), view.collection_name
            )
        )
    if data_id != view.obj_id:
        raise HTTPConflict(
            'JSON id ({}) does not match URL id ({}).'.format(
                data_id, view.obj_id
            )
        )
    if not view.object_exists(view.obj_id):
        raise HTTPNotFound(
            'No id {} in collection {}'.format(
                view.obj_id,
                view.collection_name
            )
        )
    return request
