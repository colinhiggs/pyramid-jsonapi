from .. import pjview
# from pyramid_jsonapi.results import Results

stages = (
    'request',
    'object_query',
    'objects',
    'document',
    'data'
)


def stage_initial_query(view):
    return view.single_item_query()


def stage_execute_query(view, query):
    return {}
#    return Results(is_collection=False, data=view.single_result(query))


def data_init(view, data):
    return ['first']


def add_data(view, data):
    data.append(view.obj_id)
    return data


stage_data = (add_data)
