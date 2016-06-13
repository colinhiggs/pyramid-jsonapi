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
    )

from sqlalchemy.ext.declarative import declarative_base

from sqlalchemy.orm import (
    scoped_session,
    sessionmaker,
    relationship,
    backref
    )

from zope.sqlalchemy import ZopeTransactionExtension

DBSession = scoped_session(sessionmaker(extension=ZopeTransactionExtension()))
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
    IdRefColumn('articles_by_assoc.articles_by_assoc_id', name='article_id', primary_key=True)
)

class Person(Base):
    __tablename__ = 'people'
    id = IdColumn()
    name = Column(Text)
    blogs = relationship('Blog', backref='owner')
    posts = relationship('Post', backref='author')
    comments = relationship('Comment', backref='author')
    articles_by_assoc = relationship(
        "ArticleByAssoc",
        secondary=authors_articles_assoc,
        backref="authors"
    )
    article_associations = relationship(
        'ArticleAuthorAssociation',
        backref='author'
    )

class Blog(Base):
    __tablename__ = 'blogs'
    id = IdColumn()
    title = Column(Text)
    owner_id = IdRefColumn('people.id')
    posts = relationship('Post', backref='blog')


class Post(Base):
    __tablename__ = 'posts'
    id = IdColumn()
    title = Column(Text)
    content = Column(Text)
    published_at = Column(DateTime, nullable=False)
    blog_id = IdRefColumn('blogs.id')
    author_id = IdRefColumn('people.id', nullable=False)
    comments = relationship('Comment', backref = 'post')

class Comment(Base):
    __tablename__ = 'comments'
    comments_id = IdColumn()
    content = Column(Text)
    author_id = IdRefColumn('people.id')
    post_id = IdRefColumn('posts.id')

class ArticleByAssoc(Base):
    __tablename__ = 'articles_by_assoc'
    articles_by_assoc_id = IdColumn()
    title = Column(Text, nullable=False)
    content = Column(Text)
    published_at = Column(DateTime)

class ArticleAuthorAssociation(Base):
    __tablename__ = 'article_author_associations'
    article_author_associations_id = IdColumn()
    article_id = IdRefColumn(
        'articles_by_obj.articles_by_obj_id',
        nullable=False
    )
    author_id = IdRefColumn(
        'people.id',
        nullable=False
    )
    date_joined = Column(DateTime)
    __table_args__ = (
        UniqueConstraint('article_id', 'author_id'),
    )

class ArticleByObj(Base):
    __tablename__ = 'articles_by_obj'
    articles_by_obj_id = IdColumn()
    title = Column(Text, nullable=False)
    content = Column(Text)
    published_at = Column(DateTime)
    author_associations = relationship(
        'ArticleAuthorAssociation',
        backref='article'
    )
