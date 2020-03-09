from pyramid.httpexceptions import (
    HTTPUnsupportedMediaType,
    HTTPNotAcceptable,
    HTTPBadRequest,
)

stages = (
    'request',
    'document'
)


def request_headers(view, request):
    """Check that request headers comply with spec.

    Raises:
        HTTPUnsupportedMediaType
        HTTPNotAcceptable
    """
    # Spec says to reject (with 415) any request with media type
    # params.
    if len(request.headers.get('content-type', '').split(';')) > 1:
        raise HTTPUnsupportedMediaType(
            'Media Type parameters not allowed by JSONAPI ' +
            'spec (http://jsonapi.org/format).'
        )
    # Spec says throw 406 Not Acceptable if Accept header has no
    # application/vnd.api+json entry without parameters.
    jsonapi_accepts = view.get_jsonapi_accepts(request)
    if jsonapi_accepts and\
            'application/vnd.api+json' not in jsonapi_accepts:
        raise HTTPNotAcceptable(
            'application/vnd.api+json must appear with no ' +
            'parameters in Accepts header ' +
            '(http://jsonapi.org/format).'
        )

    return request


def request_valid_json(view, request):
    """Check that the body of any request is valid JSON.

    Raises:
        HTTPBadRequest
    """
    if request.content_length:
        try:
            request.json_body
        except ValueError:
            raise HTTPBadRequest("Body is not valid JSON.")

    return request


def request_validity(view, request):
    """Perform common request validity checks."""

    if request.content_length and view.api.settings.schema_validation:
        # Validate request JSON against the JSONAPI jsonschema
        view.api.metadata.JSONSchema.validate(request.json_body, request.method)

    # Spec says throw BadRequest if any include paths reference non
    # existent attributes or relationships.
    if view.bad_include_paths:
        raise HTTPBadRequest(
            "Bad include paths {}".format(
                view.bad_include_paths
            )
        )

    # Spec says set Content-Type to application/vnd.api+json.
    request.response.content_type = 'application/vnd.api+json'

    return request


def request_add_info(view, request):
    """Add information commonly used in view operations."""

    # Extract id and relationship from route, if provided
    view.obj_id = view.request.matchdict.get('id', None)
    view.relname = view.request.matchdict.get('relationship', None)
    return request


# stage_request = (
#     request_headers,
#     request_valid_json,
#     request_validity,
#     request_add_info,
# )

stage_request = (request_add_info,)


def document_self_link(view, doc):
    """Include a self link unless the method is PATCH."""
    if view.request.method != 'PATCH':
        selfie = {'self': view.request.url}
        if hasattr(doc, 'links'):
            doc.links.update(selfie)
        else:
            doc.links = selfie
    return doc


def document_debug_info(view, doc):
    """Potentially add some debug information."""
    if view.api.settings.debug_meta:
        debug = {
            'accept_header': {
                a: None for a in view.get_jsonapi_accepts(view.request)
            },
            'qinfo_page':
                view.collection_query_info(view.request)['_page'],
            'atts': {k: None for k in view.attributes.keys()},
            'includes': {
                k: None for k in view.requested_include_names()
            }
        }
        doc.meta.update({'debug': debug})
    return doc


stage_document = (document_self_link, document_debug_info)
