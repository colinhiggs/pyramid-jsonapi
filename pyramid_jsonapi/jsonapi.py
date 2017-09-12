"""A series of classes which store jsonapi in an internal dictionary,
and provide access through class attributes and helper methods."""


class Common():
    """Common class for magic attr <-> dict classes."""

    def __init__(self):
        """Create initial 'real' attributes."""
        # We override __setattr__ so must use the 'original' to create new attrs
        # Value modification is allowed (update, pop etc) but not replacement
        super().__setattr__('_jsonapi', {})
        super().__setattr__('resources', [])
        super().__setattr__('schema', {})

    def __setattr__(self, attr, value):
        """Update _jsonapi dict on attribute modification.
        Only allow modification of values for existing keys.
        """
        if attr == 'data':
            self.data_to_resources(value)
        elif attr in self._jsonapi:
            self._jsonapi[attr] = value
        else:
            super().__setattr__(attr, value)

    def __getattr__(self, attr):
        """Return dict key as if an attribute."""
        if attr == 'data':
            return self.data_from_resources()
        try:
            return self._jsonapi[attr]
        # Convert KeyError to AttributeError for consistency
        except KeyError:
            raise AttributeError("object has no attribute '{}'".format(attr))

    def as_dict(self):
        """Generate a dictionary representing the entire jsonapi object.
        Update 'data' to contain a single resource item, or list of items.
        """

        jsonapi = self._jsonapi.copy()
        try:
            jsonapi.update(self.data_from_resources())
        except AttributeError:
            pass
        return jsonapi

    def update(self, doc):
        """Update class from jsonapi document."""
        for key, val in doc.items():
            # data contains a single resources, or list of resources
            # Convert to Resource objects, then add to self.resources
            if key == "data":
                self.data_to_resources(val)
            else:
                self._jsonapi[key] = val


class Root(Common):
    """JSONAPI 'root' object."""

    def __init__(self, collection=False):
        """Extend _jsonapi to contain top-level keys."""
        super().__init__()
        self.collection = collection
        self._jsonapi.update({
            'links': {},
            'meta': {},
            'included': {},
        })

    def data_from_resources(self):
        """Generate 'data' part of jsonapi document from resources list."""
        data = []
        for resource in self.resources:
            data.append(resource.as_dict())

        if data and self.collection:
            return {'data': data}
        elif data:
            return {'data': data[0]}
        elif self.collection:
            return {'data': []}
        else:
            return {}

    def data_to_resources(self, data):
        """Convert 'data' part of jsonapi document to resource(s).
        Add resources to the resources list.
        """
        reslist = []
        if isinstance(data, list):
            reslist.extend(data)
        else:
            reslist.append(data)
        for item in reslist:
            res = Resource()
            res.update(item)
            self.resources.append(res)


class Resource(Common):
    """JSONAPI Resource object."""

    def __init__(self, view_class=None):
        """Extend _jsonapi to contain resource keys.
        If view_class provided, update attributes.
        Also create attributes with values as jsonschema in 'schema'.
        """
        super().__init__()
        self._jsonapi.update({
            'id': "",
            'type': "",
            'attributes': {},
            'links': {},
            'related': {},
            'relationships': {},
            'meta': {},
        })

        # Update class attributes with sourced data
        if view_class:
            self.type = view_class.collection_name
            # TODO(mrichar1): Convert this to jsonschema from sqlalchemy type constraints
            self.schema = view_class.attributes
            self.attributes = dict.fromkeys(view_class.attributes, None)
