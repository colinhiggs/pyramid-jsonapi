import sqlalchemy

from pyramid.httpexceptions import (
    HTTPInternalServerError,
    HTTPBadRequest,
)
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE,
)

import pyramid_jsonapi.workflow as wf

stages = (
    'alter_query',
    'alter_results',
    'alter_related_query',
    'alter_related_results',
)


def workflow(view, stages, data):
    query = wf.execute_stage(
        view, stages, 'alter_query',
        view.related_query(view.obj_id, view.rel)
    )
    count = 0
    limit = 1

    if view.rel.direction is ONETOMANY or view.rel.direction is MANYTOMANY:
        many = True
        query = view.rel_view.query_add_sorting(query)
        query = view.rel_view.query_add_filtering(query)
        qinfo = view.rel_view.collection_query_info(view.request)
        try:
            count = query.count()
        except sqlalchemy.exc.ProgrammingError:
            raise HTTPInternalServerError(
                'An error occurred querying the database. Server logs may have details.'
            )
        query = query.offset(qinfo['page[offset]'])
        limit = qinfo['page[limit]']
        query = query.limit(qinfo['page[limit]'])

        try:
            res_objs = [wf.ResultObject(view.rel_view, o) for o in query.all()]
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest(str(exc.orig))
    else:
        many = False
        res_objs = [wf.ResultObject(view.rel_view, view.rel_view.get_one(query))]
        count = len(res_objs)

    results = wf.Results(
        view,
        objects=res_objs,
        many=many,
        is_top=True,
        count=count,
        limit=limit
    )
    results = wf.execute_stage(view, stages, 'alter_results', results)
    for res in results.objects:
        wf.loop.fill_related(stages, res)
    return results.serialise()
