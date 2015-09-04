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
from .test_data import (
    data,
    idx,
    npeople, nblogs, nposts,
    nblogs_per_person, nposts_per_blog
)

class TestJsonApi(unittest.TestCase):
    '''Unit test suite for jsonapi.
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

    def test_db_people(self):
        '''Should return initial list of people direct from DB.'''
        results = DBSession.query(Person).all()
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), len(data['people']))
        for item in results:
            self.assertIsInstance(item, Person)
            self.assertIn(item.name, idx['people'])
            self.assertNotEqual(len(item.blogs), 0)
            self.assertNotEqual(len(item.posts), 0)

    def test_db_blogs(self):
        '''Should return initial blogs from DB with accessible owners.'''
        results = DBSession.query(Blog).all()
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), len(data['blogs']) * len(data['people']))
        for item in results:
            self.assertIsInstance(item, Blog)
            self.assertIn(item.title, idx['blogs'])
            self.assertIn(item.owner.name, idx['people'])

    def test_db_posts(self):
        '''Should fetch all posts from DB.'''
        results = DBSession.query(Post).all()
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), len(data['blogs']) * len(data['people']) * 2)
        for item in results:
            self.assertIsInstance(item, Post)
            self.assertIn(item.author.name, idx['people'])
            self.assertIn(item.blog.title, idx['blogs'])

    def test_api_people_get(self):
        '''Should return all people via jsonapi.'''
        r = self.test_app.get('/people')
        self.assertEqual(r.status_code, 200)
        jdata = r.json['data']

        # collection_get should return list
        self.assertIsInstance(jdata, list)
        self.assertEqual(len(jdata), len(idx['people']))

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
                self.assertIn(item['attributes']['name'], idx['people'])
                # Has a blogs relationship.
                self.assertIn('blogs', item['relationships'])
                # Has a posts relationship.
                self.assertIn('posts', item['relationships'])

    def test_api_empty_get(self):
        '''Should return an empty list of results.'''
        r = self.test_app.get('/people?filter[name:eq]=doesnotexist')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), 0)

    def test_api_person_get(self):
        '''Should return a specific person.'''
        # Find the id of alice.
        r = self.test_app.get('/people?filter[name:eq]=alice')
        self.assertEqual(r.status_code, 200)
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']
        # Now get alice object.
        r = self.test_app.get('/people/' + alice_id)
        alice = r.json['data']
        self.assertEqual(alice['attributes']['name'], 'alice')

    def test_api_person_post(self):
        '''Should add a new person.'''
        # Add a person.
        r = self.test_app.post('/people', '{"attributes": {"name": "george"}}')
        self.assertEqual(r.status_code, 201)
        # Find them to make sure they exist.
        r = self.test_app.get('/people?filter[name:eq]=george')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), 1)

    def test_api_post_delete(self):
        '''Should delete a post (non cascading delete).'''
        # Find the id of a post to delete.
        r = self.test_app.get("/posts?filter[content:eq]=deleteme's second post in main")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']),1)
        post_id = r.json['data'][0]['id']
        # Now delete it.
        r = self.test_app.delete('/posts/' + post_id)
        self.assertEqual(r.status_code, 200)
        # Now make sure it isn't there.
        r = self.test_app.get('/posts/' + post_id, status=404)
        self.assertEqual(r.status_code, 404)

    @unittest.skip('wait to sort out cascading deletes')
    def test_api_person_delete(self):
        '''Should delete person "deleteme" and their blogs and posts.'''
        # Find the person first.
        r = self.test_app.get('/people?filter[name:eq]=deleteme')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']),1)
        dm_id = r.json['data'][0]['id']

        # Delete them.
        r = self.test_app.delete('/people/' + str(dm_id))
        self.assertEqual(r.status_code, 200)

        # Try to find them again.
        r = self.test_app.get('/people?filter[name:eq]=deleteme')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']),0)

    def test_api_posts_get(self):
        '''Should return all posts.'''
        r = self.test_app.get('/posts?page[limit]=100')
        self.assertEqual(r.status_code, 200)
        d = r.json
        data = d['data']
        self.assertEqual(len(data), nposts)

    def test_api_blogs_get(self):
        '''Should return all blogs.'''
        r = self.test_app.get('/blogs')
        self.assertEqual(r.status_code, 200)
        d = r.json
        data = d['data']
        self.assertEqual(len(data), nblogs)

    def test_api_relationships_get(self):
        '''Should return relationships from blog.'''
        # Follow relationship links from first blog returned.
        r = self.test_app.get('/blogs')
        self.assertEqual(r.status_code, 200)
        blog = r.json['data'][0]
        posts = blog['relationships']['posts']
        owner = blog['relationships']['owner']

        # blogs
        self.assertIsInstance(posts['data'], list)
        # Every blog should have 2 posts.
        self.assertEqual(len(posts['data']), nposts_per_blog)
        # Follow posts link and check ids
        post_ids = [str(item['id']) for item in posts['data']]
        r = self.test_app.get(posts['links']['self'])
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json['data']), len(post_ids))
        for item in r.json['data']:
            self.assertIn(item['id'], post_ids)

        # owner.
        self.assertIsInstance(owner['data'], dict)
        owner_id = str(owner['data']['id'])
        # Follow owner link:
        r = self.test_app.get(owner['links']['self'])
        self.assertEqual(r.status_code, 200)
        # Check that the id is the same as we got before.
        self.assertEqual(r.json['data'][0]['id'], owner_id)

    def test_api_skewed_pagination(self):
        '''Should get pages from query with offset not a multiple of limit.'''

        # Build a list with all post ids, sorted.
        post_ids = [int(post['id']) for post in
            self.test_app.get('/posts').json['data']]
        post_ids.sort()

        # Fetch 3 per page.
        # Offset of 1 so that there is a previous page.
        # Offset deliberately not a multiple of 3.
        r = self.test_app.get('/posts?page[limit]=3&page[offset]=1')
        self.assertEqual(r.status_code, 200)

        data = r.json['data']
        # Check that we got 3 results, as per pagination instruction.
        self.assertEqual(len(data), 3)

        links = r.json['links']
        # Check that pagination links are there.
        self.assertIn('first', links)
        self.assertIn('last', links)
        self.assertIn('prev', links)
        self.assertIn('next', links)

        # Check that 'first' link gets a page of 3 starting at post_ids[0]
        r = self.test_app.get(links['first'])
        self.assertEqual(r.status_code, 200)
        ids = [int(post['id']) for post in r.json['data']]
        ids.sort()
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids[0], post_ids[0])

        # Check that 'last' link gets last page.
        last_offset = ((nposts - 1) // 3) * 3
        nlast_results = nposts - last_offset
        r = self.test_app.get(links['last'])
        self.assertEqual(r.status_code, 200)
        ids = [int(post['id']) for post in r.json['data']]
        ids.sort()
        self.assertEqual(len(ids), nlast_results)
        self.assertEqual(ids[0], post_ids[last_offset])

        # Check that 'prev' link gets a page of 3 starting at post_ids[0]
        r = self.test_app.get(links['prev'])
        self.assertEqual(r.status_code, 200)
        ids = [int(post['id']) for post in r.json['data']]
        ids.sort()
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids[0], post_ids[0])

        # Check that 'next' link gets a page of 3 starting at post_ids[4]
        r = self.test_app.get(links['next'])
        self.assertEqual(r.status_code, 200)
        ids = [int(post['id']) for post in r.json['data']]
        ids.sort()
        self.assertEqual(len(ids), 3)
        self.assertEqual(ids[0], post_ids[4])

    def test_api_filters(self):
        '''Should return filtered search results.'''
        r = self.test_app.get('/posts?filter[title:eq]=first post')
        self.assertEqual(len(r.json['data']), npeople * nblogs_per_person)
        r = self.test_app.get('/posts?filter[title:eq]=first post&filter[content:endswith]=main')
        self.assertEqual(len(r.json['data']), npeople)

    def test_api_sorting(self):
        '''Should return sorted results.'''
        # Basic sorting.
        r = self.test_app.get('/posts?sort=id')
        lst = [int(item['id']) for item in r.json['data']]
        self.assertEqual(sorted(lst), lst)
        r = self.test_app.get('/posts?sort=title')
        lst = [item['attributes']['title'] for item in r.json['data']]
        self.assertEqual(sorted(lst), lst)
        # Reverse sort.
        r = self.test_app.get('/posts?sort=-title')
        lst = [item['attributes']['title'] for item in r.json['data']]
        self.assertEqual(sorted(lst, reverse=True), lst)
        # Sort by following author relationship (default to id)
        r = self.test_app.get('/posts?sort=author')
        lst = [int(item['attributes']['author_id']) for item in r.json['data']]
        self.assertEqual(sorted(lst), lst)
        # Sort on author name
        r = self.test_app.get('/posts?sort=author.name')
        lst = [
            self.test_app.get(
                '/people/' + str(item['relationships']['author']['data']['id'])
            ).json['data']['attributes']['name']
            for item in r.json['data']
        ]
        self.assertEqual(sorted(lst), lst)

    def test_api_sparse_fields(self):
        '''Should return sparse results.'''
        r = self.test_app.get('/posts?fields[posts]=title')
        self.assertIn('title', r.json['data'][0]['attributes'])
        self.assertNotIn('content', r.json['data'][0]['attributes'])

    def test_api_includes(self):
        '''Should return compound documents.'''
        pass

    def test_resource_decorator(self):
        pass

    def test_resource_links_callback(self):
        pass

    def test_resource_meta_callback(self):
        pass
