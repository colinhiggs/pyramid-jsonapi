from pyramid.config import Configurator
from sqlalchemy import engine_from_config
from . import views

# The jsonapi module.
import jsonapi

# Import models as a module: needed for create_jsonapi...
from . import models

# This is just a module that defines some initial data and a method to
# auto-populate the DB with it.
from . import test_data


# Used to test that adding JSON adapters works.
import datetime
def datetime_adapter(obj, request):
        return obj.isoformat()

def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    # The usual stuff from the pyramid alchemy scaffold.
    engine = engine_from_config(settings, 'sqlalchemy.')
    jsonapi.DBSession.configure(bind=engine)
    models.Base.metadata.bind = engine
    config = Configurator(settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('echo', '/echo/{type}')
    config.scan(views)

    # jsonapi requires cornice.
    config.include('cornice')

    # Since this is just a test app we'll do a sort of idempotent intialisation
    # each time we start.
    #
    # Create or update tables and schema. Safe if tables already exist.
    models.Base.metadata.create_all(engine)
    # Add test data. Safe if test data already exists.
    test_data.add_to_db()

    # Lines specific to jsonapi.
    # Set up the renderer.
    renderer = jsonapi.JSONAPIFromSqlAlchemyRenderer()
    renderer.add_adapter(datetime.date, datetime_adapter)
    config.add_renderer('jsonapi', renderer)
    config.add_renderer(None, renderer)
    # Create the routes and views automagically.
    jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)
    # Make sure we scan the *jsonapi* package.
    config.scan(package=jsonapi)

    # Back to the usual pyramid stuff.
    return config.make_wsgi_app()
