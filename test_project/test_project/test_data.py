import sqlalchemy
import transaction
from . import models
from .models import (
    DBSession,
)
import datetime
import inspect
import sys
import json
from pathlib import Path

def add_to_db():
    '''Add some basic test data.'''
    # Some initial data in a handy form.
    module_file = Path(inspect.getfile(sys.modules[__name__]))
    with open(str(module_file.parent / 'test_data.json')) as f:
        data = json.load(f)
    with transaction.manager:
        for dataset in data['models']:
            model = getattr(models, dataset[0])
            for item in dataset[1]:
                set_item(model, item)
        for assoc_data in data['associations']:
            table = getattr(models, assoc_data[0])
            for assoc in assoc_data[1]:
                rows = DBSession.query(table).filter_by(**assoc).all()
                if not rows:
                    DBSession.execute(table.insert(), assoc)

def set_item(model, data):
    '''Make sure item exists in the db with attributes as specified in data.
    '''
    # Assume only one primary key
    keycols = sqlalchemy.inspect(model).primary_key
    if len(keycols) > 1:
        raise Exception(
            'Model {} has more than one primary key.'.format(
                model_class.__name__
            )
        )
    keycol = keycols[0]
    item = DBSession.query(model).get(data[keycol.name])
    if item:
        DBSession.query(model)\
            .filter(keycol == data[keycol.name]).update(data)
    else:
        item = model(**data)
        DBSession.add(item)
