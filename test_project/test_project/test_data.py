#import testing.postgresql
#from sqlalchemy import create_engine
import sqlalchemy
import transaction
from .models import (
    DBSession,
    Base,
    Person,
    Blog,
    Post,
    Comment
)
import datetime

# Some initial data in a handy form.
data = {
    'people': [{'name': 'alice'}, {'name': 'bob'}, {'name': 'deleteme'}],
    'blogs': [{'title': 'main'}, {'title': 'second'}],
    'comments': [{'content': 'first post!'}, ]
}
# Indexes for later tests.
idx = {}
idx['people'] = {obj['name']: obj for obj in data['people']}
idx['blogs'] = {obj['title']: obj for obj in data['blogs']}

npeople = len(data['people'])
nblogs_per_person = len(data['blogs'])
nblogs = npeople * nblogs_per_person
nposts_per_blog = 2
nposts = nblogs * nposts_per_blog

def add_to_db():
    '''Add some basic test data.'''
    with transaction.manager:
        for pdata in data['people']:
            try:
                person = DBSession.query(Person)\
                    .filter_by(name=pdata['name']).one()
            except sqlalchemy.orm.exc.NoResultFound:
                person = Person(**pdata)
                DBSession.add(person)
            for bdata in data['blogs']:
                bdata['owner'] = person
                try:
                    blog = DBSession.query(Blog)\
                        .filter_by(title=bdata['title'], owner=person).one()
                except sqlalchemy.orm.exc.NoResultFound:
                    blog = Blog(**bdata)
                    DBSession.add(blog)
                DBSession.flush()
                try:
                    post1 = DBSession.query(Post)\
                        .filter_by(title='first post', author=person, blog=blog).one()
                except sqlalchemy.orm.exc.NoResultFound:
                    post1 = Post(
                        title='first post',
                        content='{}\'s first post in {}'.format(person.name, blog.title),
                        blog=blog,
                        author=person,
                        published_at=datetime.datetime(2015,1,1)
                        )
                    DBSession.add(post1)
                for cdata in data['comments']:
                    cdata['post'] = post1
                    try:
                        comment = DBSession.query(Comment)\
                            .filter_by(content=cdata['content'], post=post1)\
                                .one()
                    except sqlalchemy.orm.exc.NoResultFound:
                        comment = Comment(**cdata)
                        DBSession.add(comment)
                try:
                    post2 = DBSession.query(Post)\
                        .filter_by(title='also ran', author=person, blog=blog).one()
                except sqlalchemy.orm.exc.NoResultFound:
                    post1 = Post(
                        title='also ran',
                        content='{}\'s second post in {}'.format(person.name, blog.title),
                        blog=blog,
                        author=person,
                        published_at=datetime.datetime.today()
                        )
                    DBSession.add(post1)
