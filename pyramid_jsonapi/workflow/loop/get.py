from pyramid.httpexceptions import (
    HTTPForbidden,
    HTTPNotFound,
)
import pyramid_jsonapi.workflow as wf
from . import stages


def get_doc(view, stages, query):
    query = wf.execute_stage(
        view, stages, 'alter_query', query
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
    # Stage 'alter_result' will run on each related object.
    wf.loop.fill_result_object_related(res_obj, stages)

    return results.serialise()


def workflow(view, stages):
    return get_doc(view, stages, view.single_item_query())
