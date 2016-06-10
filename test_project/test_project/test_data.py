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
            opts = None
            if len(dataset) > 2:
                opts = dataset[2]
            for item in dataset[1]:
                set_item(model, item, opts)
        for assoc_data in data.get('associations',[]):
            table = getattr(models, assoc_data[0])
            for assoc in assoc_data[1]:
                rows = DBSession.query(table).filter_by(**assoc).all()
                if not rows:
                    DBSession.execute(table.insert(), assoc)

def set_item(model, data, opts):
    '''Make sure item exists in the db with attributes as specified in data.
    '''
    # Assume only one primary key
    if opts is None:
        opts = dict()

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
        seq_name = opts.get('id_seq')
        if seq_name is not None:
            # The key columnn gets its default value from a sequence: make sure
            # that the sequence is updated to at least the value of the id we're
            # adding now.
            if seq_name == '*':
                # '*' indicates use the default sequence name.
                seq_name = '{}_{}_seq'.format(
                    sqlalchemy.inspect(item).mapper.class_.__tablename__,
                    keycol.name
                )

            item_id = getattr(item, keycol.name)

            # Increment the sequence since:
            #   1) We'll probably need to anyway as we add the item.
            #   2) It's the only way to find out the value if the sequence
            #      hasn't been used yet in this session.
            seqval = DBSession.execute(
                "select nextval('{}')".format(seq_name)
            ).scalar()

            if seqval > int(item_id):
                # If seqval is higher than item_id then we shouldn't have
                # incremented it: put it back by one.
                #
                # WARNING: this is not safe! We didn't do it atomically and
                # there's a danger someone in another session/transaction
                # changed the sequence in between.
                #
                # We should be fine here because we're only populating the DB
                # with test data - no-one else should be using it.
                DBSession.execute(
                    "select setval('{}', {})".format(
                        seq_name, seqval - 1
                        )
                ).scalar()
                seqval = seqval - 1
            print('*************************************')
            print('item added as ' + str(item_id))
            print('seq {} at {}'.format(
                seq_name, seqval
            ))
