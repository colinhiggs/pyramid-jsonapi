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
from .related_get import (
    get_results,
)


def workflow(view, stages):
    if view.rel.direction is MANYTOONE:
        raise HTTPForbidden('Cannot POST to TOONE relationship link.')

    # Alter data with any callbacks
    data = view.request.json_body['data']

    obj = view.dbsession.query(view.model).get(view.obj_id)
    items = []
    for resid in data:
        if resid['type'] != view.rel_view.collection_name:
            raise HTTPConflict(
                "Resource identifier type '{}' does not match relationship type '{}'.".format(
                    resid['type'], view.rel_view.collection_name
                )
            )
        try:
            newitem = view.dbsession.query(view.rel_class).get(resid['id'])
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        if newitem is None:
            raise HTTPFailedDependency("One or more objects POSTed to this relationship do not exist.")
        items.append(newitem)
    getattr(obj, view.relname).extend(items)
    obj = wf.execute_stage(
        view, stages, 'before_write_item', obj
    )
    try:
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        if 'duplicate key value violates unique constraint' in str(exc):
            # This happens when using an association proxy if we attempt to
            # add an object to the relationship that's already there. We
            # want this to be a no-op.
            pass
        else:
            raise HTTPFailedDependency(str(exc))
    except sqlalchemy.orm.exc.FlushError as exc:
        if str(exc).startswith("Can't flush None value"):
            raise HTTPFailedDependency("One or more objects POSTed to this relationship do not exist.")
        else:
            # Catch-all. Shouldn't reach here.
            raise  # pragma: no cover

    # Everything should be done now - return the relationship as
    # relationships_get would.
    return get_results(view, stages).serialise(identifiers=True)
