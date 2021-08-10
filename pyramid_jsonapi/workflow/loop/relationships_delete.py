import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPInternalServerError,
    HTTPBadRequest,
    HTTPForbidden,
    HTTPConflict,
    HTTPFailedDependency,
)
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE,
)
from . import stages


def workflow(view, stages):
    if view.rel.direction is MANYTOONE:
        raise HTTPForbidden('Cannot DELETE to TOONE relationship link.')
    obj = view.dbsession.query(view.model).get(view.obj_id)

    for resid in view.request.json_body['data']:
        if resid['type'] != view.rel_view.collection_name:
            raise HTTPConflict(
                "Resource identifier type '{}' does not match relationship type '{}'.".format(
                    resid['type'], view.rel_view.collection_name
                )
            )
        try:
            item = view.dbsession.query(view.rel_class).get(resid['id'])
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        if item is None:
            raise HTTPFailedDependency("One or more objects DELETEd from this relationship do not exist.")
        try:
            getattr(obj, view.relname).remove(item)
        except ValueError as exc:
            if exc.args[0].endswith('not in list'):
                # The item we were asked to remove is not there.
                pass
            else:
                raise
    obj = wf.execute_stage(
        view, stages, 'before_write_item', obj
    )
    try:
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPFailedDependency(str(exc))
    return wf.Doc()
