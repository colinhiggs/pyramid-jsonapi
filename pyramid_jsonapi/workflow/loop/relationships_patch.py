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
    obj = view.dbsession.query(view.model).get(view.obj_id)
    if view.rel.direction is MANYTOONE:
        local_col, _ = view.rel.obj.local_remote_pairs[0]
        resid = view.request.json_body['data']
        if resid is None:
            setattr(obj, view.relname, None)
        else:
            if resid['type'] != view.rel_view.collection_name:
                raise HTTPConflict(
                    "Resource identifier type '{}' does not match relationship type '{}'.".format(
                        resid['type'],
                        view.rel_view.collection_name
                    )
                )
            setattr(
                obj,
                local_col.name,
                resid['id']
            )
            try:
                view.dbsession.flush()
            except sqlalchemy.exc.IntegrityError as exc:
                raise HTTPFailedDependency(
                    'Object {}/{} does not exist.'.format(resid['type'], resid['id'])
                )
            except sqlalchemy.exc.DataError as exc:
                raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        # Everything should be PATCHed now - return the relationship as
        # relationships_get would.
        return get_results(view, stages).serialise(identifiers=True)

    items = []
    for resid in view.request.json_body['data']:
        if resid['type'] != view.rel_view.collection_name:
            raise HTTPConflict(
                "Resource identifier type '{}' does not match relationship type '{}'.".format(
                    resid['type'],
                    view.rel_view.collection_name
                )
            )
        try:
            newitem = view.dbsession.query(view.rel_class).get(resid['id'])
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest("invalid id '{}'".format(resid['id']))
        if newitem is None:
            raise HTTPFailedDependency("One or more objects POSTed to this relationship do not exist.")
        items.append(newitem)
    setattr(obj, view.relname, items)
    obj = wf.execute_stage(
        view, stages, 'before_write_item', obj
    )
    try:
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPFailedDependency(str(exc))
    except sqlalchemy.orm.exc.FlushError as exc:
        if str(exc).startswith("Can't flush None value"):
            raise HTTPFailedDependency("One or more objects PATCHed to this relationship do not exist.")
        else:
            # Catch-all. Shouldn't reach here.
            raise  # pragma: no cover

    # Everything should be PATCHed now - return the relationship as
    # relationships_get would.
    return get_results(view, stages).serialise(identifiers=True)
