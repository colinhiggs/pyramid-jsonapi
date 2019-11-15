import argparse
import importlib
from collections import namedtuple
import sqlalchemy.exc
import sys
from mixer.backend.sqlalchemy import Mixer
from pyramid.paster import (
    get_appsettings,
    setup_logging,
)
from pyramid.settings import aslist
from sqlalchemy import engine_from_config
from sqlalchemy.ext.declarative.api import DeclarativeMeta
from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
)

def ismodel(model):
    if isinstance(model, DeclarativeMeta):
        try:
            sqlalchemy.inspect(model).primary_key
        except sqlalchemy.exc.NoInspectionAvailable:
            # Trying to inspect the declarative_base() raises this
            # exception.
            return False
        return True
    else:
        return False

def get_models(model_paths):
    models = {}
    modules = {}
    for model_path in model_paths:
        tmp_models = {}
        path_list = model_path.split('.')
        if path_list[0].startswith('!'):
            path_list[0] = path_list[0][1:]
            remove = True
        else:
            remove = False
        module_name = '.'.join(path_list[:-1])
        module = importlib.import_module(module_name)
        if path_list[-1] == '*':
            tmp_models = {
                '{}.{}'.format(module_name, name): model for name, model in module.__dict__.items()
                if ismodel(model)
            }
        else:
            tmp_models['.'.join(path_list)] = getattr(module, path_list[-1])
        if remove:
            for key in tmp_models:
                try:
                    del(models[key])
                except KeyError:
                    pass
        else:
            models.update(tmp_models)
    return models


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--nrecords', type=int, default=1000,
        help='Number of records of each type to create in the database.'
    ),
    parser.add_argument(
        'config_uri',
        help='uri to config file (for example development.ini)'
    )
    args = parser.parse_args()
    setup_logging(args.config_uri)
    settings = get_appsettings(args.config_uri)
    engine = engine_from_config(settings, 'sqlalchemy.')
    session = scoped_session(sessionmaker())
    session.configure(bind=engine)

    model_paths = aslist(settings.get('pyramid_jsonapi.test_data_models', []))
    models = get_models(model_paths)
    mixer = Mixer(session=session, commit=True)

    test_data_module_name = settings.get('pyramid_jsonapi.test_data_module', None)
    blended = namedtuple('FakeBlended', 'blended')({})

    if test_data_module_name:
        test_data = importlib.import_module(test_data_module_name)
        blended = test_data.Blended(mixer)

    for model in models.values():
        blendin = blended.blended.get(model, {})
        try:
            options = blendin.pop('#options')
        except KeyError:
            options = {}
        try:
            nrecords = options['nrecords']
        except KeyError:
            nrecords = args.nrecords
        mixer.cycle(nrecords).blend(model, **blendin)
