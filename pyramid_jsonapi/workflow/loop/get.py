import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.workflow as wf

stages = (
    'alter_query',
    'alter_result',
    'alter_related_query',
    'alter_related_results',
)

def workflow(view, stages, data):
    query = wf.execute_stage(
        view, stages, 'alter_query', view.single_item_query()
    )
    obj = view.get_one(
        query,
        'No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    res_obj = wf.ResultObject(view, obj)
    obj = wf.execute_stage(view, stages, 'alter_result', res_obj)
    wf.loop.fill_related(stages, res_obj)
    results = wf.Results(
        view,
        objects=[res_obj],
        many=False,
        is_top=True,
    )
    return results.serialise()
