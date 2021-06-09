import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPBadRequest,
    HTTPInternalServerError,
)

stages = (
    'alter_query',
    'alter_result',
    'alter_direct_results',
    'alter_related_query',
    'alter_related_result',
    'alter_related_results',
    'alter_results',
)


def workflow(view, stages):
    query = view.base_collection_query()
    query = view.query_add_sorting(query)
    query = view.query_add_filtering(query)
    # try:
    #     count = query.count()
    # except sqlalchemy.exc.ProgrammingError:
    #     raise HTTPInternalServerError(
    #         'An error occurred querying the database. Server logs may have details.'
    #     )
    qinfo = view.collection_query_info(view.request)
    query = query.offset(qinfo['page[offset]'])
    limit = qinfo['page[limit]']
    # query = query.limit(limit)
    query = wf.execute_stage(
        view, stages, 'alter_query', query
    )

    # Get the direct results from this collection (no related objects yet).
    # Stage 'alter_result' will run on each object.
    results = wf.Results(
        view,
        objects=list(wf.loop.get_altered_objects(
            view, stages, 'alter_result', query, limit
        )),
        many=True,
        is_top=True,
        # count=count,
        limit=limit
    )

    # Fill the relationships with related objects.
    # Stage 'alter_related_result' will run on each object.
    for res_obj in results.objects:
        for rel_name in view.relationships:
            if wf.follow_rel(view, rel_name):
                res_obj.related[rel_name] = wf.loop.get_related(
                    res_obj, rel_name, stages
                )

    # A chance to alter the complete set of results before they are serialised.
    results = wf.execute_stage(view, stages, 'alter_results', results)

    return results.serialise()
