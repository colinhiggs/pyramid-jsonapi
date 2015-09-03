from sqlalchemy import (
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

class Person(Base):
    __tablename__ = 'people'
    id = IdColumn()
    name = Column(Text)
    blogs = relationship('Blog', backref='owner')
    posts = relationship('Post', backref='author')

class Blog(Base):
    __tablename__ = 'blogs'
    id = IdColumn()
    title = Column(Text)
    owner_id = IdRefColumn('people.id', nullable=False)
    posts = relationship('Post', backref='blog')


class Post(Base):
    __tablename__ = 'posts'
    id = IdColumn()
    title = Column(Text)
    content = Column(Text)
    published_at = Column(DateTime, nullable=False)
    blog_id = IdRefColumn('blogs.id', nullable=False)
    author_id = IdRefColumn('people.id', nullable=False)
