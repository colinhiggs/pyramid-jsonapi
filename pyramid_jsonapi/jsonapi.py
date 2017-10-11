"""A series of classes which store jsonapi in an internal dictionary,
and provide access through class attributes and helper methods."""


class Base():
    """Common class for magic attr <-> dict classes."""

    def __init__(self):
        """Create initial 'real' attributes.

        Attributes:
            _jsonapi (dict): JSONAPI document object.
            resources (list): List of associated Resource objects.
        """
        # We override __setattr__ so must use the 'original' to create new attrs
        # Value modification is allowed (update, pop etc) but not replacement
        super().__setattr__('_jsonapi', {})
        super().__setattr__('resources', [])

    def __setattr__(self, attr, value):
        """If attr is a key in _jsonapi, set it's value.
        Otherwise, set a class attribute as usual.
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
        """Generate a dictionary representing the entire JSONAPI object.
        Update 'data' to contain a single resource item, or list of items.

        Returns:
            dict: JSONAPI object.
        """

        jsonapi_dict = self._jsonapi.copy()
        if hasattr(self, 'data_from_resources'):
            resources = self.data_from_resources()
            if resources:
                jsonapi_dict.update(resources)

        # Only return keys which are in filter_keys
        return {k: v for k, v in jsonapi_dict.items() if k in self.filter_keys}

    def update(self, doc):
        """Update class from JSONAPI document.
        'data' keys will be converted to Resource objects and added to
        'resources' attribute.

        Args:
            doc (dict): JSONAPI object.
        """
        if doc:
            for key, val in doc.items():
                # data contains a single resources, or list of resources
                # Convert to Resource objects, then add to self.resources
                if key == "data":
                    self.data_to_resources(val)
                else:
                    self._jsonapi[key] = val


class Document(Base):
    """JSONAPI 'root' document object."""

    def __init__(self, collection=False):
        """Extend _jsonapi to contain top-level keys.

        Args:
            collection (bool): Is this document a collection, or a single item?
            filter_keys (dict): Keys to be returned when as_dict() is called.
        """
        super().__init__()
        self.collection = collection
        # filter_keys controls which keys are included in as_dict() output
        # It's also used to build the internal dictionary
        self.filter_keys = {
            'data': [],
            'included': [],
            'links': {},
            'meta': {},
        }
        self._jsonapi.update(self.filter_keys)

    def data_from_resources(self):
        """Generate 'data' part of jsonapi document from resources list.

        Returns:
            dict, list or None: JSONAPI 'data' resource element.
        """
        data = []
        for resource in self.resources:
            data.append(resource.as_dict())

        if data and self.collection:
            return {'data': data}
        elif data:
            return {'data': data[0]}
        elif self.collection:
            return {'data': []}

        return {'data': None}

    def data_to_resources(self, data):
        """Convert 'data' part of jsonapi document to resource(s).
        Add resources to the resources list.

        Args:
            data (dict): JSONAPI 'data' resource element.
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


class Resource(Base):
    """JSONAPI Resource object."""

    def __init__(self, view_class=None):
        """Extend _jsonapi to contain resource keys.
        If view_class provided, update attributes.

        Args:
            view_class (jsonapi.view_class): Resource data extracted from the view_class

        Attributes:
            filter_keys (dict): Keys to be returned when as_dict() is called.
        """
        super().__init__()
        self.filter_keys = {
            'id': "",
            'type': "",
            'attributes': {},
            'links': {},
            'related': {},
            'relationships': {},
            'meta': {},
        }
        self._jsonapi.update(self.filter_keys)

        # Update class attributes with sourced data
        if view_class:
            self.type = view_class.collection_name
            self.attributes = dict.fromkeys(view_class.attributes, None)
