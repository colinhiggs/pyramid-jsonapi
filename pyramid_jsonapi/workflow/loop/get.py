from pyramid.httpexceptions import (
    HTTPForbidden,
)
import pyramid_jsonapi.workflow as wf

stages = (
    'alter_query',
    'alter_direct_results',
    'alter_related_query',
    'alter_related_results',
    'alter_results',
)


def workflow(view, stages, data):
    query = wf.execute_stage(
        view, stages, 'alter_query', view.single_item_query()
    )
    obj = view.get_one(
        query,
        'No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    results = wf.Results(
        view,
        objects=[wf.ResultObject(view, obj)],
        many=False,
        is_top=True,
        not_found_message='No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    results = wf.execute_stage(view, stages, 'alter_direct_results', results)
    wf.loop.fill_related(stages, results.objects[0])
    results = wf.execute_stage(view, stages, 'alter_results', results)
    return results.serialise()
