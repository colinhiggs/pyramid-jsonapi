"""A series of classes which store jsonapi in an internal dictionary,
and provide access through class attributes and helper methods."""


class Common():
    """Common class for magic attr <-> dict classes."""

    def __init__(self):
        """Create initial 'real' attributes."""
        # We override __setattr__ so must use the 'original' to create new attrs
        # Value modification is allowed (update, pop etc) but not replacement
        super().__setattr__('_jsonapi', {})
        super().__setattr__('resources', set())
        super().__setattr__('schema', {})

    def __setattr__(self, attr, value):
        """Update _jsonapi dict on attribute modification.
        Only allow modification of values for existing keys.
        """
        if attr in self._jsonapi:
            self._jsonapi[attr] = value
        else:
            super().__setattr__(attr, value)

    def __getattr__(self, attr):
        """Return dict key as if an attribute."""
        try:
            return self._jsonapi[attr]
        # Convert KeyError to AttributeError for consistency
        except KeyError:
            raise AttributeError("No such attribute")

    def add_resource(self, resource):
        """Helper method to prevent confusion with attr immutability."""
        if not isinstance(resource, Resource):
            raise TypeError("Resource {} is not of type {}".format(resource, Resource))
        self.resources.add(resource)

    def remove_resource(self, resource):
        """Helper method to prevent confusion with attr immutability."""
        if not isinstance(resource, Resource):
            raise TypeError("Resource {} is not of type {}".format(resource, Resource))
        self.resources.remove(resource)

    def as_dict(self):
        """Generate a dictionary representing the entire jsonapi object.
        Update 'data' to contain a single resource item, or list of items.
        """

        data = []
        for resource in self.resources:
            data.append(resource.as_dict())

        if data:
            # If existing list, append to it
            if isinstance(self._jsonapi['data'], list):
                    self._jsonapi['data'].extend(data)
            # If not a list, but contains an entry, needs to be a list
            elif self._jsonapi['data']:
                    # Insert at start of new data
                    data.insert(0, self._jsonapi['data'])
                    self._jsonapi['data'] = data
            #
            else:
                if len(data) > 1:
                    self._jsonapi['data'] = data
                else:
                    self._jsonapi['data'] = data[0]

        return self._jsonapi

    def update(self, res):
        self._jsonapi.update(res)

class Root(Common):
    """JSONAPI 'root' object."""

    def __init__(self):
        """Extend _jsonapi to contain top-level keys."""
        super().__init__()
        self._jsonapi.update({
            'data': {},
            'links': {},
            'meta': {},
        })


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
            self._resource['type'] = view_class.collection_name
            # TODO(mrichar1): Convert this to jsonschema from sqlalchemy type constraints
            self._resource['schema'] = view_class.attributes
            self._resource['attributes'] = dict.fromkeys(view_class.attributes, None)
