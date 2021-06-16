from pyramid.httpexceptions import (
    HTTPForbidden,
    HTTPNotFound,
)
import pyramid_jsonapi.workflow as wf

stages = (
    'alter_query',
    'alter_result',
    'alter_related_query',
    'alter_related_result',
    'alter_results',
)


def workflow(view, stages):
    query = wf.execute_stage(
        view, stages, 'alter_query', view.single_item_query()
    )
    res_obj = wf.loop.get_one_altered_result_object(view, stages, query)
    results = view.pj_shared.results = wf.Results(
        view,
        objects=[res_obj],
        many=False,
        is_top=True,
        not_found_message=view.not_found_message,
    )

    # We have a result but we still need to fill the relationships.
    # Stage 'alter_related_result' will run on each related object.
    wf.loop.fill_result_object_related(res_obj, stages)

    results = wf.execute_stage(view, stages, 'alter_results', results)
    return results.serialise()
