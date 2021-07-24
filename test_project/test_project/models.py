from ltree import (
    LtreeMixin,
)
from sqlalchemy import (
    Table,
    Column,
    Index,
    Integer,
    Text,
    BigInteger,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    CheckConstraint,
    func,
    select,
    )
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method
from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
    relationship,
    backref,
    foreign,
    remote,
    )
from sqlalchemy.orm.interfaces import (
    ONETOMANY,
    MANYTOMANY,
    MANYTOONE,
)
from zope.sqlalchemy import register

DBSession = scoped_session(sessionmaker())
register(DBSession)
Base = declarative_base()

IdType = BigInteger
def IdColumn():
    '''Convenience function: the default Column for object ids.'''
    return Column(IdType, primary_key=True, autoincrement=True)
def IdRefColumn(reference, *args, **kwargs):
    '''Convenience function: the default Column for references to object ids.'''
    return Column(IdType, ForeignKey(reference), *args, **kwargs)

authors_articles_assoc = Table(
    'authors_articles_assoc',
    Base.metadata,
    IdRefColumn('people.id', name='author_id', primary_key=True),
    IdRefColumn('articles_by_assoc.articles_by_assoc_id', name='article_id',
        primary_key=True)
)

class Person(Base):
    __tablename__ = 'people'
    id = IdColumn()
    name = Column(Text)
    age = Column(Integer)
    invisible = Column(Text)
    @hybrid_property
    def invisible_hybrid(self):
        return 'boo!'

    blogs = relationship('Blog', backref='owner')
    posts = relationship('Post', backref='author')
    comments = relationship('Comment', backref='author')
    invisible_comments = relationship('Comment')
    articles_by_assoc = relationship(
        "ArticleByAssoc",
        secondary=authors_articles_assoc,
        backref="authors"
    )
    article_associations = relationship(
        'ArticleAuthorAssociation',
        cascade='all, delete-orphan',
        backref='author'
    )
    articles_by_proxy = association_proxy('article_associations', 'article')
    # A relationship that doesn't join along the usual fk -> pk lines.
    blogs_from_titles = relationship(
        'Blog',
        primaryjoin="remote(Blog.title).like('%' + foreign(Person.name))",
        viewonly=True,
        uselist=True,
    )


    # make invisible columns invisible to API
    invisible.info.update({'pyramid_jsonapi': {'visible': False}})
    invisible_hybrid.info.update({'pyramid_jsonapi': {'visible': False}})
    invisible_comments.info.update({'pyramid_jsonapi': {'visible': False}})


class Blog(Base):
    __tablename__ = 'blogs'
    __table_args__ = (
        CheckConstraint('owner_id != 3'),
        CheckConstraint("title != 'forbidden title'")
    )
    id = IdColumn()
    title = Column(Text)
    owner_id = IdRefColumn('people.id')
    # A read only hybrid property
    @hybrid_property
    def owner_name(self):
        try:
            return self.owner.name
        except AttributeError:
            # No owner
            return None

    posts = relationship('Post', backref='blog')
    # Using a hybrid property as a ONETOMANY relationship.
    @hybrid_property
    def posts_authors(self):
        # Return the authors of all of the posts (as objects, like a relationship)
        authors = set()
        for post in self.posts:
            authors.add(post.author)
        return list(authors)
    posts_authors.info['pyramid_jsonapi'] = {
        'relationship': {
            'direction': ONETOMANY,
            'queryable': False,
            'tgt_class': 'Person',
        }
    }


class Post(Base):
    __tablename__ = 'posts'
    id = IdColumn()
    title = Column(Text)
    content = Column(Text)
    published_at = Column(DateTime, nullable=False, server_default=func.now())
    json_content = Column(JSONB)
    blog_id = IdRefColumn('blogs.id')
    author_id = IdRefColumn('people.id', nullable=False)
    # A read-write hybrid property
    @hybrid_property
    def author_name(self):
        author_name = None
        try:
            author_name = self.author.name
        except AttributeError:
            # No author
            pass
        return author_name
    @author_name.setter
    def author_name(self, name):
        self.author.name = name

    comments = relationship('Comment', backref = 'post')
    # Using a hybrid property as a MANYTOONE relationship.
    @hybrid_property
    def blog_owner(self):
        # Return the owner of the blog this post is in (as an object, like a
        # relationship)
        return self.blog.owner
    blog_owner.info['pyramid_jsonapi'] = {
        'relationship': {
            'direction': MANYTOONE,
            'queryable': False,
            'tgt_class': Person,
        }
    }


class Comment(Base):
    __tablename__ = 'comments'
    comments_id = IdColumn()
    content = Column(Text)
    author_id = IdRefColumn('people.id')
    post_id = IdRefColumn('posts.id')
    type = Column(Text)

    __mapper_args__ = {
        'polymorphic_identity': 'comments',
        'polymorphic_on': 'type'
    }


class BenignComment(Comment):
    __tablename__ = 'benign_comments'
    comments_id = IdRefColumn(
        'comments.comments_id',
        primary_key=True
    )
    fawning_text = Column(Text)
    __mapper_args__ = {
        'polymorphic_identity': 'benign_comments'
    }


class VitriolicComment(Comment):
    __tablename__ = 'vitriolic_comments'
    comments_id = IdRefColumn(
        'comments.comments_id',
        primary_key=True
    )
    scathing_text = Column(Text)
    __mapper_args__ = {
        'polymorphic_identity': 'vitriolic_comments'
    }


class ArticleByAssoc(Base):
    __tablename__ = 'articles_by_assoc'
    articles_by_assoc_id = IdColumn()
    title = Column(Text, nullable=False)
    content = Column(Text)
    published_at = Column(DateTime)


class ArticleByObj(Base):
    __tablename__ = 'articles_by_obj'
    articles_by_obj_id = IdColumn()
    title = Column(Text, nullable=False)
    content = Column(Text)
    published_at = Column(DateTime)
    author_associations = relationship(
        'ArticleAuthorAssociation',
        cascade='all, delete-orphan',
        backref='article'
    )
    authors_by_proxy = association_proxy('author_associations', 'author')


class ArticleAuthorAssociation(Base):
    __tablename__ = 'article_author_associations'
    article_author_associations_id = IdColumn()
    article_id = IdRefColumn(
        'articles_by_obj.articles_by_obj_id',
        # nullable=False
    )
    author_id = IdRefColumn(
        'people.id',
        # nullable=False
    )
    date_joined = Column(DateTime, server_default=func.now())

    # __table_args__ = (
    #     UniqueConstraint('article_id', 'author_id'),
    # )

    def __init__(
        self, article=None, author=None, date_joined=None,
        article_author_associations_id=None,
        article_id=None,
        author_id=None
        ):
        if article is not None:
            self.article = article
        if author is not None:
            self.author = author
        self.date_joined = date_joined
        if self.date_joined is None:
            self.date_joined = func.now()
        if article_author_associations_id is not None:
            self.article_author_associations_id = article_author_associations_id
        if article_id is not None:
            self.article_id = article_id
        if author_id is not None:
            self.author_id = author_id


class RenamedThings(Base):
    __tablename__ = 'things'
    id = IdColumn()
    stuff = Column(Text)
    __pyramid_jsonapi__ = {
        'collection_name': 'whatsits'
    }


class TreeNode(Base):
    __tablename__ = 'treenodes'
    id = IdColumn()
    name = Column(Text)
    parent_id = IdRefColumn('treenodes.id')
    children = relationship("TreeNode",
        backref=backref('parent', remote_side=[id])
    )


class PersonView(Base):
    __table__ = select(Person).subquery()

    posts = relationship('Post', backref='view_author')

    __pyramid_jsonapi__ = {
        'collection_name': 'view_people',
    }


class LtreeNode(Base, LtreeMixin):
    __tablename__ = 'ltree_nodes'

    id = IdColumn()
