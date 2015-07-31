from pyramid.response import Response
from pyramid.view import view_config

from sqlalchemy.exc import DBAPIError

from .models import (
    DBSession,
    )

@view_config(route_name='echo', match_param='type=params', renderer='json')
def echo_params(request):
    return {k: request.params.getall(k) for k in request.params.keys()}

@view_config(route_name='echo', match_param='type=request', renderer='json')
def echo_params(request):
    return {
        'method': request.method,
        'url': request.url,
        'headers': dict(request.headers),
        'body': request.body.decode('utf8'),
    }
