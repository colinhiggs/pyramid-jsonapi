import unittest
import transaction
import testing.postgresql
import webtest
import urllib
from pyramid.paster import get_app
from sqlalchemy import create_engine

from .models import (
    DBSession,
    Base
)

from . import test_data

class TestBugs(unittest.TestCase):
    '''Tests for issues.

    https://github.com/colinhiggs/pyramid-jsonapi/issues
    '''

    @classmethod
    def setUpClass(cls):
        '''Create a test DB and import data.'''
        # Create a new database somewhere in /tmp
        cls.postgresql = testing.postgresql.Postgresql(port=7654)
        cls.engine = create_engine(cls.postgresql.url())
        DBSession.configure(bind=cls.engine)

        cls.app = get_app('testing.ini')
        cls.test_app = webtest.TestApp(cls.app)

    @classmethod
    def tearDownClass(cls):
        '''Throw away test DB.'''
        DBSession.close()
        cls.postgresql.stop()

    def setUp(self):
        Base.metadata.create_all(self.engine)
        # Add some basic test data.
        test_data.add_to_db()
        transaction.begin()

    def tearDown(self):
        transaction.abort()
        Base.metadata.drop_all(self.engine)

    def test_19_last_negative_offset(self):
        '''last link should not have negative offset.

        'last' link has negative offset if zero results are returned
        '''
        # Need an empty collection: use a filter that will not match.
        last = self.test_app.get(
            '/posts?filter[title:eq]=frog'
        ).json['links']['last']
        offset = int(
            urllib.parse.parse_qs(
                urllib.parse.urlparse(last).query
            )['page[offset]'][0]
        )
        self.assertGreaterEqual(offset, 0)
