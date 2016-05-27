import unittest
import transaction
import testing.postgresql
import webtest
from pyramid.paster import get_app
from sqlalchemy import create_engine

from .models import (
    DBSession,
    Base
)

from . import test_data

class TestSpec(unittest.TestCase):
    '''Test compliance against jsonapi spec.

    http://jsonapi.org/format/
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

    def test_spec_server_content_type(self):
        '''Response should have correct content type.

        Servers MUST send all JSON API data in response documents with the
        header Content-Type: application/vnd.api+json without any media type
        parameters.
        '''
        # Fetch a representative page
        r = self.test_app.get('/people')
        self.assertEqual(r.content_type, 'application/vnd.api+json')

    def test_spec_incorrect_client_content_type(self):
        '''Server should return error if we send media type parameters.

        Servers MUST respond with a 415 Unsupported Media Type status code if a
        request specifies the header Content-Type: application/vnd.api+json with
        any media type parameters.
        '''
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )

    def test_spec_accept_not_acceptable(self):
        '''Server should respond with 406 if all jsonapi media types have parameters.

        Servers MUST respond with a 406 Not Acceptable status code if a
        request’s Accept header contains the JSON API media type and all
        instances of that media type are modified with media type parameters.
        '''
        # Should work with correct accepts header.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json' },
        )
        # 406 with one incorrect type.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json; param=val' },
            status=406,
        )
        # 406 with more than one type but none without params.
        r = self.test_app.get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json; param=val,' +
                'application/vnd.api+json; param2=val2' },
            status=406,
        )

    def test_spec_toplevel_must(self):
        '''Server response must have one of data, errors or meta.

        A JSON object MUST be at the root of every JSON API request and response
        containing data.

        A document MUST contain at least one of the following top-level members:

            * data: the document’s “primary data”
            * errors: an array of error objects
            * meta: a meta object that contains non-standard meta-information.
        '''
        # Should be object with data member.
        r = self.test_app.get('/people')
        self.assertIn('data', r.json)
        # Should also have a meta member.
        self.assertIn('meta', r.json)

        # Should be object with an array of errors.
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )
        self.assertIn('errors', r.json)
        self.assertIsInstance(r.json['errors'], list)

    def test_spec_get_primary_data_empty(self):
        '''Should return an empty list of results.

        Primary data MUST be either:

            * ...or an empty array ([])

        A logical collection of resources MUST be represented as an array, even
        if it... is empty.
        '''
        r = self.test_app.get('/people?filter[name:eq]=doesnotexist')
        self.assertEqual(len(r.json['data']), 0)

    def test_spec_get_primary_data_array(self):
        '''Should return an array of resource objects.

        Primary data MUST be either:

            * an array of resource objects, an array of resource identifier
            objects, or an empty array ([]), for requests that target resource
            collections
        '''
        # Data should be an array of person resource objects or identifiers.
        r = self.test_app.get('/people')
        self.assertIn('data', r.json)
        self.assertIsInstance(r.json['data'], list)
        item = r.json['data'][0]


    def test_spec_get_primary_data_array_of_one(self):
        '''Should return an array of one resource object.

        A logical collection of resources MUST be represented as an array, even
        if it only contains one item...
        '''
        r = self.test_app.get('/people?page[limit]=1')
        self.assertIn('data', r.json)
        self.assertIsInstance(r.json['data'], list)
        self.assertEqual(len(r.json['data']), 1)

    def test_spec_get_primary_data_single(self):
        '''Should return a single resource object.

        Primary data MUST be either:

            * a single resource object, a single resource identifier object, or
            null, for requests that target single resources
        '''
        # Find the id of alice.
        r = self.test_app.get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']
        # Now get alice object.
        r = self.test_app.get('/people/' + alice_id)
        alice = r.json['data']
        self.assertEqual(alice['attributes']['name'], 'alice')

    def test_spec_resource_object_must(self):
        '''Resource object should have at least id and type.

        A resource object MUST contain at least the following top-level members:
            * id
            * type

        The values of the id and type members MUST be strings.
        '''
        r = self.test_app.get('/people?page[limit]=1')
        item = r.json['data'][0]
        # item must have at least a type and id.
        self.assertEqual(item['type'], 'people')
        self.assertIn('id', item)
        self.assertIsInstance(item['type'], str)
        self.assertIsInstance(item['id'], str)

    def test_spec_resource_object_must(self):
        '''Fetched resource should have attributes, relationships, links, meta.

        a resource object MAY contain any of these top-level members:

            * attributes: an attributes object representing some of the
              resource’s data.

            * relationships: a relationships object describing relationships
              between the resource and other JSON API resources.

            * links: a links object containing links related to the resource.

            * meta: a meta object containing non-standard meta-information about
              a resource that can not be represented as an attribute or
              relationship.
        '''
        r = self.test_app.get('/people?page[limit]=1')
        item = r.json['data'][0]
        self.assertIn('attributes', item)
        #self.assertIn('relationships', item)
        self.assertIn('links', item)
        #self.assertIn('meta', item)

    def test_spec_type_id_identify_resource(self):
        '''Using type and id should fetch a single resource.

        Within a given API, each resource object’s type and id pair MUST
        identify a single, unique resource.
        '''
        # Find the id of alice.
        r = self.test_app.get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']

        # Search for alice by id. We should get one result whose name is alice.
        r = self.test_app.get('/people?filter[id:eq]={}'.format(alice_id))
        self.assertEqual(len(r.json['data']), 1)
        item = r.json['data'][0]
        self.assertEqual(item['id'], alice_id)
        self.assertEqual(item['attributes']['name'], 'alice')

    def test_spec_attributes(self):
        '''attributes key should be an object.

        The value of the attributes key MUST be an object (an “attributes
        object”). Members of the attributes object (“attributes”) represent
        information about the resource object in which it’s defined.
        '''
        # Fetch a single post.
        r = self.test_app.get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check attributes.
        self.assertIn('attributes', item)
        atts = item['attributes']
        self.assertIn('title', atts)
        self.assertIn('content', atts)
        self.assertIn('published_at', atts)

    def test_spec_no_forreign_keys(self):
        '''No forreign keys in attributes.

        Although has-one foreign keys (e.g. author_id) are often stored
        internally alongside other information to be represented in a resource
        object, these keys SHOULD NOT appear as attributes.
        '''
        # posts have author_id and blog_id as has-one forreign keys. Check that
        # they don't make it into the JSON representation (they should be in
        # relationships instead).

        # Fetch a single post.
        r = self.test_app.get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check for forreign keys.
        self.assertNotIn('author_id', item['attributes'])
        self.assertNotIn('blog_id', item['attributes'])

    def test_spec_relationships_object(self):
        '''Relationships key should be object.

        The value of the relationships key MUST be an object (a “relationships
        object”). Members of the relationships object (“relationships”)
        represent references from the resource object in which it’s defined to
        other resource objects.
        '''
        # Fetch a single blog (has to-one and to-many realtionships)
        r = self.test_app.get('/blogs?page[limit]=1')
        item = r.json['data'][0]
        # Should have relationships key
        self.assertIn('relationships', item)
        rels = item['relationships']

        # owner: to-one
        self.assertIn('owner', rels)
        owner = rels['owner']
        self.assertIn('links', owner)
        self.assertIn('data', owner)
        self.assertIsInstance(owner['data'], dict)
        self.assertIn('type', owner['data'])
        self.assertIn('id', owner['data'])

        # posts: to-many
        self.assertIn('posts', rels)
        posts = rels['posts']
        self.assertIn('links', posts)
        self.assertIn('data', posts)
        self.assertIsInstance(posts['data'], list)
        self.assertIn('type', posts['data'][0])
        self.assertIn('id', posts['data'][0])

    def test_spec_relationships_links(self):
        '''Relationships links object should have 'self' and 'related' links.
        '''
        # Fetch a single blog (has to-one and to-many relationships)
        r = self.test_app.get('/blogs?page[limit]=1')
        item = r.json['data'][0]
        # Should have relationships key
        links = item['relationships']['owner']['links']
        self.assertIn('self', links)
        self.assertTrue(
            links['self'].endswith(
                '/blogs/{}/relationships/owner'.format(item['id'])
            )
        )
        self.assertIn('related', links)
        self.assertTrue(
            links['related'].endswith(
                '/blogs/{}/owner'.format(item['id'])
            )
        )

    def test_spec_related_get(self):
        ''''related' link should fetch related resource(s).

        If present, a related resource link MUST reference a valid URL, even if
        the relationship isn’t currently associated with any target resources.
        '''
        # Fetch a single blog (has to-one and to-many relationships)
        r = self.test_app.get('/blogs/1')
        item = r.json['data']
        owner_url = item['relationships']['owner']['links']['related']
        posts_url = item['relationships']['posts']['links']['related']

        owner_data = self.test_app.get(owner_url).json['data']
        # owner should be a single object.
        self.assertIsInstance(owner_data, dict)
        # owner should be of type 'people'
        self.assertEqual(owner_data['type'], 'people')

        posts_data = self.test_app.get(posts_url).json['data']
        # posts should be a collection.
        self.assertIsInstance(posts_data, list)
        # each post should be of type 'posts'
        for post in posts_data:
            self.assertEqual(post['type'], 'posts')

    def test_spec_resource_linkage(self):
        '''Appropriate related resource identifiers in relationship.

        Resource linkage in a compound document allows a client to link together
        all of the included resource objects without having to GET any URLs via
        links.

        Resource linkage MUST be represented as one of the following:

            * null for empty to-one relationships.
            * an empty array ([]) for empty to-many relationships.
            * a single resource identifier object for non-empty to-one
             relationships.
            * an array of resource identifier objects for non-empty to-many
             relationships.
        '''
        # An anonymous comment.
        # 'null for empty to-one relationships.'
        comment = self.test_app.get('/comments/5').json['data']
        self.assertIsNone(comment['relationships']['author']['data'])

        # A comment with an author.
        # 'a single resource identifier object for non-empty to-one
        # relationships.'
        comment = self.test_app.get('/comments/1').json['data']
        author = comment['relationships']['author']['data']
        self.assertEqual(author['type'], 'people')

        # A post with no comments.
        # 'an empty array ([]) for empty to-many relationships.'
        post = self.test_app.get('/posts/1').json['data']
        comments = post['relationships']['comments']['data']
        self.assertEqual(len(comments), 0)

        # A post with comments.
        # 'an array of resource identifier objects for non-empty to-many
        # relationships.'
        post = self.test_app.get('/posts/4').json['data']
        comments = post['relationships']['comments']['data']
        self.assertGreater(len(comments), 0)
        self.assertEqual(comments[0]['type'], 'comments')

    def test_spec_links_self(self):
        ''''self' link should fetch same object.

        The optional links member within each resource object contains links
        related to the resource.

        If present, this links object MAY contain a self link that identifies
        the resource represented by the resource object.

        A server MUST respond to a GET request to the specified URL with a
        response that includes the resource as the primary data.
        '''
        person = self.test_app.get('/people/1').json['data']
        # Make sure we got the expected person.
        self.assertEqual(person['type'], 'people')
        self.assertEqual(person['id'], '1')
        # Now fetch the self link.
        person_again = self.test_app.get(person['links']['self']).json['data']
        # Make sure we got the same person.
        self.assertEqual(person_again['type'], 'people')
        self.assertEqual(person_again['id'], '1')

    def test_spec_included_array(self):
        '''Included resources should be in an array under 'included' member.

        In a compound document, all included resources MUST be represented as an
        array of resource objects in a top-level included member.
        '''
        person = self.test_app.get('/people/1?include=blogs').json
        self.assertIsInstance(person['included'], list)
        # Each item in the list should be a resource object: we'll look for
        # type, id and attributes.
        for blog in person['included']:
            self.assertIn('id', blog)
            self.assertEqual(blog['type'], 'blogs')
            self.assertIn('attributes', blog)

    def test_spec_compound_full_linkage(self):
        '''All included resources should be referenced by a resource link.

        Compound documents require "full linkage", meaning that every included
        resource MUST be identified by at least one resource identifier object
        in the same document. These resource identifier objects could either be
        primary data or represent resource linkage contained within primary or
        included resources.
        '''
        # get a person with included blogs and comments.
        person = self.test_app.get('/people/1?include=blogs,comments').json
        # Find all the resource identifiers.
        rids = set()
        for rel in person['data']['relationships'].values():
            for item in rel['data']:
                rids.add((item['type'], item['id']))

        # Every included item should have an identifier somewhere.
        for item in person['included']:
            type_ = item['type']
            id_ = item['id']
            self.assertIn((type_, id_), rids)


    def test_api_errors_structure(self):
        '''Errors should be array of objects with code, title, detail members.'''
        r = self.test_app.get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )
        self.assertIn('errors', r.json)
        self.assertIsInstance(r.json['errors'], list)
        err = r.json['errors'][0]
        self.assertIn('code', err)
        self.assertIn('title', err)
        self.assertIn('detail', err)
