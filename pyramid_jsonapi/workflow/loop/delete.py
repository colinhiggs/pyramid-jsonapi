import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPFailedDependency,
)

stages = (
    'before_delete',
)


def workflow(view, stages, prev_data):
    item = view.get_one(
        view.single_item_query(loadonly=[view.key_column.name]),
        not_found_message='No item {} in collection {}'.format(
            view.obj_id, view.collection_name
        )
    )
    item = wf.execute_stage(
        view, stages, 'before_delete', item
    )
    try:
        view.dbsession.delete(item)
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPFailedDependency(str(exc))
    doc = pyramid_jsonapi.jsonapi.Document()
    doc.update({
        'data': view.serialise_resource_identifier(
            view.obj_id
        )})
    return doc
