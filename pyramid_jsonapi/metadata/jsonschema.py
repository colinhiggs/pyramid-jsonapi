import itertools


class ViewSchema:

    def __init__(self, view_class):
        self.view_class = view_class

    def properties(self):
        return {
            k: {'type': ['string', 'number']}
            for k in itertools.chain(
                self.view_class.attributes, self.view_class.hybrid_attributes
            )
        }

    def item(self, method='GET'):
        '''Return json-schema dictionary for an item from a collection
        '''
        schema = {
            'description': 'A resource object of type "{}".'.format(
                self.view_class.collection_name
            ),
            'type': 'object',
            'required': [
                'type',
                'id'
            ],
            'properties': {
                'type': {
                    'type': 'string',
                    'pattern': '^{}$'.format(
                        self.view_class.collection_name
                    ),
                },
                'id': {
                    'type': 'string'
                },
                'attributes': {
                    'type': 'object',
                    'properties': self.properties()
                }
            }
        }

        return schema
