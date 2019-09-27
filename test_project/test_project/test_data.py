import sqlalchemy
from sqlalchemy import func
import transaction
from test_project import models
from test_project.models import (
    DBSession,
)
import datetime
import inspect
import sys
import json
from pathlib import Path
import re

def add_to_db(engine):
    '''Add some basic test data.'''
    meta = sqlalchemy.MetaData()
    meta.reflect(engine)
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
                set_item(model, item_transform(item), opts)
            # Set the current value of the associated sequence to the maximum
            # id we added.
            try:
                id_col_name = model.__pyramid_jsonapi__['id_col_name']
            except AttributeError:
                id_col_name = sqlalchemy.inspect(model).primary_key[0].name
            seq_text = meta.tables[model.__tablename__].columns[id_col_name].server_default.arg.text
            seq_name = re.match(r"^nextval\('(\w+)'::", seq_text).group(1)
            max_id = DBSession.query(func.max(getattr(model, id_col_name))).one()[0]
            DBSession.execute("select setval('{}', {})".format(seq_name, max_id))

        for assoc_data in data.get('associations',[]):
            table = getattr(models, assoc_data[0])
            for assoc in assoc_data[1]:
                rows = DBSession.query(table).filter_by(**assoc).all()
                if not rows:
                    DBSession.execute(table.insert(), assoc)

def item_transform(item):
    '''Transform item prior to saving to database.

     * Attributes named __json__<something> will be renamed to <something> with
       values parsed by the json parser first.
    '''
    new_item = {}
    for att, val in item.items():
        if att.startswith('__json__'):
            att = att.replace('__json__','')
            val = json.loads(val)
        new_item[att] = val
    return new_item

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
