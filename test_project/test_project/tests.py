from collections import namedtuple
import configparser
from functools import lru_cache
import unittest
from unittest.mock import patch, mock_open
import transaction
import testing.postgresql
import webtest
import datetime
from pyramid.config import Configurator
from pyramid.paster import get_app
from sqlalchemy import create_engine
from sqlalchemy.exc import SAWarning
import test_project
import inspect
import os
import urllib
import warnings
import json
from parameterized import parameterized
import pyramid_jsonapi.metadata
from openapi_spec_validator import validate_spec
import pprint

from test_project.models import (
    DBSession,
    Base
)

from test_project import test_data

cur_dir = os.path.dirname(
    os.path.abspath(
        inspect.getfile(inspect.currentframe())
    )
)
parent_dir = os.path.dirname(cur_dir)

RelHalf = namedtuple('RelSide', 'collection rel many filters')
FilterInfo = namedtuple('FilterInfo', 'att op value')
RelInfo = namedtuple('RelInfo', 'src tgt comment')
rel_infos = (
    RelInfo(
        RelHalf('people', 'blogs', False, []),
        RelHalf(
            'blogs', 'owner', True,
            [
                FilterInfo('title', 'eq', 'owned by 11'),
            ],
        ),
        'One to many',
    ),
    RelInfo(
        RelHalf('blogs', 'owner', True, []),
        RelHalf(
            'people', 'blogs', False,
            [
                FilterInfo('name', 'eq', 'one thing'),
            ]
        ),
        'Many to one'
    ),
    RelInfo(
        RelHalf('people', 'articles_by_assoc', True, []),
        RelHalf(
            'articles_by_assoc', 'authors', True,
            [
                FilterInfo('title', 'eq', 'Collaborative one.')
            ]
        ),
        'Many to many by association table'
    ),
    RelInfo(
        RelHalf('people', 'articles_by_proxy', True, []),
        RelHalf(
            'articles_by_obj', None, True,
            [
                FilterInfo('title', 'eq', 'Collaborative by obj one.')
            ]
        ),
        'Many to many by association proxy'
    ),
)


def setUpModule():
    '''Create a test DB and import data.'''
    # Create a new database somewhere in /tmp
    global postgresql
    global engine
    postgresql = testing.postgresql.Postgresql(port=7654)
    engine = create_engine(postgresql.url())
    DBSession.configure(bind=engine)


def tearDownModule():
    '''Throw away test DB.'''
    global postgresql
    DBSession.close()
    postgresql.stop()


def rels_doc_func(func, i, param):
    src, tgt, comment = param[0]
    return '{}:{}/{} ({})'.format(func.__name__, src.collection, src.rel, comment)


def make_ri(_type, _id):
    return { 'type': _type, 'id': _id }


class DBTestBase(unittest.TestCase):

    _test_app = None

    @classmethod
    def setUpClass(cls):
        cls._test_app = cls.new_test_app()

    def setUp(self):
        Base.metadata.create_all(engine)
        # Add some basic test data.
        test_data.add_to_db(engine)
        transaction.begin()

    def tearDown(self):
        transaction.abort()
        Base.metadata.drop_all(engine)

    def test_app(self, options=None):
        if (options is None) and self._test_app:
            # If there are no options and we have a cached app, return it.
            return self._test_app
        return self.new_test_app(options)

    @staticmethod
    def new_test_app(options=None):
        '''Create a test app.'''
        config_path = '{}/testing.ini'.format(parent_dir)
        if options:
            tmp_cfg = configparser.ConfigParser()
            tmp_cfg.read(config_path)
            tmp_cfg['app:main'].update(options or {})
            config_path = '{}/tmp_testing.ini'.format(parent_dir)
            with open(config_path, 'w') as tmp_file:
                tmp_cfg.write(tmp_file)
        with warnings.catch_warnings():
            # Suppress SAWarning: about Property _jsonapi_id being replaced by
            # Propery _jsonapi_id every time a new app is instantiated.
            warnings.simplefilter(
                "ignore",
                category=SAWarning
            )
            app = get_app(config_path)
            test_app = webtest.TestApp(app)
            test_app._pj_app = app
        if options:
            os.remove(config_path)
        return test_app

    def evaluate_filter(self, att_val, op, test_val):
        if op == 'eq':
            return att_val == test_val
        else:
            raise Exception('Unkown filter op: {}'.format(op))

class TestTmp(DBTestBase):
    '''To isolate tests so they can be run individually during development.'''
    @parameterized.expand(rel_infos[1:2], doc_func=rels_doc_func)
    def test_rels_related_get(self, src, tgt, comment):
        ''''related' link should fetch related resource(s).

        If present, a related resource link MUST reference a valid URL, even if
        the relationship isn’t currently associated with any target resources.
        '''
        # Fetch item 1 from the collection
        r = self.test_app().get('/{}/1'.format(src.collection))
        item = r.json['data']

        # Fetch the related url.
        url = item['relationships'][src.rel]['links']['related']
        data = self.test_app().get(url).json['data']

        # Check that the returned data is of the expected type.
        if tgt.many:
            self.assertIsInstance(data, list)
            for related_item in data:
                self.assertEqual(related_item['type'], tgt.collection)
        else:
            self.assertIsInstance(data, dict)
            self.assertEqual(data['type'], tgt.collection)


class TestPermissions(DBTestBase):
    '''Test permission handling mechanisms.
    '''

    def test_get_alter_result_item(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see alice (people/1)
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.name != 'alice',
        )
        # Shouldn't be allowed to see people/1 (alice)
        test_app.get('/people/1', status=403)
        # Should be able to see people/2 (bob)
        test_app.get('/people/2')

    def test_get_alter_result_item_individual_attributes(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        def pfilter(obj, *args, **kwargs):
            if obj.object.name == 'alice':
                return {'attributes': {'name'}, 'relationships': True}
            else:
                return True
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            pfilter,
        )
        # Alice should have attribute 'name' but not 'age'.
        alice = test_app.get('/people/1').json_body['data']
        self.assertIn('name', alice['attributes'])
        self.assertNotIn('age', alice['attributes'])

    def test_get_alter_result_item_individual_rels(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        def pfilter(obj, *args, **kwargs):
            if obj.object.name == 'alice':
                return {'attributes': True, 'relationships': {'blogs'}}
            else:
                return True
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            pfilter,
        )
        # Alice should have relationship 'blogs' but not 'posts'.
        alice = test_app.get('/people/1').json_body['data']
        self.assertIn('blogs', alice['relationships'])
        self.assertNotIn('posts', alice['relationships'])

    def test_get_alter_result_item_rel_ids(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see blogs/1 (one of alice's 2 blogs)
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.id != 1,
        )
        alice = test_app.get('/people/1').json_body['data']
        alice_blogs = alice['relationships']['blogs']['data']
        self.assertIn({'type': 'blogs', 'id': '2'}, alice_blogs)
        self.assertNotIn({'type': 'blogs', 'id': '1'}, alice_blogs)

    def test_get_alter_result_item_included_items(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see blogs/1 (one of alice's 2 blogs)
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.id != 1,
        )
        included = test_app.get('/people/1?include=blogs').json_body['included']
        included_blogs = {
            item['id'] for item in included if item['type'] == 'blogs'
        }
        self.assertNotIn('1', included_blogs)
        self.assertIn('2', included_blogs)

    def test_get_alter_result_collection(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see alice (people/1)
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.name != 'alice',
        )
        # Make sure we get the lowest ids with a filter.
        ret = test_app.get('/people?filter[id:lt]=3').json_body
        people = ret['data']
        ppl_ids = { person['id'] for person in people }
        self.assertNotIn('1', ppl_ids)
        self.assertIn('2', ppl_ids)

    def test_get_alter_result_collection_meta_info(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see alice (people/1)
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.name != 'alice',
        )
        # Make sure we get the lowest ids with a filter.
        res = test_app.get('/people?filter[id:lt]=3').json_body
        meta = res['meta']
        self.assertIn('people::1', meta['rejected']['objects'])

    def test_related_get_alter_result(self):
        '''
        'related' link should fetch only allowed related resource(s).
        '''
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['get'],
            ['alter_result', 'alter_related_result']
        )
        # Not allowed to see blog with title 'main: alice' (aka blogs/1)
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.title != 'main: alice',
        )
        r = test_app.get('/people/1/blogs').json_body
        data = r['data']
        ids = {o['id'] for o in data}
        self.assertIsInstance(data, list)
        self.assertNotIn('1', ids)

        # Not allowed to see alice (people/1)
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['get'],
            ['alter_result', 'alter_related_result'],
            lambda obj, *args, **kwargs: obj.object.name != 'alice',
        )
        r = test_app.get('/blogs/2/owner', status=403)

    def test_post_alterreq_collection(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['write'],
            ['alter_request']
        )
        # Not allowed to post the name "forbidden"
        def pfilter(obj, *args, **kwargs):
            return obj['attributes'].get('name') != 'forbidden'
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['post'],
            ['alter_request'],
            pfilter,
        )
        # Make sure we can't post the forbidden name.
        test_app.post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'forbidden'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )
        # Make sure we can post some other name.
        test_app.post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'allowed'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

    def test_post_alterreq_collection_with_rels(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['write'],
            ['alter_request']
        )
        def blogs_pfilter(obj, *args, **kwargs):
            return {'attributes': True, 'relationships': True}
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['post'],
            ['alter_request'],
            blogs_pfilter,
        )
        # /people: allow POST to all atts and to 3 relationships.
        def people_pfilter(obj, *args, **kwargs):
            return {
                'attributes': True,
                'relationships': {
                    'comments', 'articles_by_proxy', 'articles_by_assoc'
                }
            }
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['post'],
            ['alter_request'],
            people_pfilter,
        )
        # /comments: allow PATCH (required to set 'comments.author') on all
        # but comments/4.
        pj.view_classes[test_project.models.Comment].register_permission_filter(
            ['patch'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'4'}
        )
        # /articles_by_assoc: allow POST (required to add people/new to
        # 'articles_by_assoc.authors') on all but articles_by_assoc/11.
        pj.view_classes[test_project.models.ArticleByAssoc].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'11'}
        )
        pj.view_classes[test_project.models.ArticleByObj].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'10'}
        )
        person_in = {
            'data': {
                'type': 'people',
                'attributes': {
                    'name': 'post perms test'
                },
                'relationships': {
                    'posts': {
                        'data': [
                            {'type': 'posts', 'id': '20'},
                            {'type': 'posts', 'id': '21'}
                        ]
                    },
                    'comments': {
                        'data': [
                            {'type': 'comments', 'id': '4'},
                            {'type': 'comments', 'id': '5'},
                        ]
                    },
                    'articles_by_assoc': {
                        'data': [
                            {'type': 'articles_by_assoc', 'id': '10'},
                            {'type': 'articles_by_assoc', 'id': '11'},
                        ]
                    },
                    'articles_by_proxy': {
                        'data': [
                            {'type': 'articles_by_obj', 'id': '10'},
                            {'type': 'articles_by_obj', 'id': '11'},
                        ]
                    }
                }
            }
        }
        person_out = test_app.post_json(
            '/people',
            person_in,
            headers={'Content-Type': 'application/vnd.api+json'},
        ).json_body['data']
        rels = person_out['relationships']
        self.assertEqual(len(rels['posts']['data']),0)
        self.assertIn({'type': 'comments', 'id': '5'}, rels['comments']['data'])
        self.assertNotIn({'type': 'comments', 'id': '4'}, rels['comments']['data'])
        self.assertIn({'type': 'articles_by_assoc', 'id': '10'}, rels['articles_by_assoc']['data'])
        self.assertNotIn({'type': 'articles_by_assoc', 'id': '11'}, rels['articles_by_assoc']['data'])
        self.assertIn({'type': 'articles_by_obj', 'id': '11'}, rels['articles_by_proxy']['data'])
        self.assertNotIn({'type': 'articles_by_obj', 'id': '10'}, rels['articles_by_proxy']['data'])

        # Still need to test a to_one relationship. Posts has one of those.
        # Switching to " for quoting so that the following can be copy/pasted as
        # JSON in manual tests.
        post_json = {
            "data": {
                "type": "posts",
                "attributes": {
                    "title": "test"
                },
                "relationships": {
                    "author": {
                        "data": {"type": "people", "id": "10"}
                    },
                    "blog": {
                        "data": {"type": "blogs", "id": "10"}
                    }
                }
            }
        }
        # The Person permission filter defined above shouldn't allow us to POST
        # post_json because we don't have permission to POST to Person.posts.
        test_app.post_json(
            '/posts',
            post_json,
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409 # this should probably be a different status.
        )
        # Replace the permission filter for Person - we need to be able to
        # alter the Person.posts relationship.
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda *a, **kw: True,
        )
        post_out = test_app.post_json(
            '/posts',
            post_json,
            headers={'Content-Type': 'application/vnd.api+json'},
        )

    def test_post_alterreq_relationship(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['write'],
            ['alter_request']
        )
        def blogs_pfilter(obj, *args, **kwargs):
            if obj['id'] == '12':
                return False
            else:
                return {'attributes': True, 'relationships': True}
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['patch'],
            ['alter_request'],
            blogs_pfilter,
        )
        # /people: allow POST to all atts and to 3 relationships.
        def people_pfilter(obj, *args, **kwargs):
            if kwargs['permission_sought'] == 'delete' and obj['id'] == '20':
                return False
            if kwargs['permission_sought'] == 'post' and obj['id'] == '12':
                return False
            return {
                'attributes': True,
                'relationships': {
                    'blogs', 'articles_by_proxy', 'articles_by_assoc'
                }
            }
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['post', 'delete'],
            ['alter_request'],
            people_pfilter,
        )
        # /articles_by_assoc: allow POST (required to add people/new to
        # 'articles_by_assoc.authors') on all but articles_by_assoc/11.
        pj.view_classes[test_project.models.ArticleByAssoc].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'11'}
        )
        pj.view_classes[test_project.models.ArticleByObj].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'10'}
        )
        # ONETOMANY relationship.
        out = test_app.post_json(
            '/people/1/relationships/blogs',
            {
                'data': [
                    {'type': 'blogs', 'id': '10'},
                    {'type': 'blogs', 'id': '11'},
                    {'type': 'blogs', 'id': '12'},
                    {'type': 'blogs', 'id': '20'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        ).json_body
        # pprint.pprint(out)

        # Now fetch people/1 and see if the new blogs are there.
        p1 = test_app.get('/people/1').json_body['data']
        blogs = p1['relationships']['blogs']['data']
        # Should have left the original blogs in place.
        self.assertIn({'type': 'blogs', 'id': '1'}, blogs)
        # Should have added blogs/10 (previously no owner)
        self.assertIn({'type': 'blogs', 'id': '10'}, blogs)
        # Should have added blogs/11 (previously owned by 11)
        self.assertIn({'type': 'blogs', 'id': '11'}, blogs)
        # blogs/12 disallowed by blogs filter.
        self.assertNotIn({'type': 'blogs', 'id': '12'}, blogs)
        # blogs/20 disallowed by people filter on people/20.
        self.assertNotIn({'type': 'blogs', 'id': '20'}, blogs)

        # MANYTOMANY relationship.
        out = test_app.post_json(
            '/people/1/relationships/articles_by_assoc',
            {
                'data': [
                    {'type': 'articles_by_assoc', 'id': '10'},
                    {'type': 'articles_by_assoc', 'id': '11'},
                    {'type': 'articles_by_assoc', 'id': '12'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        ).json_body
        p1 = test_app.get('/people/1').json_body['data']
        articles = p1['relationships']['articles_by_assoc']['data']
        # Should have added articles_by_assoc/10
        self.assertIn({'type': 'articles_by_assoc', 'id': '10'}, articles)
        # articles_by_assoc/11 disallowed by articles_by_assoc filter.
        self.assertNotIn({'type': 'articles_by_assoc', 'id': '11'}, articles)
        # articles_by_assoc/12 disallowed by people filter.
        # self.assertNotIn({'type': 'articles_by_assoc', 'id': '12'}, articles)

    def test_patch_alterreq_item_with_rels(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['write'],
            ['alter_request']
        )
        def blogs_pfilter(obj, **kwargs):
            return {'attributes': True, 'relationships': True}
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['post'],
            ['alter_request'],
            blogs_pfilter,
        )
        # /people: allow PATCH to all atts and to 3 relationships.
        def people_pfilter(obj, **kwargs):
            return {
                'attributes': True,
                'relationships': {
                    'comments', 'articles_by_proxy', 'articles_by_assoc'
                }
            }
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['patch'],
            ['alter_request'],
            people_pfilter,
        )
        # /comments: allow PATCH (required to set 'comments.author') on all
        # but comments/4.
        def comments_pfilter(obj, **kwargs):
            if obj['id'] == '4' and obj['relationships']['author']['data']['id'] == '1':
                # We're not allowing people/1 to be the author of comments/4 for
                # some reason.
                return False
            return True
        pj.view_classes[test_project.models.Comment].register_permission_filter(
            ['patch'],
            ['alter_request'],
            comments_pfilter
        )
        # /articles_by_assoc: allow POST (required to add people/new to
        # 'articles_by_assoc.authors') on all but articles_by_assoc/11.
        pj.view_classes[test_project.models.ArticleByAssoc].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'11'}
        )
        pj.view_classes[test_project.models.ArticleByObj].register_permission_filter(
            ['post'],
            ['alter_request'],
            lambda obj, *args, **kwargs: obj['id'] not in {'11'}
        )
        person_in = {
            'data': {
                'type': 'people',
                'id': '1',
                'attributes': {
                    'name': 'post perms test'
                },
                'relationships': {
                    'posts': {
                        'data': [
                            {'type': 'posts', 'id': '1'},
                            {'type': 'posts', 'id': '2'},
                            {'type': 'posts', 'id': '3'},
                            {'type': 'posts', 'id': '20'},
                        ]
                    },
                    'comments': {
                        'data': [
                            {'type': 'comments', 'id': '1'},
                            {'type': 'comments', 'id': '4'},
                            {'type': 'comments', 'id': '5'},
                        ]
                    },
                    'articles_by_assoc': {
                        'data': [
                            {'type': 'articles_by_assoc', 'id': '10'},
                            {'type': 'articles_by_assoc', 'id': '11'},
                        ]
                    },
                    'articles_by_proxy': {
                        'data': [
                            {'type': 'articles_by_obj', 'id': '1'},
                            {'type': 'articles_by_obj', 'id': '10'},
                            {'type': 'articles_by_obj', 'id': '11'},
                        ]
                    }
                }
            }
        }
        test_app.patch_json(
            '/people/1',
            person_in,
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        person_out = test_app.get('/people/1').json_body['data']
        rels = person_out['relationships']
        # pprint.pprint(rels['posts']['data'])
        # pprint.pprint(rels['comments']['data'])
        # pprint.pprint(rels['articles_by_assoc']['data'])
        # pprint.pprint(rels['articles_by_proxy']['data'])

        # Still need to test a to_one relationship. Blogs has one of those.
        def blogs_pfilter(obj, **kwargs):
            if obj['id'] == '13':
                # Not allowed to change blogs/13 at all.
                return False
            if obj['id'] == '10':
                # Not allowed to set owner of blogs/10 to people/13
                if obj['relationships']['owner']['data'].get('id') == '13':
                    # print('people/13 not allowed as owner of 10')
                    return {'attributes': True, 'relationships': {'posts'}}
            if obj['id'] == '11':
                # Not allowed to set owner of blogs/11 to None.
                if obj['relationships']['owner']['data'] is None:
                    return {'attributes': True, 'relationships': {'posts'}}
            return True
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['patch'],
            ['alter_request'],
            blogs_pfilter
        )
        blog = {
            'data': {
                'type': 'blogs', 'id': None,
                'relationships': {
                    'owner': {
                        'data': None
                    }
                }
            }
        }
        blog_owner = blog['data']['relationships']['owner']
        # /blogs/10 is owned by no-one. Change owner to people/11. Should
        # Have permission for this one.
        ppl11 = make_ri('people', '11')
        blog['data']['id'] = '10'
        blog_owner['data'] = ppl11
        self.assertNotEqual(
            test_app.get('/blogs/10').json_body['data']['relationships']['owner']['data'],
            ppl11
        )
        test_app.patch_json(
            '/blogs/10',
            blog,
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        self.assertEqual(
            test_app.get('/blogs/10').json_body['data']['relationships']['owner']['data'],
            ppl11
        )
        # Not allowed to set blogs/10.owner to people/13 though.
        ppl13 = make_ri('people', '13')
        blog_owner['data'] = ppl13
        test_app.patch_json(
            '/blogs/10',
            blog,
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        self.assertNotEqual(
            test_app.get('/blogs/10').json_body['data']['relationships']['owner']['data'],
            ppl13
        )

        # Should be able to switch ownership of blogs/11 to people/12
        ppl12 = make_ri('people', '12')
        blog['data']['id'] = '11'
        blog_owner['data'] = ppl12
        test_app.patch_json(
            '/blogs/11',
            blog,
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        self.assertEqual(
            test_app.get('/blogs/11').json_body['data']['relationships']['owner']['data'],
            ppl12
        )
        # but not to None
        blog_owner['data'] = None
        test_app.patch_json(
            '/blogs/11',
            blog,
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        self.assertNotEqual(
            test_app.get('/blogs/11').json_body['data']['relationships']['owner']['data'],
            None
        )

        # Shouldn't be allowed to patch blogs/13 at all.
        blog['data']['id'] = '13'
        test_app.patch_json(
            '/blogs/13',
            blog,
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )

    def test_patch_alterreq_relationships(self):
        test_app = self.test_app({})
        pj = test_app._pj_app.pj
        pj.enable_permission_handlers(
            ['write'],
            ['alter_request']
        )
        def people_pfilter(obj, **kwargs):
            if obj['id'] == '1':
                return False
            if obj['id'] == '2':
                return {'attributes': True, 'relationships': False}
            return True
        pj.view_classes[test_project.models.Person].register_permission_filter(
            ['patch'],
            ['alter_request'],
            people_pfilter
        )
        def blogs_pfilter(obj, **kwargs):
            if obj['id'] == '10':
                # Not allowed to change blogs/10 at all.
                return False
            if obj['id'] == '11':
                # Not allowed to set owner of blogs/11 to None.
                if obj['relationships']['owner']['data'] is None:
                    return {'attributes': True, 'relationships': {'posts'}}
            if obj['id'] == '12':
                # Not allowed to set owner of blogs/12 to people/11
                if obj['relationships']['owner']['data'].get('id') == '11':
                    return {'attributes': True, 'relationships': {'posts'}}
            return True
        pj.view_classes[test_project.models.Blog].register_permission_filter(
            ['patch'],
            ['alter_request'],
            blogs_pfilter
        )

        # ONETOMANY tests
        # No permission to patch people/1 at all.
        test_app.patch_json(
            '/people/1/relationships/blogs',
            {
                'data': [
                    {'type': 'blogs', 'id': '10'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )
        # No permission to patch relationship of people/2.
        test_app.patch_json(
            '/people/2/relationships/blogs',
            {
                'data': [
                    {'type': 'blogs', 'id': '10'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )

        test_app.patch_json(
            '/people/11/relationships/blogs',
            {
                'data': [
                    {'type': 'blogs', 'id': '10'},
                    {'type': 'blogs', 'id': '12'},
                    {'type': 'blogs', 'id': '13'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        blog_ids = [
            b['id'] for b in
            test_app.get('/people/11').json_body['data']['relationships']['blogs']['data']
        ]
        # No permission to blogs/10
        self.assertNotIn('10', blog_ids)
        # No permission to set blogs/11.owner = people/11
        self.assertNotIn('12', blog_ids)
        # No permission to set blogs/11.owner = None
        self.assertIn('11', blog_ids)
        # Allowed to add blogs/13 :)
        self.assertIn('13', blog_ids)

        # MANYTOMANY tests
        def articles_by_assoc_pfilter(obj, **kwargs):
            if obj['id'] == '10':
                # Not allowed to change articles_by_assoc/10 at all.
                return False
            if obj['id'] == '12':
                # Not allowed to alter author of articles_by_assoc/12
                return {'attributes': True, 'relationships': False}
            return True
        pj.view_classes[test_project.models.ArticleByAssoc].register_permission_filter(
            ['post', 'delete'],
            ['alter_request'],
            articles_by_assoc_pfilter
        )
        test_app.patch_json(
            '/people/12/relationships/articles_by_assoc',
            {
                'data': [
                    {'type': 'articles_by_assoc', 'id': '10'},
                    {'type': 'articles_by_assoc', 'id': '1'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        article_ids = [
            b['id'] for b in
            test_app.get('/people/12').json_body['data']['relationships']['articles_by_assoc']['data']
        ]
        # No permission to add 10
        self.assertNotIn('10', article_ids)
        # Permission to remove 13
        self.assertNotIn('13', article_ids)
        # No permission to remove 12
        self.assertIn('12', article_ids)
        # Permission to add 1
        self.assertIn('1', article_ids)

class TestRelationships(DBTestBase):
    '''Test functioning of relationsips.
    '''
    # Test data convention:
    #
    # src:10 -> undef or []
    # src:11 -> tgt:11 or [tgt:11]
    # src:12 -> [tgt:12, tgt:13]

    ###############################################
    # Relationship GET tests.
    ###############################################

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_object(self, src, tgt, comment):
        '''Relationships key should be object with a defined structure.

        The value of the relationships key MUST be an object (a “relationships
        object”). Members of the relationships object (“relationships”)
        represent references from the resource object in which it’s defined to
        other resource objects.

        Relationships links object should have 'self' and 'related' links.
        '''
        # Fetch item 1 from the collection
        r = self.test_app().get('/{}/1'.format(src.collection))
        item = r.json['data']
        # Should have relationships key
        self.assertIn('relationships', item)
        rels = item['relationships']
        # The named relationship should exist.
        self.assertIn(src.rel, rels)

        # Check the structure of the relationship object.
        obj = rels[src.rel]
        self.assertIn('links', obj)
        self.assertIn('self', obj['links'])
        self.assertTrue(obj['links']['self'].endswith(
            '{}/1/relationships/{}'.format(src.collection, src.rel)
        ))
        self.assertIn('related', obj['links'])
        self.assertTrue(obj['links']['related'].endswith(
            '{}/1/{}'.format(src.collection, src.rel)
        ))
        self.assertIn('data', obj)
        if tgt.many:
            self.assertIsInstance(obj['data'], list)
            self.assertIn('type', obj['data'][0])
            self.assertIn('id', obj['data'][0])
        else:
            self.assertIsInstance(obj['data'], dict)
            self.assertIn('type', obj['data'])
            self.assertIn('id', obj['data'])

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_related_get(self, src, tgt, comment):
        ''''related' link should fetch related resource(s).

        If present, a related resource link MUST reference a valid URL, even if
        the relationship isn’t currently associated with any target resources.
        '''
        # Fetch item 1 from the collection
        r = self.test_app().get('/{}/1'.format(src.collection))
        item = r.json['data']

        # Fetch the related url.
        url = item['relationships'][src.rel]['links']['related']
        data = self.test_app().get(url).json['data']

        # Check that the returned data is of the expected type.
        if tgt.many:
            self.assertIsInstance(data, list)
            for related_item in data:
                self.assertEqual(related_item['type'], tgt.collection)
        else:
            self.assertIsInstance(data, dict)
            self.assertEqual(data['type'], tgt.collection)

    def test_rels_related_get_no_relationship(self):
        """Should fail to get an invalid relationship."""
        self.test_app().get('/blogs/1/no_such_relationship',
                            status=400,
                           )

    def test_rels_related_get_no_object(self):
        """Should fail if 'parent' doesn't exist."""
        self.test_app().get('/blogs/99999/owner',
                            status=400,
                           )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_resource_linkage(self, src, tgt, comment):
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
        # Test data convention:
        #
        # src:10 -> None or []
        # src:11 -> tgt:11 or [tgt:11]
        # src:12 -> [tgt:12, tgt:13]

        # We always need items 10 and 11 from the source collection.
        reldata_with_none = self.test_app().get(
            '/{}/10'.format(src.collection)
        ).json['data']['relationships'][src.rel]['data']
        reldata_with_one = self.test_app().get(
            '/{}/11'.format(src.collection)
        ).json['data']['relationships'][src.rel]['data']

        if tgt.many:
            # Empty to_many relationship should hold [].
            self.assertEqual(reldata_with_none, [])

            # Should be an array with one item.
            self.assertEqual(
                reldata_with_one[0],
                {'type': tgt.collection, 'id': '11'}
            )

            # We need item 12 for a to_many relationship.
            # Note that we sort the list of related items so that they are in a
            # known order for later testing.
            reldata_with_two = sorted(
                self.test_app().get(
                    '/{}/12'.format(src.collection)
                ).json['data']['relationships'][src.rel]['data'],
                key=lambda item: item['id']
            )
            # Should be an array with two items.
            self.assertEqual(
                reldata_with_two[0], {'type': tgt.collection, 'id': '12'}
            )
            self.assertEqual(
                reldata_with_two[1], {'type': tgt.collection, 'id': '13'}
            )
        else:
            # Empty to_one relationship should hold None.
            self.assertIsNone(reldata_with_none)
            # Otherwise a single item {type: tgt_type, id: 11}.
            self.assertEqual(reldata_with_one, {'type': tgt.collection, 'id': '11'})

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_fetch_relationship_link(self, src, tgt, comment):
        '''relationships links should return linkage information.

        A server MUST support fetching relationship data for every relationship
        URL provided as a self link as part of a relationship’s links object

        The primary data in the response document MUST match the appropriate
        value for resource linkage, as described above for relationship objects.

        If [a to-one] relationship is empty, then a GET request to the
        [relationship] URL would return:

            "data": null

        If [a to-many] relationship is empty, then a GET request to the
        [relationship] URL would return:

            "data": []
        '''
        for item_id in ['10', '11', '12']:
            url = self.test_app().get(
                '/{}/{}'.format(src.collection, item_id)
            ).json['data']['relationships'][src.rel]['links']['self']
            reldata = self.test_app().get(url).json['data']
            if tgt.many:
                if item_id == '10':
                    self.assertEqual(reldata, [])
                elif item_id == '11':
                    self.assertEqual(reldata[0]['type'], tgt.collection)
                    self.assertEqual(reldata[0]['id'], '11')
                else:
                    reldata.sort(key=lambda item: item['id'])
                    self.assertEqual(reldata[0]['type'], tgt.collection)
                    self.assertEqual(reldata[0]['id'], '12')
                    self.assertEqual(reldata[1]['type'], tgt.collection)
                    self.assertEqual(reldata[1]['id'], '13')
            else:
                if item_id == '10':
                    self.assertIsNone(reldata)
                elif item_id == '11':
                    self.assertEqual(reldata['type'], tgt.collection)
                    self.assertEqual(reldata['id'], '11')
                else:
                    continue

    def test_rels_fetch_not_found_relationship(self):
        '''Should 404 when fetching a relationship that does not exist.

        A server MUST return 404 Not Found when processing a request to fetch a
        relationship link URL that does not exist.
        '''
        # Try to get the author of a non existent post.
        r = self.test_app().get('/posts/1000/relationships/author', status=404)
        # Try to get data about a non existing relationships
        self.test_app().get('/posts/1/relationships/no_such_relationship',
            status=404)

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_filter(self, src, tgt, comment):
        '''
        '''
        for filter in tgt.filters:
            json = self.test_app().get(
                '/{}?filter[{}.{}:{}]={}&include={}'.format(
                    src.collection,
                    src.rel,
                    filter.att,
                    filter.op,
                    filter.value,
                    src.rel,
                )
            ).json
            #included = json['included']
            included = {
                (inc['type'], inc['id']): inc for inc in json['included']
            }
            # There should be at least one match.
            self.assertGreater(len(included), 0)
            items = json['data']
            # For each returned item, there should be at least one related
            # item which matches the filter.
            for item in items:
                res_ids = item['relationships'][src.rel]['data']
                self.assertIsNotNone(res_ids)
                if not tgt.many:
                    res_ids = [res_ids]
                found_match = False
                for res_id in res_ids:
                    relitem = included[(res_id['type'], res_id['id'])]
                    found_match = self.evaluate_filter(
                        relitem['attributes'][filter.att],
                        filter.op,
                        filter.value
                    )
                    if found_match:
                        break
                self.assertTrue(found_match)


    ###############################################
    # Relationship POST tests.
    ###############################################

    def test_rels_post_no_such_relationship(self):
        """Should fail to create an invalid relationship."""

        created_id = self.test_app().post_json(
            '/blogs',
            {
                'data': {
                    'type': 'blogs',
                    'attributes': {
                        'title': 'test'
                    },
                    'relationships': {
                        'no_such_relationship': {
                            'data': {'type': 'people', 'id': '1'}
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )

    def test_rels_post_relationship_no_data(self):
        "Relationships mentioned in POSTs must have data."
        created_id = self.test_app(
            options = {
                'pyramid_jsonapi.schema_validation': 'false'
            }
        ).post_json(
        '/blogs',
        {
            'data': {
                'type': 'blogs',
                'attributes': {
                    'title': 'test'
                },
                'relationships': {
                    'owner': {}
                }
            }
        },
        headers={'Content-Type': 'application/vnd.api+json'},
        status=400
    )

    def test_rels_post_relationship_no_id(self):
        "Relationship linkage in POST requests must have id."
        created_id = self.test_app(
            options = {
                'pyramid_jsonapi.schema_validation': 'false'
            }
        ).post_json(
        '/blogs',
        {
            'data': {
                'type': 'blogs',
                'attributes': {
                    'title': 'test'
                },
                'relationships': {
                    'owner': {
                        'data': {'type': 'people'}
                    }
                }
            }
        },
        headers={'Content-Type': 'application/vnd.api+json'},
        status=400
    )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_post_to_relationships(self, src, tgt, comment):
        '''Should add items to a TOMANY relationship; 403 Error for TOONE.

        If a client makes a POST request to a URL from a relationship link, the
        server MUST add the specified members to the relationship unless they
        are already present. If a given type and id is already in the
        relationship, the server MUST NOT add it again.
        '''
        if not tgt.many:
            # Cannot POST to TOONE relationship. 403 Error.
            self.test_app(
                options = {
                    'pyramid_jsonapi.schema_validation': 'false'
                    }
                ).post_json(
                    '/{}/10/relationships/{}'.format(src.collection, src.rel),
                    {'type': tgt.collection, 'id': '11'},
                    headers={'Content-Type': 'application/vnd.api+json'},
                    status=403
                )
            return

        # Add related items 12 and 13 to item 10 (has no related items).
        self.test_app().post_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    { 'type': tgt.collection, 'id': '12'},
                    { 'type': tgt.collection, 'id': '13'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Make sure they are there.
        rel_ids = {
            rel_item['id'] for rel_item in
                self.test_app().get(
                    '/{}/10/relationships/{}'.format(src.collection, src.rel)
                ).json['data']
        }
        self.assertEqual(rel_ids, {'12', '13'})
        # Make sure adding relitem:12 again doesn't result in two relitem:12s
        self.test_app().post_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    { 'type': tgt.collection, 'id': '12'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        rel_ids = [
            rel_item['id'] for rel_item in
                self.test_app().get(
                    '/{}/10/relationships/{}'.format(src.collection, src.rel)
                ).json['data']
        ]
        self.assertEqual(sorted(rel_ids), ['12', '13'])
        # Make sure adding relitem:11 adds to the list, rather than replacing
        # it.
        self.test_app().post_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    { 'type': tgt.collection, 'id': '11'},
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        rel_ids = [
            rel_item['id'] for rel_item in
                self.test_app().get(
                    '/{}/10/relationships/{}'.format(src.collection, src.rel)
                ).json['data']
        ]
        self.assertEqual(sorted(rel_ids), ['11', '12', '13'])

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_post_item_with_related(self, src, tgt, comment):
        '''Should add a new item with linkage to related resources.

        If a relationship is provided in the relationships member of the
        resource object, its value MUST be a relationship object with a data
        member. The value of this key represents the linkage the new resource is
        to have.
        '''
        # Add a new item related to relitem:12 and possibly relitem:13
        reldata = {'type': tgt.collection, 'id': '12'}
        if tgt.many:
            reldata = [ reldata, {'type': tgt.collection, 'id': '13'} ]
        item_id = self.test_app().post_json(
            '/{}'.format(src.collection),
            {
                'data': {
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': reldata
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']['id']

        # GET it back and check that relationship linkage is correct.
        item = self.test_app().get(
            '/{}/{}'.format(src.collection, item_id)
        ).json['data']
        if tgt.many:
            specified_related_ids = {'12', '13'}
            found_related_ids = {
                thing['id'] for thing in item['relationships'][src.rel]['data']
            }
            self.assertEqual(specified_related_ids, found_related_ids)
        else:
            self.assertEqual(item['relationships'][src.rel]['data']['id'], '12')

        # Now attempt to add another item with malformed requests.
        incorrect_type_data = { 'type': 'frogs', 'id': '12' }
        no_id_data = { 'type': tgt.collection, 'id_typo': '12'}
        # No data element in rel.
        self.test_app().post_json(
            '/{}'.format(src.collection),
            {
                'data': {
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'meta': 'should fail'
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )
        if tgt.many:
            incorrect_type_data = [ incorrect_type_data ]
            no_id_data = [ no_id_data ]
            # Not an array.
            self.test_app().post_json(
                '/{}'.format(src.collection),
                {
                    'data': {
                        'type': src.collection,
                        'relationships': {
                            src.rel: {
                                'data': { 'type': tgt.collection, 'id': '12'}
                            }
                        }
                    }
                },
                headers={'Content-Type': 'application/vnd.api+json'},
                status=400
            )
        else:
            # Data is an array of identifiers when it should be just one.
            self.test_app().post_json(
                '/{}'.format(src.collection),
                {
                    'data': {
                        'type': src.collection,
                        'relationships': {
                            src.rel: {
                                'data': [
                                    { 'type': tgt.collection, 'id': '12'}
                                ]
                            }
                        }
                    }
                },
                headers={'Content-Type': 'application/vnd.api+json'},
                status=400
            )

        # Data malformed (not a resource identifier or array of them).
        self.test_app().post_json(
            '/{}'.format(src.collection),
            {
                'data': {
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': 'splat'
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )
        # Item with incorrect type.
        self.test_app().post_json(
            '/{}'.format(src.collection),
            {
                'data': {
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': incorrect_type_data
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )
        # Item with no id.
        self.test_app().post_json(
            '/{}'.format(src.collection),
            {
                'data': {
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': no_id_data
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_rels_post_relationships_nonexistent_relationship(self):
        '''Should return 404 error (relationship not found).
        '''
        # Try to add people/1 to no_such_relationship.
        self.test_app().post_json(
            '/articles_by_assoc/2/relationships/no_such_relationship',
            {
                'data': [
                    { 'type': 'people', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_post_relationships_nonexistent_item(self, src, tgt, comment):
        '''Should return HTTPFailedDependency (424).
        '''
        # Try to add tgt/99999 (doesn't exist) to src.rel
        reldata = { 'type': tgt.collection, 'id': '99999'}
        status = 403
        if tgt.many:
            reldata = [ reldata ]
            status = 424
        self.test_app().post_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': reldata
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=status
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_spec_post_relationships_invalid_id(self, src, tgt, comments):
        '''Should return HTTPBadRequest.
        '''
        if not tgt.many:
            return
        # Try to add item/splat to rel..
        self.test_app().post_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    { 'type': tgt.collection, 'id': 'splat'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_rels_post_relationships_integrity_error(self):
        '''Should return HTTPFailedDependency.
        '''
        # Try to add blog/1 to people/3 (db constraint precludes this)
        self.test_app().post_json(
            '/people/3/relationships/blogs',
            {
                'data': [
                    { 'type': 'blogs', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=424
        )

    ###############################################
    # Relationship PATCH tests.
    ###############################################

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_patch_resources_relationships(self, src, tgt, comment):
        '''Should replace src.rel with new contents.

        Any or all of a resource’s relationships MAY be included in the resource
        object included in a PATCH request.

        If a request does not include all of the relationships for a resource,
        the server MUST interpret the missing relationships as if they were
        included with their current values. It MUST NOT interpret them as null
        or empty values.

        If a relationship is provided in the relationships member of a resource
        object in a PATCH request, its value MUST be a relationship object with
        a data member. The relationship’s value will be replaced with the value
        specified in this member.
        '''
        reldata = {'type': tgt.collection, 'id': '12'}
        if tgt.many:
            reldata = [ reldata, {'type': tgt.collection, 'id': '13'} ]

        # PATCH src/10/rels/rel to be reldata
        self.test_app().patch_json(
            '/{}/10'.format(src.collection),
            {
                'data': {
                    'id': '10',
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': reldata
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )

        # Check that src.rel has the correct linkage.
        src_item = self.test_app().get('/{}/10'.format(src.collection)).json['data']
        if tgt.many:
            for related_item in src_item['relationships'][src.rel]['data']:
                self.assertEqual(related_item['type'], tgt.collection)
                self.assertIn(related_item['id'], {'12', '13'})
        else:
            self.assertEqual(src_item['relationships'][src.rel]['data'], reldata)

        # Now try PATCHing the relationship back to empty
        if tgt.many:
            reldata = []
        else:
            reldata = None
        self.test_app().patch_json(
            '/{}/10'.format(src.collection),
            {
                'data': {
                    'id': '10',
                    'type': src.collection,
                    'relationships': {
                        src.rel: {
                            'data': reldata
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        src_item = self.test_app().get('/{}/10'.format(src.collection)).json['data']
        self.assertEqual(src_item['relationships'][src.rel]['data'], reldata)

        # MUST be a relationship object with a data member
        # Try without a data member...
        self.test_app().patch_json(
            '/{}/10'.format(src.collection),
            {
                'data': {
                    'id': '10',
                    'type': src.collection,
                    'relationships': {
                        src.rel: reldata
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_patch_relationships(self, src, tgt, comment):
        '''Should update a relationship.

        A server MUST respond to PATCH requests to a URL from a to-one
        relationship link as described below.

        The PATCH request MUST include a top-level member named data containing
        one of:

            * a resource identifier object corresponding to the new related
              resource.
            * null, to remove the relationship.

        If a client makes a PATCH request to a URL from a to-many relationship
        link, the server MUST either completely replace every member of the
        relationship, return an appropriate error response if some resources can
        not be found or accessed, or return a 403 Forbidden response if complete
        replacement is not allowed by the server.
        '''
        if tgt.many:
            new_reldata = [
                { 'type': tgt.collection, 'id': '12'},
                { 'type': tgt.collection, 'id': '13'}
            ]
            new_empty = []
        else:
            new_reldata = { 'type': tgt.collection, 'id': '12'}
            new_empty = None
        # src:11 should be related to tgt:11. Update the relationship.
        self.test_app().patch_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': new_reldata
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Check that the change went through
        fetched_reldata = self.test_app().get(
            '/{}/10/relationships/{}'.format(src.collection, src.rel)
        ).json['data']
        if tgt.many:
            expected_length = 2
            expected_ids = {'12', '13'}
        else:
            # Wrap to_one results in an array to make the following code DRY.
            fetched_reldata = [ fetched_reldata ]
            expected_length = 1
            expected_ids = {'12'}
        fetched_reldata.sort(key=lambda item: item['id'])
        self.assertEqual(len(fetched_reldata), expected_length)
        for relitem in fetched_reldata:
            self.assertEqual(relitem['type'], tgt.collection)
            self.assertIn(relitem['id'], expected_ids)

        # Update the relationship to be empty.
        self.test_app().patch_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': new_empty
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Check that it's empty.
        self.assertEqual(
            self.test_app().get(
                '/{}/10/relationships/{}'.format(src.collection, src.rel)
            ).json['data'],
            new_empty
        )

    def test_rels_patch_relationships_nonexistent_relationship(self):
        '''Should return 404 error (relationship not found).
        '''
        # Try set people/1 on no_such_relationship.
        self.test_app().patch_json(
            '/articles_by_assoc/2/relationships/no_such_relationship',
            {
                'data': [
                    { 'type': 'people', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_patch_relationships_nonexistent_item(self, src, tgt, comment):
        '''Should return HTTPFailedDependency.
        '''
        reldata = { 'type': tgt.collection, 'id': '99999' }
        if tgt.many:
            reldata = [ reldata ]
        self.test_app().patch_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': reldata
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=424
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_patch_relationships_invalid_id(self, src, tgt, comment):
        '''Should return HTTPBadRequest.
        '''
        reldata = { 'type': tgt.collection, 'id': 'splat' }
        if tgt.many:
            reldata = [ reldata ]
        self.test_app().patch_json(
            '/{}/10/relationships/{}'.format(src.collection, src.rel),
            {
                'data': reldata
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_rels_patch_relationships_integrity_error(self):
        '''Should return HTTPFailedDependency.
        '''
        # Try to add blog/1 to people/3 (db constraint precludes this)
        self.test_app().patch_json(
            '/people/3/relationships/blogs',
            {
                'data': [
                    { 'type': 'blogs', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=424
        )
        # and the other way round
        self.test_app().patch_json(
            '/blogs/1/relationships/owner',
            {
                'data': { 'type': 'people', 'id': '3'}
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=424
        )

    ###############################################
    # Relationship DELETE tests.
    ###############################################

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_delete_relationships(self, src, tgt, comment):
        '''Should remove items from relationship.

        If the client makes a DELETE request to a URL from a relationship link
        the server MUST delete the specified members from the relationship or
        return a 403 Forbidden response. If all of the specified resources are
        able to be removed from, or are already missing from, the relationship
        then the server MUST return a successful response
        '''
        if not tgt.many:
            # DELETEing from a to_one relationship is not allowed.
            self.test_app().delete(
                '/{}/11/relationships/{}'.format(src.collection, src.rel),
                status=403
            )
            return

        # Attempt to delete tgt:13 from src:12
        self.test_app().delete_json(
            '/{}/12/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    {'type': tgt.collection, 'id': '13'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Test that tgt:13 is no longer in the relationship.
        self.assertEqual(
            {'12'},
            {
                item['id'] for item in
                self.test_app().get(
                    '/{}/12/relationships/{}'.format(src.collection, src.rel)
                ).json['data']
            }
        )
        # Try to DELETE tgt:13 from relationship again. Should return success.
        self.test_app().delete_json(
            '/{}/12/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    {'type': tgt.collection, 'id': '13'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        self.assertEqual(
            {'12'},
            {
                item['id'] for item in
                self.test_app().get(
                    '/{}/12/relationships/{}'.format(src.collection, src.rel)
                ).json['data']
            }
        )

    def test_rels_delete_relationships_nonexistent_relationship(self):
        '''Should return 404 error (relationship not found).
        '''
        # Delete people/1 from no_such_relationship.
        self.test_app().delete_json(
            '/articles_by_assoc/2/relationships/no_such_relationship',
            {
                'data': [
                    { 'type': 'people', 'id': '1'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_delete_relationships_nonexistent_item(self, src, tgt, comment):
        '''Should return HTTPFailedDependency.
        '''
        if not tgt.many:
            return
        self.test_app().delete_json(
            '/{}/11/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [ { 'type': tgt.collection, 'id': '99999' } ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=424
        )

    @parameterized.expand(rel_infos, doc_func=rels_doc_func)
    def test_rels_delete_relationships_invalid_id(self, src, tgt, comment):
        '''Should return HTTPBadRequest.
        '''
        if not tgt.many:
            return
        # Try to delete tgt:splat from src:11.
        self.test_app().delete_json(
            '/{}/11/relationships/{}'.format(src.collection, src.rel),
            {
                'data': [
                    { 'type': tgt.collection, 'id': 'splat'}
                ]
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_adjacancy_list(self):
        '''Should correctly identify parent and children for TreeNode.
        '''
        top = self.test_app().get('/treenodes/1').json
        top_1 = self.test_app().get('/treenodes/2').json
        # top should have no parent.
        self.assertIsNone(top['data']['relationships']['parent']['data'])
        # top should have multiple children.
        self.assertIsInstance(top['data']['relationships']['children']['data'], list)
        # top_1 should have top as a parent.
        self.assertEqual(
            top_1['data']['relationships']['parent']['data'],
            {'type': 'treenodes', 'id': '1'}
        )
        # top_1 should have 2 children.
        self.assertIsInstance(top_1['data']['relationships']['children']['data'], list)
        self.assertEqual(len(top_1['data']['relationships']['children']['data']), 2)


class TestSpec(DBTestBase):
    '''Test compliance against jsonapi spec.

    http://jsonapi.org/format/
    '''

    ###############################################
    # GET tests.
    ###############################################

    def test_spec_server_content_type(self):
        '''Response should have correct content type.

        Servers MUST send all JSON API data in response documents with the
        header Content-Type: application/vnd.api+json without any media type
        parameters.
        '''
        # Fetch a representative page

        r = self.test_app().get('/people')
        self.assertEqual(r.content_type, 'application/vnd.api+json')

    def test_spec_incorrect_client_content_type(self):
        '''Server should return error if we send media type parameters.

        Servers MUST respond with a 415 Unsupported Media Type status code if a
        request specifies the header Content-Type: application/vnd.api+json with
        any media type parameters.
        '''
        r = self.test_app().get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )

    def test_spec_accept_not_acceptable(self):
        '''Server should respond with 406 if all jsonapi media types have parameters.

        Servers MUST respond with a 406 Not Acceptable status code if a
        request's Accept header contains the JSON API media type and all
        instances of that media type are modified with media type parameters.
        '''
        # Should work with correct accepts header.
        r = self.test_app().get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json' },
        )
        # 406 with one incorrect type.
        r = self.test_app().get(
            '/people',
            headers={ 'Accept': 'application/vnd.api+json; param=val' },
            status=406,
        )
        # 406 with more than one type but none without params.
        r = self.test_app().get(
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

            * data: the document's “primary data”
            * errors: an array of error objects
            * meta: a meta object that contains non-standard meta-information.
        '''
        # Should be object with data member.
        r = self.test_app().get('/people')
        self.assertIn('data', r.json)
        # Should also have a meta member.
        self.assertIn('meta', r.json)

        # Should be object with an array of errors.
        r = self.test_app().get(
            '/people',
            headers={ 'Content-Type': 'application/vnd.api+json; param=val' },
            status=415,
        )
        self.assertIn('errors', r.json)
        self.assertIsInstance(r.json['errors'], list)

    def test_spec_get_no_such_item(self):
        '''Should fail to get non-existent comments/99999

        A server MUST respond with 404 Not Found when processing a request
        to fetch a single resource that does not exist

        '''

        # Get comments/99999
        self.test_app().get('/comments/99999', status=404)

    def test_spec_get_invalid_item(self):
        '''Should fail to get invalid item comments/cat

        A server MUST respond with 404 Not Found when processing a request
        to fetch a single resource that does not exist

        '''

        # Get comments/cat
        self.test_app().get('/comments/cat', status=404)

    def test_spec_get_primary_data_empty(self):
        '''Should return an empty list of results.

        Primary data MUST be either:

            * ...or an empty array ([])

        A logical collection of resources MUST be represented as an array, even
        if it... is empty.
        '''
        r = self.test_app().get('/people?filter[name:eq]=doesnotexist')
        self.assertEqual(len(r.json['data']), 0)

    def test_spec_get_primary_data_array(self):
        '''Should return an array of resource objects.

        Primary data MUST be either:

            * an array of resource objects, an array of resource identifier
            objects, or an empty array ([]), for requests that target resource
            collections
        '''
        # Data should be an array of person resource objects or identifiers.
        r = self.test_app().get('/people')
        self.assertIn('data', r.json)
        self.assertIsInstance(r.json['data'], list)
        item = r.json['data'][0]


    def test_spec_get_primary_data_array_of_one(self):
        '''Should return an array of one resource object.

        A logical collection of resources MUST be represented as an array, even
        if it only contains one item...
        '''
        r = self.test_app().get('/people?page[limit]=1')
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
        r = self.test_app().get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']
        # Now get alice object.
        r = self.test_app().get('/people/' + alice_id)
        alice = r.json['data']
        self.assertEqual(alice['attributes']['name'], 'alice')

    def test_spec_resource_object_must(self):
        '''Resource object should have at least id and type.

        A resource object MUST contain at least the following top-level members:
            * id
            * type

        The values of the id and type members MUST be strings.
        '''
        r = self.test_app().get('/people?page[limit]=1')
        item = r.json['data'][0]
        # item must have at least a type and id.
        self.assertEqual(item['type'], 'people')
        self.assertIn('id', item)
        self.assertIsInstance(item['type'], str)
        self.assertIsInstance(item['id'], str)

    def test_spec_resource_object_should(self):
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
        r = self.test_app().get('/people?page[limit]=1')
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
        r = self.test_app().get('/people?filter[name:eq]=alice')
        item = r.json['data'][0]
        self.assertEqual(item['attributes']['name'], 'alice')
        alice_id = item['id']

        # Search for alice by id. We should get one result whose name is alice.
        r = self.test_app().get('/people?filter[id:eq]={}'.format(alice_id))
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
        r = self.test_app().get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check attributes.
        self.assertIn('attributes', item)
        atts = item['attributes']
        self.assertIn('title', atts)
        self.assertIn('content', atts)
        self.assertIn('published_at', atts)

    def test_spec_no_foreign_keys(self):
        '''No forreign keys in attributes.

        Although has-one foreign keys (e.g. author_id) are often stored
        internally alongside other information to be represented in a resource
        object, these keys SHOULD NOT appear as attributes.
        '''
        # posts have author_id and blog_id as has-one forreign keys. Check that
        # they don't make it into the JSON representation (they should be in
        # relationships instead).

        # Fetch a single post.
        r = self.test_app().get('/posts?page[limit]=1')
        item = r.json['data'][0]
        # Check for forreign keys.
        self.assertNotIn('author_id', item['attributes'])
        self.assertNotIn('blog_id', item['attributes'])

    def test_spec_links_self(self):
        ''''self' link should fetch same object.

        The optional links member within each resource object contains links
        related to the resource.

        If present, this links object MAY contain a self link that identifies
        the resource represented by the resource object.

        A server MUST respond to a GET request to the specified URL with a
        response that includes the resource as the primary data.
        '''
        person = self.test_app().get('/people/1').json['data']
        # Make sure we got the expected person.
        self.assertEqual(person['type'], 'people')
        self.assertEqual(person['id'], '1')
        # Now fetch the self link.
        person_again = self.test_app().get(person['links']['self']).json['data']
        # Make sure we got the same person.
        self.assertEqual(person_again['type'], 'people')
        self.assertEqual(person_again['id'], '1')

    def test_spec_included_array(self):
        '''Included resources should be in an array under 'included' member.

        In a compound document, all included resources MUST be represented as an
        array of resource objects in a top-level included member.
        '''
        person = self.test_app().get('/people/1?include=blogs').json
        self.assertIsInstance(person['included'], list)
        # Each item in the list should be a resource object: we'll look for
        # type, id and attributes.
        for blog in person['included']:
            self.assertIn('id', blog)
            self.assertEqual(blog['type'], 'blogs')
            self.assertIn('attributes', blog)

    def test_spec_bad_include(self):
        '''Should 400 error on attempt to fetch non existent relationship path.

        If a server is unable to identify a relationship path or does not
        support inclusion of resources from a path, it MUST respond with 400 Bad
        Request.
        '''
        # Try to include a relationship that doesn't exist.
        r = self.test_app().get('/people/1?include=frogs', status=400)

    def test_spec_nested_include(self):
        '''Should return includes for nested resources.

        In order to request resources related to other resources, a
        dot-separated path for each relationship name can be specified:

            * GET /articles/1?include=comments.author
        '''
        r = self.test_app().get('/people/1?include=comments.author')
        people_seen = set()
        types_expected = {'people', 'comments'}
        types_seen = set()
        for item in r.json['included']:
            # Shouldn't see any types other than comments and people.
            self.assertIn(item['type'], types_expected)
            types_seen.add(item['type'])

            # We should only see people 1, and only once.
            if item['type'] == 'people':
                self.assertNotIn(item['id'], people_seen)
                people_seen.add(item['id'])

        # We should have seen at least one of each type.
        self.assertIn('people', types_seen)
        self.assertIn('comments', types_seen)



    def test_spec_multiple_include(self):
        '''Should return multiple related resource types.

        Multiple related resources can be requested in a comma-separated list:

            * GET /articles/1?include=author,comments.author
        '''
        # TODO(Colin) implement

    def test_spec_compound_full_linkage(self):
        '''All included resources should be referenced by a resource link.

        Compound documents require "full linkage", meaning that every included
        resource MUST be identified by at least one resource identifier object
        in the same document. These resource identifier objects could either be
        primary data or represent resource linkage contained within primary or
        included resources.
        '''
        # get a person with included blogs and comments.
        person = self.test_app().get('/people/1?include=blogs,comments').json
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

    def test_spec_compound_no_linkage_sparse(self):
        '''Included resources not referenced if referencing field not included.

        The only exception to the full linkage requirement is when relationship
        fields that would otherwise contain linkage data are excluded via sparse
        fieldsets.
        '''
        person = self.test_app().get(
            '/people/1?include=blogs&fields[people]=name,comments'
        ).json
        # Find all the resource identifiers.
        rids = set()
        for rel in person['data']['relationships'].values():
            for item in rel['data']:
                rids.add((item['type'], item['id']))
        self.assertGreater(len(person['included']), 0)
        for blog in person['included']:
            self.assertEqual(blog['type'], 'blogs')

    def test_spec_compound_unique_resources(self):
        '''Each resource object should appear only once.

        A compound document MUST NOT include more than one resource object for
        each type and id pair.
        '''
        # get some people with included blogs and comments.
        people = self.test_app().get('/people?include=blogs,comments').json
        # Check that each resource only appears once.
        seen = set()
        # Add the main resource objects.
        for person in people['data']:
            self.assertNotIn((person['type'], person['id']), seen)
            seen.add((person['type'], person['id']))
        # Check the included resources.
        for obj in people['included']:
            self.assertNotIn((obj['type'], obj['id']), seen)
            seen.add((obj['type'], obj['id']))

    def test_spec_links(self):
        '''Links should be an object with URL strings.

        Where specified, a links member can be used to represent links. The
        value of each links member MUST be an object (a "links object").

        Each member of a links object is a “link”. A link MUST be represented as
        either:

            * a string containing the link’s URL.
            * an object ("link object") which can contain the following members:
                * href: a string containing the link’s URL.
                * meta: a meta object containing non-standard meta-information
                 about the link.

        Note: only URL string links are currently generated by jsonapi.
        '''
        links = self.test_app().get('/people').json['links']
        self.assertIsInstance(links['self'], str)
        self.assertIsInstance(links['first'], str)
        self.assertIsInstance(links['last'], str)

    def test_spec_fetch_non_existent(self):
        '''Should 404 when fetching non existent resource.

        A server MUST respond with 404 Not Found when processing a request to
        fetch a single resource that does not exist,
        '''
        r = self.test_app().get('/people/1000', status=404)

    def test_spec_fetch_non_existent_related(self):
        '''Should return primary data of null, not 404.

        null is only an appropriate response when the requested URL is one that
        might correspond to a single resource, but doesn’t currently.
        '''
        data = self.test_app().get('/comments/5/author').json['data']
        self.assertIsNone(data)

    def test_spec_sparse_fields(self):
        '''Should return only requested fields.

        A client MAY request that an endpoint return only specific fields in the
        response on a per-type basis by including a fields[TYPE] parameter.

        The value of the fields parameter MUST be a comma-separated (U+002C
        COMMA, ",") list that refers to the name(s) of the fields to be
        returned.

        If a client requests a restricted set of fields for a given resource
        type, an endpoint MUST NOT include additional fields in resource objects
        of that type in its response.
        '''
        # Ask for just the title, content and author fields of a post.
        r = self.test_app().get('/posts/1?fields[posts]=title,content,author')
        data = r.json['data']

        atts = data['attributes']
        self.assertEqual(len(atts), 2)
        self.assertIn('title', atts)
        self.assertIn('content', atts)

        rels = data['relationships']
        self.assertEqual(len(rels), 1)
        self.assertIn('author', rels)

    def test_spec_empty_fields(self):
        """should return no attributes."""
        person = self.test_app().get(
            '/people?fields[people]='
        ).json
        self.assertEqual(len(person['data'][0]['attributes']), 0)

    def test_spec_single_sort(self):
        '''Should return  collection sorted by correct field.

        An endpoint MAY support requests to sort the primary data with a sort
        query parameter. The value for sort MUST represent sort fields.

            * GET /people?sort=age
        '''
        data = self.test_app().get('/posts?sort=content').json['data']
        prev = ''
        for item in data:
            self.assertGreaterEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']


    def test_spec_multiple_sort(self):
        '''Should return collection sorted by multiple fields, applied in order.

        An endpoint MAY support multiple sort fields by allowing comma-separated
        (U+002C COMMA, ",") sort fields. Sort fields SHOULD be applied in the
        order specified.

            * GET /people?sort=age,name
        '''
        data = self.test_app().get('/posts?sort=content,id').json['data']
        prev_content = ''
        prev_id = 0
        for item in data:
            self.assertGreaterEqual(
                item['attributes']['content'],
                prev_content
            )
            if item['attributes']['content'] != prev_content:
                prev_id = 0
            self.assertGreaterEqual(int(item['id']), prev_id)
            prev_content = item['attributes']['content']
            prev_id = int(item['id'])

    def test_spec_descending_sort(self):
        '''Should return results sorted by field in reverse order.

        The sort order for each sort field MUST be ascending unless it is
        prefixed with a minus (U+002D HYPHEN-MINUS, "-"), in which case it MUST
        be descending.

            * GET /articles?sort=-created,title
        '''
        data = self.test_app().get('/posts?sort=-content').json['data']
        prev = 'zzz'
        for item in data:
            self.assertLessEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']

    # TODO(Colin) repeat sort tests for other collection returning endpoints,
    # because: Note: This section applies to any endpoint that responds with a
    # resource collection as primary data, regardless of the request type

    def test_spec_pagination_links(self):
        '''Should provide correct pagination links.

        A server MAY provide links to traverse a paginated data set ("pagination
        links").

        Pagination links MUST appear in the links object that corresponds to a
        collection. To paginate the primary data, supply pagination links in the
        top-level links object. To paginate an included collection returned in a
        compound document, supply pagination links in the corresponding links
        object.

        The following keys MUST be used for pagination links:

            * first: the first page of data
            * last: the last page of data
            * prev: the previous page of data
            * next: the next page of data
        '''
        json = self.test_app().get('/posts?page[limit]=2&page[offset]=2').json
        self.assertEqual(len(json['data']), 2)
        self.assertIn('first', json['links'])
        self.assertIn('last', json['links'])
        self.assertIn('prev', json['links'])
        self.assertIn('next', json['links'])

    def test_spec_pagination_unavailable_links(self):
        '''Next page link should not be available

        Keys MUST either be omitted or have a null value to indicate that a
        particular link is unavailable.
        '''
        r = self.test_app().get('/posts?page[limit]=1')
        available = r.json['meta']['results']['available']
        json = self.test_app().get(
            '/posts?page[limit]=2&page[offset]=' + str(available - 2)
        ).json
        self.assertEqual(len(json['data']), 2)
        self.assertNotIn('next', json['links'])

    def test_spec_negative_offset(self):
        """Offset must not be negative"""
        self.test_app().get('/posts?page[offset]=-1', status=400)

    def test_spec_negative_limit(self):
        """Limit must not be negative"""
        self.test_app().get('/posts?page[limit]=-1', status=400)

    def test_spec_pagination_order(self):
        '''Pages (and results) should order restults as per order param.

        Concepts of order, as expressed in the naming of pagination links, MUST
        remain consistent with JSON API’s sorting rules.
        '''
        data = self.test_app().get(
            '/posts?page[limit]=4&sort=content&fields[posts]=content'
        ).json['data']
        self.assertEqual(len(data), 4)
        prev = ''
        for item in data:
            self.assertGreaterEqual(item['attributes']['content'], prev)
            prev = item['attributes']['content']

    # TODO(Colin) repeat sort tests for other collection returning endpoints,
    # because: Note: This section applies to any endpoint that responds with a
    # resource collection as primary data, regardless of the request type

    def test_spec_filterop_eq(self):
        '''Should return collection with just the alice people object.

        The filter query parameter is reserved for filtering data. Servers and
        clients SHOULD use this key for filtering operations.
        '''
        data = self.test_app().get('/people?filter[name:eq]=alice').json['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['type'], 'people')
        self.assertEqual(data[0]['attributes']['name'], 'alice')

    def test_spec_filterop_ne(self):
        '''Should return collection of people whose name is not alice.'''
        data = self.test_app().get('/people?filter[name:ne]=alice').json['data']
        for item in data:
            try:
                errors = item['meta']['errors']
            except KeyError:
                self.assertNotEqual('alice', item['attributes']['name'])

    def test_spec_filterop_startswith(self):
        '''Should return collection where titles start with "post1".'''
        data = self.test_app().get(
            '/posts?filter[title:startswith]=post1'
        ).json['data']
        for item in data:
            self.assertTrue(item['attributes']['title'].startswith('post1'))

    def test_spec_filterop_endswith(self):
        '''Should return collection where titles end with "main".'''
        data = self.test_app().get(
            '/posts?filter[title:endswith]=main'
        ).json['data']
        for item in data:
            self.assertTrue(item['attributes']['title'].endswith('main'))

    def test_spec_filterop_contains(self):
        '''Should return collection where titles contain "bob".'''
        data = self.test_app().get(
            '/posts?filter[title:contains]=bob'
        ).json['data']
        for item in data:
            self.assertTrue('bob' in item['attributes']['title'])

    def test_spec_filterop_lt(self):
        '''Should return posts with published_at less than 2015-01-03.'''
        data = self.test_app().get(
            '/posts?filter[published_at:lt]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertLess(date, ref_date)

    def test_spec_filterop_gt(self):
        '''Should return posts with published_at greater than 2015-01-03.'''
        data = self.test_app().get(
            '/posts?filter[published_at:gt]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertGreater(date, ref_date)

    def test_spec_filterop_le(self):
        '''Should return posts with published_at <= 2015-01-03.'''
        data = self.test_app().get(
            '/posts?filter[published_at:le]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertLessEqual(date, ref_date)

    def test_spec_filterop_ge(self):
        '''Should return posts with published_at >= 2015-01-03.'''
        data = self.test_app().get(
            '/posts?filter[published_at:ge]=2015-01-03'
        ).json['data']
        ref_date = datetime.datetime(2015,1,3)
        for item in data:
            #TODO(Colin) investigate more robust way of parsing date.
            date = datetime.datetime.strptime(
                item['attributes']['published_at'],
                "%Y-%m-%dT%H:%M:%S"
            )
            self.assertGreaterEqual(date, ref_date)

    def test_spec_filterop_like(self):
        '''Should return collection where content matches "*thing*".'''
        data = self.test_app().get(
            '/posts?filter[content:like]=*thing*'
        ).json['data']
        for item in data:
            self.assertTrue('thing' in item['attributes']['content'])


    def test_spec_filterop_ilike(self):
        '''Should return collection where content case insensitive matches "*thing*".'''
        data = self.test_app().get(
            '/posts?filter[content:ilike]=*THING*'
        ).json['data']
        for item in data:
            self.assertTrue('thing' in item['attributes']['content'])

    def test_spec_filterop_json_contains(self):
        '''Should return collection where json_content contains {"b": 2}.'''
        data = self.test_app().get(
            '/posts?filter[json_content:contains]={"b": 2}'
        ).json['data']
        for item in data:
            self.assertIn('b', item['attributes']['json_content'])

    def test_spec_filterop_json_contained_by(self):
        '''Should return collection where json_content contained by expression.'''
        containing_expr = '{"a":1, "b": 2, "c": 3}'
        containing_json = json.loads(containing_expr)
        data = self.test_app().get(
            '/posts?filter[json_content:contained_by]={}'.format(containing_expr)
        ).json['data']
        for item in data:
            for key in item['attributes']['json_content']:
                self.assertIn(key, containing_json)

    def test_spec_filter_related_property(self):
        '''Should return collection of posts with author.name=alice.'''
        data = self.test_app().get('/posts?filter[author.name:eq]=alice').json['data']
        for item in data:
            self.assertEqual(item['attributes']['author_name'], 'alice')

    ###############################################
    # POST tests.
    ###############################################

    def test_spec_post_invalid_json(self):
        '''Invalid json should raise an error.'''

        # Send garbage json
        self.test_app().post(
            '/people',
            '{,,,}',
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_spec_post_no_data_attribute(self):
        '''Missing data attribute in json should raise an error.'''

        # Send minimal json with no data attribute
        self.test_app().post(
            '/people',
            '{"meta": {}}',
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_spec_post_data_not_item(self):
        '''Missing data attribute in json should raise an error.'''

        # Send minimal json with no data attribute
        self.test_app().post(
            '/people',
            '{"data": []}',
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_spec_post_collection(self):
        '''Should create a new person object.'''
        # Make sure there is no test person.
        data = self.test_app().get('/people?filter[name:eq]=test').json['data']
        self.assertEqual(len(data),0)

        # Try adding a test person.
        self.test_app().post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        )

        # Make sure they are there.
        data = self.test_app().get('/people?filter[name:eq]=test').json['data']
        self.assertEqual(len(data),1)

    def test_spec_post_collection_no_attributes(self):
        '''Should create a person with no attributes.'''
        self.test_app().post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        )

    def test_spec_post_must_have_type(self):
        '''type must be specified.

        Note: The type member is required in every resource object throughout
        requests and responses in JSON API. There are some cases, such as when
        POSTing to an endpoint representing heterogenous data, when the type
        could not be inferred from the endpoint. However, picking and choosing
        when it is required would be confusing; it would be hard to remember
        when it was required and when it was not. Therefore, to improve
        consistency and minimize confusion, type is always required.
        '''
        self.test_app().post_json(
            '/people',
            {
                'data': {
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_spec_post_with_id(self):
        '''Should create a person object with id 1000.

        A server MAY accept a client-generated ID along with a request to create
        a resource. An ID MUST be specified with an id key. The client SHOULD
        use a properly generated and formatted UUID as described in RFC 4122

        If a POST request did not include a Client-Generated ID and the
        requested resource has been created successfully, the server MUST return
        a 201 Created status code.

        The response SHOULD include a Location header identifying the location
        of the newly created resource.

        The response MUST also include a document that contains the primary
        resource created.

        If the resource object returned by the response contains a self key in
        its links member and a Location header is provided, the value of the
        self member MUST match the value of the Location header.

        Comment: jsonapi.allow_client_ids is set in the ini file, so we should
        be able to create objects with ids.  The id strategy in test_project
        isn't RFC4122 UUID, but we're not enforcing that since there may be
        other globally unique id strategies in use.
        '''
        r = self.test_app().post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=201 # Test the status code.
        )

        # Test for Location header.
        location = r.headers.get('Location')
        self.assertIsNotNone(location)

        # Test that json is a resource object
        data = r.json['data']
        self.assertEqual(data['id'],'1000')
        self.assertEqual(data['type'],'people')
        self.assertEqual(data['attributes']['name'], 'test')

        # Test that the Location header and the self link match.
        self.assertEqual(data['links']['self'], location)

    def test_spec_post_with_id_disallowed(self):
        '''Should 403 when attempting to create object with id.

        A server MUST return 403 Forbidden in response to an unsupported request
        to create a resource with a client-generated ID.
        '''
        # We need a test_app with different settings.
        test_app = self.test_app(
            options={'pyramid_jsonapi.allow_client_ids': 'false'}
        )
        res = test_app.post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=403
        )
        print(res.json['traceback'])

    def test_spec_post_with_id_conflicts(self):
        '''Should 409 if id exists.

        A server MUST return 409 Conflict when processing a POST request to
        create a resource with a client-generated ID that already exists.
        '''
        self.test_app().post_json(
            '/people',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409 # Test the status code.
        )

    def test_spec_post_type_conflicts(self):
        '''Should 409 if type conflicts with endpoint.

        A server MUST return 409 Conflict when processing a POST request in
        which the resource object’s type is not among the type(s) that
        constitute the collection represented by the endpoint.
        '''
        self.test_app().post_json(
            '/people',
            {
                'data': {
                    'id': '1000',
                    'type': 'frogs',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409 # Test the status code.
        )

    ###############################################
    # PATCH tests.
    ###############################################

    def test_spec_patch(self):
        '''Should change alice's name to alice2'''
        # Patch alice.
        self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # Fetch alice back...
        data = self.test_app().get('/people/1').json['data']
        # ...should now be alice2.
        self.assertEqual(data['attributes']['name'], 'alice2')

    def test_spec_patch_invalid_json(self):
        '''Invalid json should raise an error.'''

        # Send garbage json
        self.test_app().patch(
            '/people/1',
            '{,,,}',
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_spec_patch_no_type_id(self):
        '''Should 409 if id or type do not exist.

        The PATCH request MUST include a single resource object as primary data.
        The resource object MUST contain type and id members.
        '''
        # No id.
        self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )
        # No type.
        self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )
        # No type or id.
        self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_spec_patch_integrity_error(self):
        '''Should 409 if PATCH violates a server side constraint.

        A server MAY return 409 Conflict when processing a PATCH request to
        update a resource if that update would violate other server-enforced
        constraints (such as a uniqueness constraint on a property other than
        id).
        '''
        self.test_app().patch_json(
            '/blogs/1',
            {
                'data': {
                    'id': '1',
                    'type': 'blogs',
                    'attributes': {
                        'title': 'forbidden title'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_spec_patch_empty_success(self):
        '''Should return only meta, not data or links.

        A server MUST return a 200 OK status code if an update is successful,
        the client’s current attributes remain up to date, and the server
        responds only with top-level meta data. In this case the server MUST NOT
        include a representation of the updated resource(s).
        '''
        json = self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'id': '1',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        ).json
        self.assertIn('meta',json)
        self.assertEqual(len(json),1)

    def test_spec_patch_nonexistent(self):
        '''Should 404 when patching non existent resource.

        A server MUST return 404 Not Found when processing a request to modify a
        resource that does not exist.
        '''
        self.test_app().patch_json(
            '/people/1000',
            {
                'data': {
                    'id': '1000',
                    'type': 'people',
                    'attributes': {
                        'name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        )
        # Patching non existent attribute
        detail = self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'type': 'people',
                    'id': '1',
                    'attributes': {
                        'non_existent': 'splat'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        ).json['errors'][0]['detail']
        self.assertIn('has no attribute',detail)
        # Patching non existent relationship
        detail = self.test_app().patch_json(
            '/people/1',
            {
                'data': {
                    'type': 'people',
                    'id': '1',
                    'attributes': {
                        'name': 'splat'
                    },
                    'relationships': {
                        'non_existent': {
                            'data': None
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=404
        ).json['errors'][0]['detail']
        self.assertIn('has no relationship',detail)


    ###############################################
    # DELETE tests.
    ###############################################

    def test_spec_delete_item(self):
        '''Should delete comments/5

        An individual resource can be deleted by making a DELETE request to the
        resource’s URL
        '''

        # Check that comments/5 exists.
        self.test_app().get('/comments/5')

        # Delete comments/5.
        self.test_app().delete('/comments/5')

        # Check that comments/5 no longer exists.
        self.test_app().get('/comments/5', status=404)

    def test_spec_delete_no_such_item(self):
        '''Should fail to delete non-existent comments/99999

        A server SHOULD return a 404 Not Found status code if
        a deletion request fails due to the resource not existing.
        '''

        # Delete comments/99999.
        self.test_app().delete('/comments/99999', status=404)

    def test_spec_delete_invalid_item(self):
        '''Should fail to delete non-existent comments/invalid

        A server SHOULD return a 404 Not Found status code if
        a deletion request fails due to the resource not existing.
        '''

        # Delete comments/invalid
        self.test_app().delete('/comments/invalid', status=404)


class TestErrors(DBTestBase):
    '''Test that errors are thrown properly.'''

    ###############################################
    # Error tests.
    ###############################################

    def test_errors_structure(self):
        '''Errors should be array of objects with code, title, detail members.'''
        r = self.test_app().get(
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

    def test_errors_only_controlled_paths(self):
        '''Error handlers only for controlled paths ('api' and 'metadata')'''
        app = self.test_app(
            options={'pyramid_jsonapi.route_pattern_api_prefix': 'api'}
        )
        # Both /api/ and /metadata/ should have json structured errors
        for path in ('/api/', '/metadata/'):
            json = app.get(path, status=404).json
        # Other paths should not have json errors
        for path in ('/', '/splat/', '/api_extra/'):
            r = app.get(path, status=404)
            self.assertRaises(AttributeError, getattr, r, 'json')


    def test_errors_composite_key(self):
        '''Should raise exception if a model has a composite key.'''
        self.assertRaisesRegex(
            Exception,
            r'^Model \S+ has more than one primary key.$',
            self.test_app,
            {'pyramid_jsonapi_tests.models_iterable': 'composite_key'}
        )


class TestMalformed(DBTestBase):
    '''Various malformed POSTs and PATCHes.'''

    def test_malformed_collection_post_not_single_item(self):
        '''Should complain about data being a list.'''
        self.test_app().post_json(
            '/people',
            {'type': 'people', 'data': []},
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_malformed_collection_post_no_data(self):
        '''Should complain about lack of data attribute.'''
        self.test_app().post_json(
            '/people',
            {'type': 'people'},
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_malformed_item_patch_no_data(self):
        '''Should complain about lack of data attribute.'''
        self.test_app().patch_json(
            '/people/1',
            {'type': 'people', 'id': '1'},
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_no_filter_operator_defaults_to_eq(self):
        '''Missing filter operator should behave as 'eq'.'''

        r = self.test_app().get('/people?filter[name:eq]=alice')
        op = r.json['data'][0]
        r = self.test_app().get('/people?filter[name]=alice')
        noop = r.json['data'][0]

        self.assertEqual(op, noop)


    def test_malformed_filter_unregistered_operator(self):
        '''Unkown filter operator should raise 400 BadRequest.'''
        self.test_app().get(
            '/people?filter[name:not_an_op]=splat',
            status=400
        )

    def test_malformed_filter_bad_operator(self):
        '''Known filter with no comparator should raise 500 InternalServerError.'''
        self.test_app().get(
            '/people?filter[name:bad_op]=splat',
            status=500
        )

    def test_malformed_filter_unknown_column(self):
        '''Unkown column should raise 400 BadRequest.'''
        self.test_app().get(
            '/people?filter[unknown_column:eq]=splat',
            status=400
        )


class TestHybrid(DBTestBase):
    '''Test cases for @hybrid_property attributes.'''

    def test_hybrid_readonly_get(self):
        '''Blog object should have owner_name attribute.'''
        atts = self.test_app().get(
            '/blogs/1'
        ).json['data']['attributes']
        self.assertIn('owner_name', atts)
        self.assertEqual(atts['owner_name'], 'alice')

    def test_hybrid_readonly_patch(self):
        '''Updating owner_name should fail with 409.'''
        self.test_app().patch_json(
            '/blogs/1',
            {
                'data': {
                    'id': '1',
                    'type': 'blogs',
                    'attributes': {
                        'owner_name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_hybrid_writeable_patch(self):
        '''Should be able to update author_name of Post object.'''
        # Patch post 1 and change author_name to 'alice2'
        r = self.test_app().patch_json(
            '/posts/1',
            {
                'data': {
                    'id': '1',
                    'type': 'posts',
                    'attributes': {
                        'author_name': 'alice2'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
        )
        # author_name should be in the list of updated attributes.
        self.assertIn('author_name', r.json['meta']['updated']['attributes'])
        # Fetch alice back...
        data = self.test_app().get('/people/1').json['data']
        # ...should now be called alice2.
        self.assertEqual(data['attributes']['name'], 'alice2')


class TestJoinedTableInheritance(DBTestBase):
    '''Test cases for sqlalchemy joined table inheritance pattern.'''

    def test_joined_benign_create_fetch(self):
        '''Should create BenignComment with author people/1 and then fetch it.'''
        content = 'Main content.'
        fawning_text = 'You are so great.'
        created = self.test_app().post_json(
            '/benign_comments',
            {
                'data': {
                    'type': 'benign_comments',
                    'attributes': {
                        'content': content,
                        'fawning_text': fawning_text
                    },
                    'relationships': {
                        'author': {
                            'data': {'type': 'people', 'id': '1'}
                        }
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=201
        ).json['data']
        # Fetch the object back
        fetched = self.test_app().get(
            '/benign_comments/{}'.format(created['id'])
        ).json['data']
        self.assertEqual(fetched['attributes']['content'], content)
        self.assertEqual(
            fetched['attributes']['fawning_text'],
            fawning_text
        )
        self.assertEqual(fetched['relationships']['author']['data']['id'],'1')


class TestFeatures(DBTestBase):
    '''Test case for features beyond spec.'''

    def test_feature_invisible_column(self):
        '''people object should not have attribute "invisible".'''
        atts = self.test_app().get(
            '/people/1'
        ).json['data']['attributes']
        self.assertNotIn('invisible', atts)
        self.assertNotIn('invisible_hybrid', atts)

    def test_feature_invisible_relationship(self):
        '''people object should not have relationship "invisible_comments".'''
        rels = self.test_app().get(
            '/people/1'
        ).json['data']['relationships']
        self.assertNotIn('invisible_comments', rels)

    def test_feature_rename_collection(self):
        '''Should be able to fetch from whatsits even though table is things.'''
        # There should be whatsits...
        self.test_app().get('/whatsits')
        # ...but not things.
        self.test_app().get('/things', status=404)

    def test_feature_construct_with_models_list(self):
        '''Should construct an api from a list of models.'''
        test_app = self.test_app(
            options={'pyramid_jsonapi_tests.models_iterable': 'list'}
        )
        test_app.get('/blogs/1')

    def test_feature_debug_endpoints(self):
        '''Should create a set of debug endpoints for manipulating the database.'''
        test_app = self.test_app(
            options={
                'pyramid_jsonapi.debug_endpoints': 'true',
                'pyramid_jsonapi.debug_test_data_module': 'test_project.test_data'
            }
        )
        test_app.get('/debug/populate')

    def test_feature_disable_schema_validation(self):
        '''Should disable schema validation.'''
        # Create an app without schema validation.
        test_app = self.test_app(
            options = {
                'pyramid_jsonapi.schema_validation': 'false'
            }
        )
        # Schema validation produces 400 without 'type', without validation we
        # get 409 (Unsupported type None)
        test_app.post_json(
            '/people',
            {
                'data': {
                    'not_type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=409
        )

    def test_feature_alternate_schema_file(self):
        '''Should load alternate schema file.'''
        test_app = self.test_app(
            options={'pyramid_jsonapi.schema_file': '{}/test-alt-schema.json'.format(parent_dir)}
        )
        test_app.post_json(
            '/people',
            {
                'data': {
                    'not_type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'},
            status=400
        )

    def test_feature_debug_meta(self):
        '''Should add meta information.'''
        test_app = self.test_app(
            options={'pyramid_jsonapi.debug_meta': 'true'}
        )
        self.assertIn('debug',test_app.get('/people/1').json['meta'])

    def test_feature_expose_foreign_keys(self):
        """Should return blog with owner_id."""
        test_app = self.test_app(
            options={'pyramid_jsonapi.expose_foreign_keys': 'true'}
        )
        self.assertIn('owner_id', test_app.get('/blogs/1').json['data']['attributes'])

class TestBugs(DBTestBase):

    def test_19_last_negative_offset(self):
        '''last link should not have negative offset.

        #19: 'last' link has negative offset if zero results are returned
        '''
        # Need an empty collection: use a filter that will not match.
        last = self.test_app().get(
            '/posts?filter[title:eq]=frog'
        ).json['links']['last']
        offset = int(
            urllib.parse.parse_qs(
                urllib.parse.urlparse(last).query
            )['page[offset]'][0]
        )
        self.assertGreaterEqual(offset, 0)

    def test_20_non_string_id(self):
        '''Creating single object should not result in integer id.

        #20: creating single object returns non string id
        '''
        data = self.test_app().post_json(
            '/people',
            {
                'data': {
                    'type': 'people',
                    'attributes': {
                        'name': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']
        self.assertIsInstance(data['id'], str)

    def test_56_post_with_non_id_primary_key(self):
        '''POST to model with non 'id' primary key should work.

        #56: POSTing a new item where the primary key column is not 'id' causes
        an error.
        '''
        data = self.test_app().post_json(
            '/comments',
            {
                'data': {
                    'id': '1000',
                    'type': 'comments',
                    'attributes': {
                        'content': 'test'
                    }
                }
            },
            headers={'Content-Type': 'application/vnd.api+json'}
        ).json['data']
        self.assertEqual(data['id'],'1000')

    def test_association_proxy(self):
        '''Should treat association proxy as a relationship.'''
        data = self.test_app().get('/people/1').json['data']
        self.assertIn('articles_by_proxy', data['relationships'])

    def test_175_head_method(self):
        '''Should produce OK for HEAD request.'''
        self.test_app().head('/people/1')


class TestEndpoints(DBTestBase):
    """Tests for endpoint configuration."""

    def test_api_prefix(self):
        """Test setting api prefix."""
        self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_api_prefix': 'api'
            }).get('/api/people')

    def test_metadata_endpoints_disable(self):
        self.test_app(
            options={
                'pyramid_jsonapi.metadata_endpoints': 'false'
            }).get('/metadata/JSONSchema', status=404)

    def test_api_version(self):
        """Test setting api version."""
        self.test_app(
            options={
                'pyramid_jsonapi.api_version': '10'
            }).get('/10/people')
        self.test_app(
            options={
                'pyramid_jsonapi.api_version': '10'
            }).get('/10/metadata/JSONSchema')

    def test_route_pattern_prefix(self):
        """Test setting route_pattern_prefix."""
        self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_prefix': 'SPLAT'
            }).get('/SPLAT/people')
        self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_prefix': 'SPLAT'
            }).get('/SPLAT/metadata/JSONSchema')

    def test_route_pattern_prefix_error(self):
        """Test setting route_pattern_prefix error handling."""
        resp = self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_prefix': 'SPLAT'
            }).get('/SPLAT/invalid',
            status=404)
        self.assertTrue(resp.content_type == 'application/vnd.api+json')

    def test_api_version(self):
        """Test setting api_version."""
        self.test_app(
            options={
                'pyramid_jsonapi.api_version': 'v1',
            }).get('/v1/people')

    def test_api_version_error(self):
        """Test setting api_version error handling."""
        resp = self.test_app(
            options={
                'pyramid_jsonapi.api_version': 'v1',
            }).get('/v1/invalid',
            status=404)
        self.assertTrue(resp.content_type == 'application/vnd.api+json')

    def test_route_pattern_api_prefix(self):
        """Test setting route_pattern_api_prefix."""
        self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_api_prefix': 'API'
            }).get('/API/people')

    def test_route_pattern_api_prefix_error(self):
        """Test setting route_pattern_prefix error handling."""
        resp = self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_api_prefix': 'API'
            }).get('/API/invalid',
            status=404)
        self.assertTrue(resp.content_type == 'application/vnd.api+json')

    def test_route_pattern_metadata_prefix(self):
        """Test setting route_pattern_metadata_prefix."""
        self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_metadata_prefix': 'METADATA'
            }).get('/METADATA/JSONSchema')

    def test_route_pattern_metadata_prefix_error(self):
        """Test setting route_pattern_prefix error handling."""
        resp = self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_metadata_prefix': 'METADATA'
            }).get('/METADATA/invalid',
            status=404)
        self.assertTrue(resp.content_type == 'application/vnd.api+json')

    def test_route_pattern_all_prefixes(self):
        """Test setting all pattern prefixes."""
        api = self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_prefix': 'SPLAT',
                'pyramid_jsonapi.api_version': 'v1',
                'pyramid_jsonapi.route_pattern_api_prefix': 'API',
                'pyramid_jsonapi.route_pattern_metadata_prefix': 'METADATA'
            })
        api.get('/SPLAT/v1/API/people')
        api.get('/SPLAT/v1/METADATA/JSONSchema')

    def test_route_pattern_all_prefixes_error(self):
        """Test setting all pattern prefixes error handling."""
        api = self.test_app(
            options={
                'pyramid_jsonapi.route_pattern_prefix': 'SPLAT',
                'pyramid_jsonapi.api_version': 'v1',
                'pyramid_jsonapi.route_pattern_api_prefix': 'API',
                'pyramid_jsonapi.route_pattern_metadata_prefix': 'METADATA'
            })
        self.assertEqual(
            api.get('/SPLAT/v1/API/invalid', status=404).content_type,
            'application/vnd.api+json'
        )
        self.assertEqual(
            api.get('/SPLAT/v1/METADATA/invalid', status=404).content_type,
            'application/vnd.api+json'
        )


class TestMetaData(DBTestBase):
    """Tests for the metadata plugins."""

    @classmethod
    def setUpClass(cls):
        """Setup metadata plugins."""
        super().setUpClass()
        config = Configurator()
        cls.api = pyramid_jsonapi.PyramidJSONAPI(config, [])
        cls.api.create_jsonapi()
        cls.metadata = pyramid_jsonapi.metadata.MetaData(cls.api)

    def test_no_jsonschema_module(self):
        """Test how things break if jsonschema is disabled."""
        self.test_app(
            options={
                'pyramid_jsonapi.metadata_modules': ''
            }).post('/people', '{}', status=500)

        self.test_app(
            options={
                'pyramid_jsonapi.metadata_modules': ''
            }).get('/metadata/JSONSchema', '{}', status=404)

    def test_disable_jsonschema_validation(self):
        """Test disabling jsonschema and validation together works."""
        self.test_app(
            options={
                'pyramid_jsonapi.metadata_modules': '',
                'pyramid_jsonapi.schema_validation': 'false',
            }).post_json(
                '/people',
                {
                    'data': {
                        'type': 'people',
                        'attributes': {
                            'name': 'test'
                        }
                    }
                },
                headers={'Content-Type': 'application/vnd.api+json'}
            )

    def test_jsonschema_template(self):
        """Test that template() returns valid json, and as a view."""
        dir_tmpl = json.dumps(self.metadata.JSONSchema.template())
        view_tmpl = self.test_app().get('/metadata/JSONSchema', '{}').json

    def test_jsonschema_load_schema_file(self):
        """Test loading jsonschema from file."""
        path = "/tmp/nosuchfile.json"
        schema = {"test": "true"}
        self.api.settings.schema_file = path
        with patch("builtins.open", mock_open(read_data=json.dumps(schema))) as mock_file:
            self.metadata.JSONSchema.load_schema()
            mock_file.assert_called_with(path)
            self.assertDictEqual(schema, self.metadata.JSONSchema.schema)

    def test_jsonschema_resource_attributes_view(self):
        """Test that resource_attributes view returns valid json."""
        self.test_app().get('/metadata/JSONSchema/resource/people', status=200).json

    def test_jsonschema_resource_attributes_view_not_found(self):
        """Test that view returns 404 for non-existent endpoint."""
        self.test_app().get('/metadata/JSONSchema/resource/invalid', status=404)

    def test_jsonschema_endpoint_schema_view(self):
        """Check that endpoint_schema returns json with appropriate query params."""
        self.test_app().get('/metadata/JSONSchema/endpoint/people',
                            params='method=get&direction=request&code=200',
                            status=200).json

        self.test_app().get('/metadata/JSONSchema/endpoint/people',
                            params='method=get&direction=response&code=200',
                            status=200).json

    def test_jsonschema_endpoint_schema_view_failure_schema(self):
        """Test that a reference to the failure schema is returned for code=4xx."""
        res = self.test_app().get('/metadata/JSONSchema/endpoint/people',
                            params='method=get&direction=response&code=404',
                            status=200).json
        self.assertEqual(res, {"$ref" : "#/definitions/failure"})

    def test_jsonschema_endpoint_schema_view_bad_params(self):
        """Test that 400 returned if missing/bad query params specified."""
        self.test_app().get('/metadata/JSONSchema/endpoint/people', status=400).json
        self.test_app().get('/metadata/JSONSchema/endpoint/people', params='cat=1', status=400).json

    def test_jsonschema_endpoint_schema_view_not_found(self):
        self.test_app().get('/metadata/JSONSchema/endpoint/invalid',
                            params='method=get&direction=request&code=200',
                            status=404).json

    def test_jsonschema_invalid_schema(self):
        """Invalid schema mappings generate empty resource attrs."""
        # posts has JSONB field
        res = self.test_app().get('/metadata/JSONSchema/resource/posts').json
        self.assertEqual(res, {})

    def test_openapi_swagger_ui_view(self):
        """Test that swagger_ui view returns html."""
        html = self.test_app().get('/metadata/OpenAPI', status=200).html

    def test_openapi_specification_view(self):
        """Test that specification view returns valid json."""
        self.test_app().get('/metadata/OpenAPI/specification', status=200).json

    # def test_openapi_specification_valid(self):
    #     """Test that the openapi specification returned is valid."""
    #     validate_spec(self.test_app().get('/metadata/OpenAPI/specification', status=200).json)
        # print(json.dumps(self.test_app().get('/metadata/OpenAPI/specification', status=200).json, indent=4))

    def test_openapi_file(self):
        """Test providing openapi spec updates in a file."""
        path = os.path.dirname(os.path.realpath(__file__))
        res = self.test_app(
            options={
                'pyramid_jsonapi.openapi_file': os.path.join(path, 'test-openapi.json'),
            }).get('/metadata/OpenAPI/specification', status=200).json
        # Check that openapi file merge has overridden version string
        self.assertEqual("999", res['openapi'])


if __name__ == "__main__":
    unittest.main()
