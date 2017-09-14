import itertools
from pyramid_jsonapi.metadata import VIEWS


class JSONSchema():

    def __init__(self, api):
        self.views = [VIEWS(attr='jsonschema', route_name='', request_method='', renderer='')]
        self.api = api

    def jsonschema(self, view, context):
        return {"Made up schema": "True"}
