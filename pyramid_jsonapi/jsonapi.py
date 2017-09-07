class Root():
    """JSONAPI 'root'."""

    def __init__(self):
        self.data = {}
        self.links = {}
        self.meta = {}
        self.resources = []

    def as_dict(self):
        """Create dictionary from class atributes."""

        if len(self.resources) > 1:
            self.data = []
            for resource in self.resources:
                self.data.append(resource.__dict__)
        elif len(self.resources) == 1:
            self.data = self.resources[0].__dict__

        return {"data": self.data,
                "links": self.links,
                "meta": self.meta}

    def add_resource(self, resource):
        self.resources.append(resource)


class Resource():
    """JSONAPI Resource."""

    def __init__(self, view_class=None):
        self.id = ""
        self.type = ""
        self.attributes = {}
        self.links = {}
        self.related = {}
        self.relationships = {}
        self.meta = {}

        # Update class attributes with sourced data
        if view_class:
            self.type = view_class.collection_name
            self.attributes = dict.fromkeys(view_class.attributes, None)
