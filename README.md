# pyramid-jsonapi

Utilities for creating JSON-API apis from a database using the sqlAlchemy ORM and pyramid framework.

## Installation

Pretty basic right now: copy `jsonapi.py` into your PYTHONPATH or into your project.

## Quick preview

In `views.py`:
```python
import jsonapi
# Or 'from . import jsonapi' if you copied jsonapi directly into your project.
from . import models # Your models module.

jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)

```

Yes, there really is a method called "create_api_using_magic_and_pixie_dust". No, you don't *have* to call it that. If you are feeling more sensible you can use the synonym `autocreate_jsonapi()`.

## Usage

### Auto-creating a JSON-API

1. Create Some Models:

    ```python
    from sqlalchemy import (
      Column,
      BigInteger,
      Text,
      ForeignKey,
    )

    from sqlalchemy.ext.declarative import declarative_base

    from sqlalchemy.orm import (
        relationship,
        backref,
    )

    Base = declarative_base()

    # Nearly everything will need an id and most things will need to refer to
    # other id columns. Create convenience functions for those.
    IdType = BigInteger
    def IdColumn():
      '''Convenience function: the default Column for object ids.'''
      return Column(IdType, primary_key=True, autoincrement=True)
    def IdRefColumn(reference, *args, **kwargs):
      '''Convenience function: the default Column for references to object ids.'''
      return Column(IdType, ForeignKey(reference), *args, **kwargs)

    class Blog(Base):
      __tablename__ = 'blogs'
      id = IdColumn()
      title = Column(Text)
      posts = relationship('Post', backref='blog')

    class Post(Base):
      __tablename__ = 'posts'
      id = IdColumn()
      title = Column(text)
      content = Column(text)
      blog_id = IdRefColumn('blogs.id', nullable=False)
    ```

#### Auto-create Assumptions

1. Your models all inherit from a base class returned by sqlalchemy's `declarative-base()`.
1. Each model has a primary_key called 'id'.
1. You are happy to give your collection end-points the same name as the corresponding database table.
1. You have defined any relationships to exposed via the API using `sqlalchemy.orm.relationship() (or backref())`.

#### Customising auto-create

### Creating Individual JSON-API Resources from Models

#### Resource Creation On-the-fly

#### Decorating Class Definitions
