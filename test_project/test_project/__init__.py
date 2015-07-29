from pyramid.config import Configurator
from sqlalchemy import engine_from_config

import jsonapi
from . import models

#from .models import (
#    DBSession,
#    Base,
#    )


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    engine = engine_from_config(settings, 'sqlalchemy.')
    jsonapi.DBSession.configure(bind=engine)
    models.Base.metadata.bind = engine
    config = Configurator(settings=settings)
    config.include('cornice')
    renderer = jsonapi.JSONAPIFromSqlAlchemyRenderer()
    config.add_renderer('jsonapi', renderer)
    jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.scan(package=jsonapi)
    return config.make_wsgi_app()
