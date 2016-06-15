# pyramid-jsonapi

Create a [JSON-API](http://jsonapi.org/) standard api from a database using the sqlAlchemy ORM and pyramid framework.

# Status

New and still being developed. There are bugs: some known (see the [issues](https://github.com/colinhiggs/pyramid-jsonapi/issues) page), doubtless many unknown.

**Currently working on:** unit tests representing the specification (`test_spec.py`); fixing some bugs found via failed tests.

Right now it will take a typical sqlalchemy declarative-style models file and produce a working REST-ful web api conforming to the JSON-API standard, pretty much with the invocation of one function.

Functionality already added (works modulo bugs):

* `GET`ing, `PATCH`ing and `DELETE`ing individual resources.
* `GET`ing and `POST`ing to resource collections.
* `GET`ing related resources via `related` links.
* `GET`ing, `POST`ing, `PATCH`ing and `DELETE`ing `relationships` links - i.e. viewing and changing relationship linkage.
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
  # Create the routes and views automagically:
  jsonapi.create_jsonapi_using_magic_and_pixie_dust(
    config, models, lambda view: models.DBSession
  )
  # The third argument above should be a callable which accepts a CollectionView
  # instance as an argument and returns a database session. Notably the request
  # is available as view.request, so if you're doing something like this post
  # [https://metaclassical.com/what-the-zope-transaction-manager-means-to-me-and-you/]
  # you can return the per-request session. In this case we just return the
  # usual DBSession from the models module.

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

# Building the API at the Server End.

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
  jsonapi.create_jsonapi_using_magic_and_pixie_dust(config, models, callback)
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

# <a name="client"></a>Consuming the API from the Client End

## `GET` Resources

### Basic Fetching

#### A Collection

```bash
$ http GET http://localhost:6543/posts
```

```json
{
  "data": [
    {
      "type": "posts",
      "id": "1",
      "attributes": {
        "content": "something insightful",
        "published_at": "2015-01-01T00:00:00",
        "title": "post1: alice.main"
      },
      "links": {
        "self": "http://localhost:6543/posts/1"
      },
      "relationships": {
        "author": {
          "data": {
            "id": "1",
            "type": "people"
          },
          "links": {
            "related": "http://localhost:6543/posts/1/author",
            "self": "http://localhost:6543/posts/1/relationships/author"
          },
          "meta": {
            "direction": "MANYTOONE",
            "results": {}
          }
        },
        "blog": {
          "data": {
            "id": "1",
            "type": "blogs"
          },
          "links": {
            "related": "http://localhost:6543/posts/1/blog",
            "self": "http://localhost:6543/posts/1/relationships/blog"
          },
          "meta": {
            "direction": "MANYTOONE",
            "results": {}
          }
        },
        "comments": {
          "data": [],
          "links": {
            "related": "http://localhost:6543/posts/1/comments",
            "self": "http://localhost:6543/posts/1/relationships/comments"
          },
          "meta": {
            "direction": "ONETOMANY",
            "results": {
              "available": 0,
              "limit": 10,
              "returned": 0
            }
          }
        }
      }
    },
    "... 5 more results ..."
  ],
  "links": {
    "first": "http://localhost:6543/posts?sort=id&page%5Boffset%5D=0",
    "last": "http://localhost:6543/posts?sort=id&page%5Boffset%5D=0",
    "self": "http://localhost:6543/posts"
  },
  "meta": {
    "results": {
      "available": 6,
      "limit": 10,
      "offset": 0,
      "returned": 6
    }
  }
}  
```

Note that we have:
* `data` which is an array of comments objects, each with:
  * `attributes`, as expected
  * a `links` object with:
    * a `self` link
  * relationship objects for each relationship with:
    * `data` with resource identifiers for related objects
    * `self` and `related` links
    * some other information about the relationship in `meta`
* `links` with:
  * `self` and
  * `pagination` links
* `meta` with:
  * some extra information about the number of results returned.

#### A Single Resource

```bash
$ http GET http://localhost:6543/posts/1
```

Returns a single resource object in `data` and no pagination links.

```json
{
  "data": {
    "type": "posts",
    "id": "1",
    "attributes": {
      "content": "something insightful",
      "published_at": "2015-01-01T00:00:00",
      "title": "post1: alice.main"
    },
    "links": {
      "self": "http://localhost:6543/posts/1"
    },
    "relationships": {
      "author": {
        "data": {
          "id": "1",
          "type": "people"
        },
        "links": {
          "related": "http://localhost:6543/posts/1/author",
          "self": "http://localhost:6543/posts/1/relationships/author"
        },
        "meta": {
          "direction": "MANYTOONE",
          "results": {}
        }
      },
      "blog": {
        "data": {
          "id": "1",
          "type": "blogs"
        },
        "links": {
          "related": "http://localhost:6543/posts/1/blog",
          "self": "http://localhost:6543/posts/1/relationships/blog"
        },
        "meta": {
          "direction": "MANYTOONE",
          "results": {}
        }
      },
      "comments": {
        "data": [],
        "links": {
          "related": "http://localhost:6543/posts/1/comments",
          "self": "http://localhost:6543/posts/1/relationships/comments"
        },
        "meta": {
          "direction": "ONETOMANY",
          "results": {
            "available": 0,
            "limit": 10,
            "returned": 0
          }
        }
      }
    }
  },
  "links": {
    "self": "http://localhost:6543/posts/1"
  },
  "meta": {}
}
```

### Sparse Fieldsets

We can ask only for certain fields (attributes and relationships are collectively known as fields).

Use the `fields` parameter, parameterized by collection name (fields[collection]), with the value set as a comma separated list of field names.

So, to return only the title attribute and author relationship of each post:

```bash
$ http GET http://localhost:6543/posts?fields[posts]=title,author
```

The resulting json has a `data` element with a list of objects something like this:

```json
{
  "attributes": {
    "title": "post1: bob.second"
  },
  "id": "6",
  "links": {
    "self": "http://localhost:6543/posts/6"
  },
  "relationships": {
    "author": {
      "data": {
        "id": "2",
        "type": "people"
      },
      "links": {
        "related": "http://localhost:6543/posts/6/author",
        "self": "http://localhost:6543/posts/6/relationships/author"
      },
      "meta": {
        "direction": "MANYTOONE",
        "results": {}
      }
    }
  },
  "type": "posts"
}
```

### Sorting

You can specify a sorting attribute and order with the sort query parameter.

Sort posts by title:

```bash
$ http GET http://localhost:6543/posts?sort=title
```

and in reverse:

```bash
$ http GET http://localhost:6543/posts?sort=-title
```

Sorting by multiple attributes (e.g. `sort=title,content`) and sorting by attributes of related objects (`sort=author.name`) are not currently supported.

A sort on id is assumed unless the sort parameter is specified.

### Pagination

You can specify the pagination limit and offset:

```bash
$ http GET http://localhost:6543/posts?fields[posts]=title\&page[limit]=2\&page[offset]=2
```
We asked for only the `title` field above so that the results would be more compact...

```json
{
  "data": [
    {
      "attributes": {
        "title": "post1: alice.second"
      },
      "id": "3",
      "links": {
        "self": "http://localhost:6543/posts/3"
      },
      "relationships": {},
      "type": "posts"
    },
    {
      "attributes": {
        "title": "post1: bob.main"
      },
      "id": "4",
      "links": {
        "self": "http://localhost:6543/posts/4"
      },
      "relationships": {},
      "type": "posts"
    }
  ],
  "links": {
    "first": "http://localhost:6543/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=0",
    "last": "http://localhost:6543/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=4",
    "next": "http://localhost:6543/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=4",
    "prev": "http://localhost:6543/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=0",
    "self": "http://localhost:6543/posts?fields[posts]=title&page[limit]=2&page[offset]=2"
  },
  "meta": {
    "results": {
      "available": 6,
      "limit": 2,
      "offset": 2,
      "returned": 2
    }
  }
}
```

There's a default page limit which is used if the limit is not specified and a maximum limit that the server will allow. Both of these can be set in the ini file.

### Filtering

The JSON API spec doesn't say much about filtering syntax, other than that it should use the parameter key `filter`. In this implementation, we use syntax like the following:

```
filter[<attribute_spec>:<operator>]=<value>
```

where:
* `attribute_spec` is either a direct attribute name or a dotted path to an attribute via relationhips.
* `operator` is one of the list of supported operators ([#filter-ops](#filter-ops)).
* `value` is the value to match on.

#### <a name='filter-ops'></a> Filter Operators

* `eq`
* `ne`
* `startswith`
* `endswith`
* `contains`
* `lt`
* `gt`
* `le`
* `ge`
* `like` or `ilike`. Note that both of these use '*' in place of '%' to avoid much URL escaping.

#### Filter Examples

Find all the people with name 'alice':

```
http GET http://localhost:6543/people?filter[name:eq]=alice
```

Find all the posts published after 2015-01-03

```
http GET http://localhost:6543/posts?filter[published_at:gt]=2015-01-03
```

## `GET` a Single Resource
