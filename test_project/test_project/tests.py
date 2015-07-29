import unittest
import transaction
import testing.postgresql
import webtest
from pyramid.paster import get_app
from sqlalchemy import create_engine

#from pyramid import testing

from .models import (
    DBSession,
    Base,
    Person,
    Blog,
    Post
)

class TestJsonApi(unittest.TestCase):
    '''Unit test suite for jsonapi.
    '''

    # Some initial data in a handy form.
    data = {
        'people': [{'name': 'alice'}, {'name': 'bob'}],
        'blogs': [{'title': 'main'}, {'title': 'second'}]
    }
    # Indexes for later tests.
    idx = {}
    idx['people'] = {obj['name']: obj for obj in data['people']}
    idx['blogs'] = {obj['title']: obj for obj in data['blogs']}

    @classmethod
    def setUpClass(cls):
        '''Create a test DB and import data.'''
        # Create a new database somewhere in /tmp
        cls.postgresql = testing.postgresql.Postgresql()
        cls.engine = create_engine(cls.postgresql.url())
        DBSession.configure(bind=cls.engine)
        Base.metadata.create_all(cls.engine)

        # Add some basic test data.
        with transaction.manager:
            for pdata in cls.data['people']:
                person = Person(**pdata)
                DBSession.add(person)
                for bdata in cls.data['blogs']:
                    bdata['owner'] = person
                    blog = Blog(**bdata)
                    DBSession.add(blog)
                    post1 = Post(
                        title='first post',
                        content='{}\'s first post in {}'.format(person.name, blog.title),
                        blog=blog,
                        author=person
                    )
                    post2 = Post(
                        title='also ran',
                        content='{}\'s second post in {}'.format(person.name, blog.title),
                        blog=blog,
                        author=person
                    )

    @classmethod
    def tearDownClass(cls):
        '''Throw away test DB.'''
        Base.metadata.drop_all(cls.engine)
        DBSession.close()
        cls.postgresql.stop()

    def setUp(self):
        transaction.begin()

    def tearDown(self):
        transaction.abort()

    def test_db_people(self):
        '''Should return initial list of people driect from DB.'''
        results = DBSession.query(Person).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(self.data['people']))
        for item in results:
            self.assertIsInstance(item, Person)
            self.assertTrue(item.name in self.idx['people'])
            self.assertTrue(len(item.blogs) != 0)
            self.assertTrue(len(item.posts) != 0)

    def test_db_blogs(self):
        '''Should return initial blogs from DB with accessible owners.'''
        results = DBSession.query(Blog).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(self.data['blogs']) * len(self.data['people']))
        for item in results:
            self.assertIsInstance(item, Blog)
            self.assertTrue(item.title in self.idx['blogs'])
            self.assertTrue(item.owner.name in self.idx['people'])

    def test_db_posts(self):
        '''Should fetch all posts from DB.'''
        results = DBSession.query(Post).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(self.data['blogs']) * len(self.data['people']) * 2)
        for item in results:
            self.assertIsInstance(item, Post)
            self.assertTrue(item.author.name in self.idx['people'])
            self.assertTrue(item.blog.title in self.idx['blogs'])
