import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPFailedDependency,
)
from . import stages


def workflow(view, stages):
    item = view.get_one(
        view.single_item_query(loadonly=[view.key_column.name]),
        not_found_message='No item {} in collection {}'.format(
            view.obj_id, view.collection_name
        )
    )
    item = wf.execute_stage(
        view, stages, 'before_write_item', item
    )
    try:
        view.dbsession.delete(item)
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPFailedDependency(str(exc))
    doc = wf.Doc()
    doc['data'] = wf.ResultObject(view, item).identifier()
    return doc
