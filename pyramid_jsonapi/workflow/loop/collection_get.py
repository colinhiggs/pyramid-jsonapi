import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPInternalServerError,
)

stages = (
    'alter_query',
    'alter_direct_results',
    'alter_related_query',
    'alter_related_results',
    'alter_results',
)


def workflow(view, stages):
    query = view.base_collection_query()
    query = view.query_add_sorting(query)
    query = view.query_add_filtering(query)
    try:
        count = query.count()
    except sqlalchemy.exc.ProgrammingError:
        raise HTTPInternalServerError(
            'An error occurred querying the database. Server logs may have details.'
        )
    qinfo = view.collection_query_info(view.request)
    query = query.offset(qinfo['page[offset]'])
    limit = qinfo['page[limit]']
    query = query.limit(limit)
    query = wf.execute_stage(
        view, stages, 'alter_query', query
    )
    try:
        res_objs = [wf.ResultObject(view, o) for o in query.all()]
    except sqlalchemy.exc.DataError as exc:
        raise HTTPBadRequest(str(exc.orig))
    results = wf.Results(
        view,
        objects=res_objs,
        many=True,
        is_top=True,
        count=count,
        limit=limit
    )
    results = wf.execute_stage(view, stages, 'alter_direct_results', results)
    for res in results.objects:
        wf.loop.fill_related(stages, res)
    results = wf.execute_stage(view, stages, 'alter_results', results)
    return results.serialise()
