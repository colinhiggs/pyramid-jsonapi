.. _client:

Consuming the API from the Client End
=====================================

GET-ing Resources
--------------------

A Collection
~~~~~~~~~~~~

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts


.. code-block:: json

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
          "self": "http://localhost:6543/api/posts/1"
        },
        "relationships": {
          "author": {
            "data": {
              "id": "1",
              "type": "people"
            },
            "links": {
              "related": "http://localhost:6543/api/posts/1/author",
              "self": "http://localhost:6543/api/posts/1/relationships/author"
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
              "related": "http://localhost:6543/api/posts/1/blog",
              "self": "http://localhost:6543/api/posts/1/relationships/blog"
            },
            "meta": {
              "direction": "MANYTOONE",
              "results": {}
            }
          },
          "comments": {
            "data": [],
            "links": {
              "related": "http://localhost:6543/api/posts/1/comments",
              "self": "http://localhost:6543/api/posts/1/relationships/comments"
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
      "first": "http://localhost:6543/api/posts?sort=id&page%5Boffset%5D=0",
      "last": "http://localhost:6543/api/posts?sort=id&page%5Boffset%5D=0",
      "self": "http://localhost:6543/api/posts"
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


Note that we have:

* ``data`` which is an array of posts objects, each with:

  * a ``type``, which is the collection name

  * an ``id``, which is the value of the primary key column (which may or may not be called ``id``)

  * ``attributes``, as expected

    * a ``links`` object with:

    * a ``self`` link

  * relationship objects for each relationship with:

    * ``data`` with resource identifiers for related objects

    * ``self`` and ``related`` links

    * some other information about the relationship in ``meta``

* ``links`` with:

  * ``self`` and

  * ``pagination`` links

* ``meta`` with:

  * some extra information about the number of results returned.

A Single Resource
~~~~~~~~~~~~~~~~~

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts/1

Returns a single resource object in ``data`` and no pagination links.

.. code-block:: json

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
        "self": "http://localhost:6543/api/posts/1"
      },
      "relationships": {
        "author": {
          "data": {
            "id": "1",
            "type": "people"
          },
          "links": {
            "related": "http://localhost:6543/api/posts/1/author",
            "self": "http://localhost:6543/api/posts/1/relationships/author"
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
            "related": "http://localhost:6543/api/posts/1/blog",
            "self": "http://localhost:6543/api/posts/1/relationships/blog"
          },
          "meta": {
            "direction": "MANYTOONE",
            "results": {}
          }
        },
        "comments": {
          "data": [],
          "links": {
            "related": "http://localhost:6543/api/posts/1/comments",
            "self": "http://localhost:6543/api/posts/1/relationships/comments"
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
      "self": "http://localhost:6543/api/posts/1"
    },
    "meta": {}
  }

Sparse Fieldsets
~~~~~~~~~~~~~~~~

We can ask only for certain fields (attributes and relationships are
collectively known as fields).

Use the ``fields`` parameter, parameterized by collection name
(fields[collection]), with the value set as a comma separated list of field
names.

So, to return only the title attribute and author relationship of each post:

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts?fields[posts]=title,author

The resulting json has a ``data`` element with a list of objects something like
this:

.. code-block:: json

  {
    "attributes": {
      "title": "post1: bob.second"
    },
    "id": "6",
    "links": {
      "self": "http://localhost:6543/api/posts/6"
    },
    "relationships": {
      "author": {
        "data": {
          "id": "2",
          "type": "people"
        },
        "links": {
          "related": "http://localhost:6543/api/posts/6/author",
          "self": "http://localhost:6543/api/posts/6/relationships/author"
        },
        "meta": {
          "direction": "MANYTOONE",
          "results": {}
        }
      }
    },
    "type": "posts"
  }

Sorting
~~~~~~~

You can specify a sorting attribute and order with the sort query parameter.

Sort posts by title:

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts?sort=title

and in reverse:

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts?sort=-title

Sorting by multiple attributes (e.g. ``sort=title,content``) and sorting by attributes of related objects (`sort=author.name`) are supported.

A sort on id is assumed unless the sort parameter is specified.

Pagination
~~~~~~~~~~

You can specify the pagination limit and offset:

.. code-block:: bash

  $ http GET http://localhost:6543/api/posts?fields[posts]=title\&page[limit]=2\&page[offset]=2

We asked for only the ``title`` field above so that the results would be more
compact...

.. code-block:: json

  {
    "data": [
      {
        "attributes": {
          "title": "post1: alice.second"
        },
        "id": "3",
        "links": {
          "self": "http://localhost:6543/api/posts/3"
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
          "self": "http://localhost:6543/api/posts/4"
        },
        "relationships": {},
        "type": "posts"
      }
    ],
    "links": {
      "first": "http://localhost:6543/api/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=0",
      "last": "http://localhost:6543/api/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=4",
      "next": "http://localhost:6543/api/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=4",
      "prev": "http://localhost:6543/api/posts?page%5Blimit%5D=2&sort=id&page%5Boffset%5D=0",
      "self": "http://localhost:6543/api/posts?fields[posts]=title&page[limit]=2&page[offset]=2"
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

There's a default page limit which is used if the limit is not specified and a
maximum limit that the server will allow. Both of these can be set in the ini
file.

Filtering
~~~~~~~~~

The JSON API spec doesn't say much about filtering syntax, other than that it
should use the parameter key ``filter``. In this implementation, we use syntax
like the following:

.. code::

  filter[<attribute_spec>:<operator>]=<value>

where:

* ``attribute_spec`` is either a direct attribute name or a dotted path to an
  attribute via relationhips (only one level of relationships is currently supported).

* ``operator`` is one of the list of supported operators (:ref:`search_filter_operators`).

* ``value`` is the value to match on.

This is simple and reasonably effective. It's a little awkward on readability though. If you feel that you have a syntax that is more readable, more powerful, easier to parse or has some other advantage, let me know - I'd be interested in any thoughts.

Search operators in sqlalchemy (called column comparators) must be registered before they are treated as valid for use in json-api filters. The procedure for registering them, and the list of those registered by default can be found in :ref:`search_filter_operators`.

Filter Examples
^^^^^^^^^^^^^^^

Find all the people with name 'alice':

.. code-block:: bash

  http GET http://localhost:6543/api/people?filter[name:eq]=alice

Find all the posts published after 2015-01-03:

.. code-block:: bash

  http GET http://localhost:6543/api/posts?filter[published_at:gt]=2015-01-03

Find all the posts with 'bob' somewhere in the title:

.. code-block:: bash

  http GET http://localhost:6543/api/posts?filter[title:like]=*bob*
