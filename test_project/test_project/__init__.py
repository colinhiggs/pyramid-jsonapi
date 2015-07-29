from pyramid.config import Configurator
from sqlalchemy import engine_from_config

# The jsonapi module.
import jsonapi
# Import models as a module: needed for create_jsonapi...
from . import models

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

    # jsonapi requires cornice.
    config.include('cornice')

    # Lines specific to jsonapi.
    # Set up the renderer.
    renderer = jsonapi.JSONAPIFromSqlAlchemyRenderer()
    config.add_renderer('jsonapi', renderer)
    # Create the routes and views automagically.
    jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)
    # Make sure we scan the *jsonapi* package.
    config.scan(package=jsonapi)

    # Back to the usual pyramid stuff.
    return config.make_wsgi_app()
