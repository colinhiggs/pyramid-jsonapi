# pyramid-jsonapi

Utilities for creating JSON-API apis from a database using the sqlAlchemy ORM and pyramid framework.

## Installation

Pretty basic right now: copy the directory jsonapi/ into your PYTHONPATH or into your project.

## Quick preview

If you are happy with the defaults, you can get away with the following additions to the standard pyramid alchemy scaffold's top level `__init__.py`:

```python
import jsonapi
# Or 'from . import jsonapi' if you copied jsonapi directly into your project.

from . import models # Your models module.

# In the main function:
  renderer = jsonapi.JSONAPIFromSqlAlchemyRenderer()
  config.add_renderer('jsonapi', renderer)
  jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)
  # Make sure we scan the *jsonapi* package.
  config.scan(package=jsonapi)
```

See `test_project/test_project/__init.py` for a fully working file.

You don't need views.py unless you have some other routes and views.

Yes, there really is a method called "create_api_using_magic_and_pixie_dust". No, you don't *have* to call it that. If you are feeling more sensible you can use the synonym `create_jsonapi()`.

## Usage

### Auto-creating a JSON-API

1. Create Some Models:

    ```python
    
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
