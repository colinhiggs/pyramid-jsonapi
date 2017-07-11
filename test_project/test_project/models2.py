'''Quick and dirty alternative models file for testing purposes.'''

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

Base = declarative_base()

IdType = BigInteger
def IdColumn():
    '''Convenience function: the default Column for object ids.'''
    return Column(IdType, primary_key=True, autoincrement=True)
def IdRefColumn(reference, *args, **kwargs):
    '''Convenience function: the default Column for references to object ids.'''
    return Column(IdType, ForeignKey(reference), *args, **kwargs)

class CompositeKey(Base):
    __tablename__ = 'people2'
    primary_one = IdColumn()
    primary_two = IdColumn()
    other_column = Column(Text)
