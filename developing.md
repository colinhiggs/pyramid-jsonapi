# Getting started

## Clone the repo:
Although you've quite possibly already done that if you're here...
```bash
git clone https://github.com/colinhiggs/pyramid-jsonapi.git
```

## Install `tox`

You need to install tox - either system-wide, or in it's own virtualenv:

```bash
python3 -mvenv toxenv
toxenv/bin/pip install tox
```

*Note*: This virtualenv only exists to deliver `tox`, *NOT* for development.



## Run `tox`

`tox` creates it's own virtualenvs for testing in `.tox/` which can be used for code testing and development.
These contain all of the dependencies for both the project and testing, as well as the local `pyramid-jsonapi`

```bash
toxenv/bin/tox
```

Hopefully the tests all passed!


## Try it Out

Begin by sourcing the tox virtualenv:

```bash
source .tox/py3/bin/activate`
```

### Create a test database

Mumble mumble hand-wave... poke postgresql to create a new test database owned by an appropriate role.

### Edit development.ini to match database and role details

The test project comes with the following sqlalchemy url:
```ini
sqlalchemy.url = postgresql://test:test@localhost/test
```
which assumes there is a database called test owned by a user called test with password test. Highly imaginative stuff.

### Start a server running
```bash
pserve test_project/development.ini
```

### Populate with test data
I use httpie [http://httpie.org/](http://httpie.org/) for manual poking and testing. Installing it gives you the command `http`.

development.ini turns on certain debug features. One of them is to generate some database manipulating endpoints.

To populate:
```bash
http http://localhost:6543/debug/populate
```

There are also 'drop' to drop all tables and 'reset' to do a drop and then populate.

The test data is defined in `test_project/test_project/test_data.json`

### Ask for something via the API
```bash
http --verbose GET http://localhost:6543/api/people/1
```

which results in some http conversation:

```
GET /people/1 HTTP/1.1
Accept: */*
Accept-Encoding: gzip, deflate, compress
Host: localhost:6543
User-Agent: HTTPie/0.8.0



HTTP/1.1 200 OK
Content-Length: 1236
Content-Type: application/vnd.api+json; charset=UTF-8
Date: Fri, 03 Jun 2016 12:07:09 GMT
Server: waitress
```

and the following JSON (listed here in a separate block so it will be coloured):

```json
{
    "data": {
        "attributes": {
            "name": "alice"
        },
        "id": "1",
        "links": {
            "self": "http://localhost:6543/people/1"
        },
        "relationships": {
            "blogs": {
                "data": [
                    {
                        "id": "1",
                        "type": "blogs"
                    },
                    {
                        "id": "2",
                        "type": "blogs"
                    }
                ],
                "links": {
                    "related": "http://localhost:6543/people/1/blogs",
                    "self": "http://localhost:6543/people/1/relationships/blogs"
                },
                "meta": {
                    "direction": "ONETOMANY",
                    "results": {
                        "available": 2,
                        "limit": 10,
                        "returned": 2
                    }
                }
            },
            "comments": {
                "data": [
                    {
                        "id": "1",
                        "type": "comments"
                    },
                    {
                        "id": "3",
                        "type": "comments"
                    }
                ],
                "links": {
                    "related": "http://localhost:6543/people/1/comments",
                    "self": "http://localhost:6543/people/1/relationships/comments"
                },
                "meta": {
                    "direction": "ONETOMANY",
                    "results": {
                        "available": 2,
                        "limit": 10,
                        "returned": 2
                    }
                }
            },
            "posts": {
                "data": [
                    {
                        "id": "1",
                        "type": "posts"
                    },
                    {
                        "id": "2",
                        "type": "posts"
                    },
                    {
                        "id": "3",
                        "type": "posts"
                    }
                ],
                "links": {
                    "related": "http://localhost:6543/people/1/posts",
                    "self": "http://localhost:6543/people/1/relationships/posts"
                },
                "meta": {
                    "direction": "ONETOMANY",
                    "results": {
                        "available": 3,
                        "limit": 10,
                        "returned": 3
                    }
                }
            }
        },
        "type": "people"
    },
    "links": {
        "self": "http://localhost:6543/people/1"
    },
    "meta": {
        "debug": {
            "accept_header": {},
            "atts": {
                "name": null
            },
            "includes": {},
            "qinfo_page": {}
        }
    }
}
```
That ugly debug information up there should be going away soon.
