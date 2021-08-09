import ltree_models
import sqlalchemy
from sqlalchemy import (
    create_engine,
)
from sqlalchemy.orm import (
    aliased,
)
import testing.postgresql
from test_project import (
    test_data
)
from test_project.models import (
    DBSession,
    ArticleAuthorAssociation,
    ArticleByAssoc,
    ArticleByObj,
    Base,
    Blog,
    Person,
    LtreeNode,
    TreeNode,
)
import transaction
import unittest

def setUpModule():
    '''Create a test DB and import data.'''
    # Create a new database somewhere in /tmp
    global postgresql
    global engine
    postgresql = testing.postgresql.Postgresql(port=7654)
    engine = create_engine(postgresql.url())
    ltree_models.add_ltree_extension(engine)
    DBSession.configure(bind=engine)


def tearDownModule():
    '''Throw away test DB.'''
    global postgresql
    DBSession.close()
    postgresql.stop()


class DBTestBase(unittest.TestCase):

    def setUp(self):
        Base.metadata.create_all(engine)
        # Add some basic test data.
        test_data.add_to_db(engine)
        transaction.begin()

    def tearDown(self):
        transaction.abort()
        Base.metadata.drop_all(engine)


class IllustrateRelatedQueries(DBTestBase):

    def test_fk_one_to_many(self):
        query = DBSession.query(Blog).select_from(Person).join(
            Person.blogs
        ).filter(
            Person.id == '1'
        )
        alice = DBSession.query(Person).get('1')
        self.assertEqual(query.all(), alice.blogs)

    def test_fk_many_to_one(self):
        query = DBSession.query(Person).select_from(Blog).join(
            Blog.owner
        ).filter(
            Blog.id == '1'
        )
        self.assertEqual(query.one(), DBSession.query(Person).get('1'))

    def test_fk_many_to_many_assoc_table(self):
        query = DBSession.query(ArticleByAssoc).select_from(Person).join(
            Person.articles_by_assoc
        ).filter(
            Person.id == '11'
        )
        person11 = DBSession.query(Person).get('11')
        self.assertEqual(query.all(), person11.articles_by_assoc)
        query = DBSession.query(ArticleByAssoc).select_from(Person).join(
            Person.articles_by_assoc
        ).filter(
            Person.id == '12'
        )
        person12 = DBSession.query(Person).get('12')
        self.assertEqual(query.all(), person12.articles_by_assoc)

    def test_fk_many_to_many_assoc_proxy(self):
        rel = sqlalchemy.inspect(Person).all_orm_descriptors['articles_by_proxy']
        proxy = rel.for_class(Person)
        # print(proxy.local_attr)
        # print(proxy.remote_attr)
        query = DBSession.query(ArticleByObj).select_from(Person).join(
            # Person.article_associations
            proxy.local_attr
        ).join(
            # ArticleAuthorAssociation.article
            proxy.remote_attr
        ).filter(
            Person.id == '12'
        )
        person12 = DBSession.query(Person).get('12')
        self.assertEqual(
            [aa.article for aa in person12.article_associations],
            query.all()
        )

    def test_fk_self_one_to_many(self):
        tn2 = aliased(TreeNode)
        query = DBSession.query(TreeNode).select_from(tn2).join(
            tn2.children
        ).filter(
            tn2.id == '1'
        )
        root = DBSession.query(TreeNode).get('1')
        self.assertEqual(query.all(), root.children)

    def test_fk_self_many_to_one(self):
        tn2 = aliased(TreeNode)
        query = DBSession.query(TreeNode).select_from(tn2).join(
            tn2.parent
        ).filter(
            tn2.id == '2'
        )
        child = DBSession.query(TreeNode).get('2')
        self.assertEqual(query.one(), child.parent)

    def test_join_condition_one_to_many(self):
        query = DBSession.query(Blog).select_from(Person).join(
            Person.blogs_from_titles
        ).filter(
            Person.id == '1'
        )
        alice = DBSession.query(Person).get('1')
        self.assertEqual(query.all(), alice.blogs_from_titles)

    def test_ltree_node_children(self):
        lt2 = aliased(LtreeNode)
        query = DBSession.query(LtreeNode).select_from(lt2).join(
            lt2.children
        ).filter(
            lt2.id == '1'
        )
        root = DBSession.query(LtreeNode).get('1')
        self.assertEqual(query.all(), root.children)

    def test_ltree_node_parent(self):
        lt2 = aliased(LtreeNode)
        query = DBSession.query(LtreeNode).select_from(lt2).join(
            lt2.parent
        ).filter(
            lt2.id == '2'
        )
        child = DBSession.query(LtreeNode).get('2')
        self.assertEqual(query.one(), child.parent)

    def test_ltree_node_ancestors(self):
        lt2 = aliased(LtreeNode)
        query = DBSession.query(LtreeNode).select_from(lt2).join(
            lt2.ancestors
        ).filter(
            lt2.node_name == 'r.1.2'
        )
        node = DBSession.query(LtreeNode).filter(LtreeNode.node_name == 'r.1.2').one()
        # self.assertEqual(query.all(), root.children)
        print(query.all())
