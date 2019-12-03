import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.workflow as wf

from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)

stages = (
    'alter_query',
    'alter_object',
    'alter_related_query',
    'alter_related_objects',
)

# def stage_alter_query(view, query, data):
#     return view.single_item_by_id_query()
#
# def stage_get_object(view, object, data):
#     return view.load_objects(data['alter_query'])[0]

def workflow(view, stages, data):
    query = wf.execute_stage(
        view, stages, 'alter_query', view.single_item_query()
    )
    obj = view.get_one(
        query,
        'No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    obj = wf.execute_stage(view, stages, 'alter_object', obj)
    res_obj = wf.ResultObject(view, obj)
    fill_related(res_obj)
    results = wf.Results(
        view,
        objects=[res_obj],
        many=False,
        is_top=True
    )
    fill_related(res_obj)
    doc = pyramid_jsonapi.jsonapi.Document()
    doc.data = results.data()
    doc.included = results.included()
    return doc

def fill_related(obj, include_path=None):
    view = obj.view
    if include_path is None:
        include_path = []
    for rel_name, rel in view.relationships.items():
        rel_include_path = include_path + [rel_name]
        is_included = False
        if rel_name not in view.requested_relationships:
            continue
        if not view.mapped_info_from_name(rel_name).get('visible', True):
            continue
        if '.'.join(rel_include_path) in view.requested_include_names():
            is_included = True

        rel_view = view.view_instance(rel.tgt_class)
        query = view.related_query(obj.obj_id, rel, full_object=is_included)
        many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
        if many:
            limit = view.related_limit(rel)
            query = query.limit(limit)

        rel_results = [wf.ResultObject(rel_view, o) for o in query.all()]
        if is_included:
            for rel_obj in rel_results:
                fill_related(rel_obj, include_path=rel_include_path)
        obj.related[rel_name] = wf.Results(
            rel_view,
            objects=rel_results,
            many=many,
            count=query.count(),
            is_included=is_included
        )
