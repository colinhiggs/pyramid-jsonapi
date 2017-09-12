from pyramid.config import Configurator
from sqlalchemy import engine_from_config
from pyramid.renderers import JSON
from . import views

# The jsonapi module.
import pyramid_jsonapi

# Import models as a module: needed for create_jsonapi...
from . import models
from . import models2

from pyramid.httpexceptions import (
    HTTPForbidden
)

test_settings = {
    'models_iterable': {
        'module': models,
        'list': [models.Person, models.Blog],
        'composite_key': [models2.CompositeKey]
    }
}

# Used to test that adding JSON adapters works.
import datetime
def datetime_adapter(obj, request):
    return obj.isoformat()


def person_callback_add_information(view, ret):
    param = view.request.params.get(
        'fields[{}]'.format(view.collection_name)
    )
    if param is None:
        requested_fields = {'name_copy', 'age'}
    else:
        requested_fields = view.requested_field_names
    if 'name_copy' in requested_fields:
        ret.attributes['name_copy'] = ret.attributes['name']
    if 'age' in requested_fields:
        ret.attributes['age'] = 42
    return ret


def person_allowed_fields(self):
    if self.request.method == 'GET':
        return set(self.fields) | {'name_copy'}
    else:
        return set(self.fields)


def person_allowed_object(self, obj):
    if self.request.method == 'GET':
        try:
            name = obj.attributes['name']
        except KeyError:
            return True
        if name == 'secret_squirrel':
            return False
        else:
            return True
    else:
        return True


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    # The usual stuff from the pyramid alchemy scaffold.
    engine = engine_from_config(settings, 'sqlalchemy.')
    models.DBSession.configure(bind=engine)
    models.Base.metadata.bind = engine
    config = Configurator(settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('echo', '/echo/{type}')
    config.scan(views)

    # Set up the renderer.
    renderer = JSON()
    renderer.add_adapter(datetime.date, datetime_adapter)
    config.add_renderer('json', renderer)

    # Lines specific to pyramid_jsonapi.
    # Create an API instance.
    pj = pyramid_jsonapi.PyramidJSONAPI(
        config,
        test_settings['models_iterable'][
            settings.get('pyramid_jsonapi.tests.models_iterable', 'module')
        ],
        lambda view: models.DBSession
    )
    # Register a bad filter operator for test purposes.
    pj.filter_registry.register('bad_op')
    # Create the routes and views automagically.
    pj.create_jsonapi_using_magic_and_pixie_dust()

    person_view = pj.view_classes[
        models.Person
    ]
    person_view.callbacks['after_serialise_object'].appendleft(
        person_callback_add_information
    )
    person_view.allowed_fields = property(person_allowed_fields)
    person_view.allowed_object = person_allowed_object
    pj.append_callback_set_to_all_views(
        'access_control_serialised_objects'
    )

    # Back to the usual pyramid stuff.
    return config.make_wsgi_app()
