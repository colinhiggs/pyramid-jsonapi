import argparse
import pyramid_jsonapi.generate_test_data as pj_gen

from mixer.backend.sqlalchemy import Mixer
from mixer.main import mixer
from pyramid.paster import (
    get_appsettings,
    setup_logging,
)
from pyramid.settings import aslist
from sqlalchemy import engine_from_config
from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
)
from test_project import models

blendin = {
    models.Person: {
        'name': mixer.faker.name,
    },
    models.Blog: {
        'title': mixer.faker.title,
    },
    models.Post: {
        'title': mixer.faker.title,
    },
    models.Comment: {
        'content': mixer.faker.paragraph,
    },
    models.BenignComment: {
        'content': mixer.faker.paragraph,
        'fawning_text': mixer.faker.sentence,
    }
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--nrecords', type=int, default=10,
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
    config_models = pj_gen.get_models(model_paths)
    all_models = [m for m in models.__dict__.values() if pj_gen.is_model(m)]
    sa_mixer = Mixer(session=session, commit=True)

    pj_gen.generate_data(
        session, sa_mixer,
        config_models,
        blendin=blendin, nrecords=args.nrecords
    )
