# pyramid-jsonapi

Create a [JSON-API](http://jsonapi.org/) standard api from a database using the sqlAlchemy ORM and pyramid framework.

# Status

New and still being developed. There are bugs: some known (see the [issues](https://github.com/colinhiggs/pyramid-jsonapi/issues) page), doubtless many unknown.

Right now it will take a typical sqlalchemy declarative-style models file and produce a working REST-ful web api conforming to the JSON-API standard, pretty much with the invocation of one function.

Functionality already added (works modulo bugs):

* `GET`ing of resource collections and individual resources.
* `POST`ing new resources.
* `PATCH`ing existing resources.
* `DELETE`ing resources.
* There is no `PUT` in JSON-API.
* `links` section auto-populated with some standard links.
* `relationships` section auto-populated from relationships defined in sqlalchemy model.
* Pagination of collection gets via `page[]` parameters.
* Filtering of collection gets via `filter[]` parameters.
  * A good number of comparators are supported.
* Sorting of collection gets via `sort` parameter.
* Sparse field returns
  * via `fields[]` parameter and/or
  * limiting field visibility in the constructor.
* Included documents via `include` parameter.

I tend to keep track of TODOs in the [github issue list](https://github.com/colinhiggs/pyramid-jsonapi/issues). Biggies that don't work for now:

* Multiple views onto the same model (planned for some point in the future)
* Proper handling of many error cases.

Definitely at the stage where you can play with it; don't use it in production.

# Installation

Pretty basic right now: copy the directory jsonapi/ into your PYTHONPATH or into your project. There is only one file.

setup.py *should* work but has not really been tested.

A release worthy of some packaging should come soon.

# Quick preview

If you are happy with the defaults, you can get away with the following additions to the standard pyramid alchemy scaffold's top level `__init__.py`:

```python
import jsonapi
# Or 'from . import jsonapi' if you copied jsonapi directly into your project.

from . import models # Your models module.

# In the main function:
  # Use the standard JSON renderer...
  renderer = JSON()
  # ...so adding adapters works fine.
  renderer.add_adapter(datetime.date, datetime_adapter)
  config.add_renderer('json', renderer)
  config.add_renderer(None, renderer)
  # Create the routes and views automagically.
  jsonapi.create_jsonapi_using_magic_and_pixie_dust(config, models)
  # Routes and views are added imperatively, so no need for a scan - unless you
  # have defined other routes and views declaratively.
```

You should now have a working JSON-API.

Start the server:

```bash
$ pserv your_project/development.ini
```

Using the rather lovely [httpie](https://github.com/jkbrzt/httpie) to test:

```bash
$ http http://localhost:6543/people
```
```
HTTP/1.1 200 OK
Content-Length: 1387
Content-Type: application/vnd.api+json; charset=UTF-8
Date: Fri, 28 Aug 2015 20:22:46 GMT
Server: waitress

{
  "data": [
  {
    "attributes": {
      "name": "alice"
    },
    "id": "2",
    "links": {
      "self": "http://localhost:6543/people/2"
    },
    "relationships": {
    ...
  }
  ...
  ]
}
```

See `test_project/test_project/__init__.py` for a fully working `__init__` file.

You don't need a views.py unless you have some other routes and views.

Yes, there really is a method called `create_jsonapi_using_magic_and_pixie_dust()`. No, you don't *have* to call it that. If you are feeling more sensible you can use the synonym `create_jsonapi()`.

# Usage

## Auto-creating a JSON-API

More or less the same as the quick preview above. Spelled out in a bit more detail:

1. Create Some Models in the usual style:

    ```python

    class Person(Base):
      __tablename__ = 'people'
      id = Column(BigInteger, primary_key=True, autoincrement=True)
      name = Column(Text)
      blogs = relationship('Blog', backref='owner')
      posts = relationship('Post', backref='author')
    ```

1. Create the API end points from the model:

  ```python
  jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)
  ```

That's pretty much it.

### Auto-create Assumptions

1. Your model classes all inherit from a base class returned by sqlalchemy's `declarative-base()`.
1. Each model has a single primary_key column. This will be auto-detected and copied to an attribute called `_jsonapi_id`, so...
1. ... don't create any columns called `_jsonapi_id`.  
1. You are happy to give your collection end-points the same name as the corresponding database table (for now...).
1. You have defined any relationships to exposed via the API using `sqlalchemy.orm.relationship()` (or `backref()`).
1. You are happy to expose any so defined relationship via a relationship URL.

### Customising the Generated API

#### Selectively Passing Models for API Generation

Your database may have some tables which you do not wish to expose as collections in the generated API. You can be selective by:

* writing a models module with only the model classes you wish to expose; or
* [not yet] passing an iterable of model classes to `create_jsonapi_using_magic_and_pixie_dust()`.


If you need deeper customisation of your JSON-API, you will need to construct it using the building blocks that `create_api_using_magic_and_pixie_dust()` uses. Start with [create_resource()](#create_resource).

## Creating Individual JSON-API Resources from Models

### <a name="create_resource"></a>Resource Creation On-the-fly: `create_resource()`

#### `create_resource()` Parameters
