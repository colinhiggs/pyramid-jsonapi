import pyramid_jsonapi.workflow as wf
import sqlalchemy

from pyramid.httpexceptions import (
    HTTPBadRequest,
)
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE
)


def fill_related(stages, obj, include_path=None):
    view = obj.view
    if include_path is None:
        include_path = []
    for rel_name, rel in view.relationships.items():
        rel_include_path = include_path + [rel_name]
        is_included = False
        if '.'.join(rel_include_path) in view.requested_include_names():
            is_included = True
        if rel_name not in view.requested_relationships and not is_included:
            continue
        if not view.mapped_info_from_name(rel_name).get('visible', True):
            continue

        rel_view = view.view_instance(rel.tgt_class)
        query = view.related_query(obj.obj_id, rel, full_object=is_included)
        many = rel.direction is ONETOMANY or rel.direction is MANYTOMANY
        if many:
            count = query.count()
            limit = view.related_limit(rel)
            query = query.limit(limit)
        query = wf.execute_stage(
            view, stages, 'alter_related_query', query
        )

        try:
            rel_results = [wf.ResultObject(rel_view, o) for o in query.all()]
        except sqlalchemy.exc.DataError as exc:
            raise HTTPBadRequest(str(exc.orig))
        rel_results = wf.execute_stage(
            view, stages, 'alter_related_results', rel_results
        )
        if is_included:
            for rel_obj in rel_results:
                fill_related(stages, rel_obj, include_path=rel_include_path)
        obj.related[rel_name] = wf.Results(
            rel_view,
            objects=rel_results,
            many=many,
            is_included=is_included
        )
        if many:
            obj.related[rel_name].count = count
            obj.related[rel_name].limit = limit
