import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.pjview as pjview

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
    query = pjview.execute_stage(
        view, stages, 'alter_query', view.single_item_query()
    )
    obj = view.get_one(
        query,
        'No item {} in {}'.format(view.obj_id, view.collection_name)
    )
    obj = pjview.execute_stage(view, stages, 'alter_object', obj)
    res_obj = pjview.ResultObject(view, obj)
    fill_related(res_obj)
    results = pjview.Results(
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
    obj_id = view.id_col(obj.object)
    if include_path is None:
        include_path = []
    for rel_name, rel in view.relationships.items():
        is_included = False
        if '.'.join(include_path + [rel_name]) in view.requested_include_names():
            is_included = True
        if rel_name not in view.requested_relationships and not is_included:
            continue
        if not view.mapped_info_from_name(rel_name).get('visible', True):
            continue

        print('{} included: {}'.format(rel_name, is_included))

        rel_view = view.view_instance(rel.tgt_class)
        query = view.related_query(obj_id, rel, full_object=is_included)
        many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
        if many:
            limit = view.related_limit(rel)
            query = query.limit(limit)

        obj.related[rel_name] = pjview.Results(
            rel_view,
            objects=[pjview.ResultObject(rel_view, o) for o in query.all()],
            many=many,
            count=query.count(),
            is_included=is_included
        )
