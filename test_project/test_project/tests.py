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

from . import test_data
from .test_data import data, idx

class TestJsonApi(unittest.TestCase):
    '''Unit test suite for jsonapi.
    '''

    @classmethod
    def setUpClass(cls):
        '''Create a test DB and import data.'''
        # Create a new database somewhere in /tmp
        cls.postgresql = testing.postgresql.Postgresql()
        cls.engine = create_engine(cls.postgresql.url())
        DBSession.configure(bind=cls.engine)
        Base.metadata.create_all(cls.engine)

        # Add some basic test data.
        test_data.add_to_db()

        cls.app = get_app('development.ini')
        cls.test_app = webtest.TestApp(cls.app)

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
        '''Should return initial list of people direct from DB.'''
        results = DBSession.query(Person).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(data['people']))
        for item in results:
            self.assertIsInstance(item, Person)
            self.assertTrue(item.name in idx['people'])
            self.assertTrue(len(item.blogs) != 0)
            self.assertTrue(len(item.posts) != 0)

    def test_db_blogs(self):
        '''Should return initial blogs from DB with accessible owners.'''
        results = DBSession.query(Blog).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(data['blogs']) * len(data['people']))
        for item in results:
            self.assertIsInstance(item, Blog)
            self.assertTrue(item.title in idx['blogs'])
            self.assertTrue(item.owner.name in idx['people'])

    def test_db_posts(self):
        '''Should fetch all posts from DB.'''
        results = DBSession.query(Post).all()
        self.assertIsInstance(results, list)
        self.assertTrue(len(results) == len(data['blogs']) * len(data['people']) * 2)
        for item in results:
            self.assertIsInstance(item, Post)
            self.assertTrue(item.author.name in idx['people'])
            self.assertTrue(item.blog.title in idx['blogs'])

    def test_api_people_get(self):
        '''Should return all people via jsonapi.'''
        r = self.test_app.get('/people')
        self.assertTrue(r.status_code == 200)
        jdata = r.json['data']

        # collection_get should return list
        self.assertIsInstance(jdata, list)
        self.assertTrue(len(jdata) == len(idx['people']))

        # Links:
        self.assertIn('links', r.json)
        links = r.json['links']
        self.assertIn('self', links)
        self.assertIn('first', links)
        self.assertIn('last', links)

        for item in jdata:
            # Has an id.
            self.assertIn('id', item)

            # Has an appropriate self link.
            self.assertIn('links', item)
            self.assertIn('self', item['links'])
            self.assertRegex(item['links']['self'], r'^.*/people/\d+')

            with self.subTest(name=item['attributes']['name']):
                # Name as expected.
                self.assertTrue(item['attributes']['name'] in idx['people'])
                # Has a blogs relationship.
                self.assertIn('blogs', item['relationships'])
                # Has a posts relationship.
                self.assertIn('posts', item['relationships'])

    def test_api_posts_get(self):
        '''Should return all posts in pages of 3.'''
        r = self.test_app.get('/posts?page[limit]=3')
        self.assertEqual(r.status_code, 200)
        d = r.json
        data = d['data']
        self.assertEqual(len(data), 3)
