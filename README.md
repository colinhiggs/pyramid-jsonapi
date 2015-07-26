# pyramid-jsonapi

Utilities for creating JSON-API apis from a database using the sqlAlchemy ORM and pyramid framework.

## Quick preview

In `views.py`:
```python
import jsonapi
from . import models # Your models module.

jsonapi.create_jsonapi_using_magic_and_pixie_dust(models)

```

Yes, there really is a method called "create_api_using_magic_and_pixie_dust". No, you don't *have* to call it that. If you are feeling more sensible you can use the synonym `autocreate_jsonapi`.

## Installation

Pretty basic right now: copy `jsonapi.py` into your PYTHONPATH or into your project.
