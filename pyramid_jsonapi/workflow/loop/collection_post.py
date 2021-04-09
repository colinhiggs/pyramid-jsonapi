import pyramid_jsonapi.workflow as wf
import sqlalchemy

from collections.abc import Sequence

from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)

from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPForbidden,
    HTTPConflict,
    HTTPNotFound,
)

stages = (
    'alter_direct_results',
    'alter_related_query',
    'alter_related_results',
    'alter_results',
)


def workflow(view, stages):
    try:
        data = view.request.json_body['data']
    except KeyError:
        raise HTTPBadRequest('data attribute required in POSTs.')

    if not isinstance(data, dict):
        raise HTTPBadRequest('data attribute must contain a single resource object.')

    # Check to see if we're allowing client ids
    if not view.api.settings.allow_client_ids and 'id' in data:
        raise HTTPForbidden('Client generated ids are not supported.')
    # Type should be correct or raise 409 Conflict
    datatype = data.get('type')
    if datatype != view.collection_name:
        raise HTTPConflict("Unsupported type '{}'".format(datatype))
    try:
        atts = data['attributes']
    except KeyError:
        atts = {}
    if 'id' in data:
        atts[view.model.__pyramid_jsonapi__['id_col_name']] = data['id']
    item = view.model(**atts)
    with view.dbsession.no_autoflush:
        for relname, reldict in data.get('relationships', {}).items():
            try:
                reldata = reldict['data']
            except KeyError:
                raise HTTPBadRequest(
                    'relationships within POST must have data member'
                )
            try:
                rel = view.relationships[relname]
            except KeyError:
                raise HTTPNotFound(
                    'No relationship {} in collection {}'.format(
                        relname,
                        view.collection_name
                    )
                )
            rel_type = view.api.view_classes[rel.tgt_class].collection_name
            if rel.direction is ONETOMANY or rel.direction is MANYTOMANY:
                # reldata should be a list/array
                if not isinstance(reldata, Sequence) or isinstance(reldata, str):
                    raise HTTPBadRequest(
                        'Relationship data should be an array for TOMANY relationships.'
                    )
                rel_items = []
                for rel_identifier in reldata:
                    if rel_identifier.get('type') != rel_type:
                        raise HTTPConflict(
                            'Relationship identifier has type {} and should be {}'.format(
                                rel_identifier.get('type'), rel_type
                            )
                        )
                    try:
                        rel_items.append(view.dbsession.query(rel.tgt_class).get(rel_identifier['id']))
                    except KeyError:
                        raise HTTPBadRequest(
                            'Relationship identifier must have an id member'
                        )
                setattr(item, relname, rel_items)
            else:
                if (not isinstance(reldata, dict)) and (reldata is not None):
                    raise HTTPBadRequest(
                        'Relationship data should be a resource identifier object or null.'
                    )
                if reldata.get('type') != rel_type:
                    raise HTTPConflict(
                        'Relationship identifier has type {} and should be {}'.format(
                            reldata.get('type'), rel_type
                        )
                    )
                try:
                    setattr(
                        item,
                        relname,
                        view.dbsession.query(rel.tgt_class).get(reldata['id'])
                    )
                except KeyError:
                    raise HTTPBadRequest(
                        'No id member in relationship data.'
                    )
    try:
        view.dbsession.add(item)
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPConflict(exc.args[0])
    view.request.response.status_code = 201
    view.request.response.headers['Location'] = view.request.route_url(
        view.api.endpoint_data.make_route_name(view.collection_name, suffix='item'),
        **{'id': view.id_col(item)}
    )

    results = wf.Results(
        view,
        objects=[wf.ResultObject(view, item)],
        many=False,
        is_top=True,
        not_found_message='No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    doc = wf.Doc()
    ro = wf.ResultObject(view, item)
    wf.loop.fill_related(stages, ro)
    doc['data'] = ro.serialise()
    return doc
