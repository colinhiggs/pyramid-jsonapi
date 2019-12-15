import pyramid_jsonapi.jsonapi
import pyramid_jsonapi.workflow as wf

stages = (
    'before_delete',
)

def workflow(view, stages, prev_data):
    item = view.single_item_query(loadonly=[view.key_column.name]).one()
    item = wf.execute_stage(
        view, stages, 'before_delete', item
    )
    try:
        view.dbsession.delete(item)
        view.dbsession.flush()
    except sqlalchemy.exc.IntegrityError as exc:
        raise HTTPFailedDependency(str(exc))
    doc = pyramid_jsonapi.jsonapi.Document()
    doc.update({
        'data': view.serialise_resource_identifier(
            view.obj_id
        )})
    return doc
