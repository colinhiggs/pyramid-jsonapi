"""Generate random test data using mixer.

Creates random relationships between objects as determined by the schema
(models).
"""
import argparse
import importlib
import networkx as nx
import random
import sqlalchemy
import sqlalchemy.exc

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


def is_model(model):
    """Determine if argument is a sqlalchemy model.

    Args:
        model: the class to be tested.

    Returns:
        True if model is a model, False otherwise
    """
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
    """Get a list of models from model paths.

    Args:
        model_paths (list of str): A list of string representations of module
        paths.

    Returns:
        A list of sqlalchemy model classes.
    """
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
                if is_model(model)
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
    return models.values()


def dag_from_models(models):
    """Create a directed acyclic graph from a list of models.

    Use the networkx module to populate a DiGraph by following relationships.
    The graph will be topologically sorted so that objects can be created in
    order.

    Args:
        models (list): list of models.

    Returns:
        networkx.DiGraph
    """
    dg = nx.DiGraph()
    for model in models:
        dg.add_node(model)
        mapper = sqlalchemy.inspect(model).mapper
        for rel in mapper.relationships.values():
            if rel.mapper.class_ in models and not rel.uselist:
                dg.add_edge(model, rel.mapper.class_, name=rel.key)
    return dg


def generate_data(session, mixer, models, blendin={}, nrecords=1000):
    """Generate objects and relationships between them.

    Args:
        session: sqlalchemy session.
        mixer: Mixer object.
        models: list of models.
        blendin: dictionary of data generators in the form::

            {
                Person: {
                    'name': mixer.faker.name,
                    'description': mixer.faker.sentence,
                },
                Blog: {
                    'title': mixer.faker.title,
                    'content': mixer.faker.paragraph,
                }
            }

        nrecord: the number of records per model to generate.
    """
    g = dag_from_models(models)
    items = {}
    for model in reversed(list(nx.topological_sort(g))):
        blendin[model] = blendin.get(model, {})
        for edge in g.edges(model):
            blendin[model][g.edges[edge]['name']] = (
                i for i in random.choices(items[edge[1]], k=nrecords)
            )
        items[model] = mixer.cycle(nrecords).blend(
            model,
            **blendin.get(model, {})
        )


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

    blendin = {}
    test_data_module_name = settings.get('pyramid_jsonapi.test_data_module', None)
    if test_data_module_name:
        test_data_module = importlib.import_module(test_data_module_name)
        try:
            blendin = test_data_module.blendin(mixer)
        except AttributeError:
            pass

    generate_data(session, mixer, models, blendin=blendin, nrecords=args.nrecords)
