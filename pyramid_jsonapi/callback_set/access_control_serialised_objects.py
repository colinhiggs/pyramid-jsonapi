"""Access Control Serialised Object."""

from pyramid.httpexceptions import (
    HTTPForbidden
)

from . import callback, hook

@hook
def before_append(view_class):
    """Tasks to perform before callback set is appended."""
    # Add HTTPForbidden to list of possible exceptions for endpoints/methods
    # where permission might be denied.
    eps = view_class.api.endpoint_data.endpoints['endpoints']
    try:
        forbidden = eps['item']['http_methods']['GET']['responses'][HTTPForbidden]
    except KeyError:
        forbidden = {'reason': []}
        eps['item']['http_methods']['GET']['responses'][HTTPForbidden] = forbidden
    forbidden['reason'].append('Access controls forbid this operation.')



@callback
def after_serialise_object(view, obj):  # pylint:disable=no-self-argument
    """Standard callback altering object to take account of permissions.

    Args:
        obj (dict): the object immediately after serialisation.

    Returns:
        dict: the object, possibly with some fields removed, or meta
        information indicating permission was denied to the whole object.
    """
    if view.allowed_object(obj):
        # Remove any forbidden fields that have been added by other
        # callbacks. Those from the model won't have been added in the first
        # place.

        # Keep track so we can tell the caller which ones were forbidden.
        forbidden = set()
        for attr in ('attributes', 'relationships'):
            if hasattr(obj, attr):
                new = {}
                for name, val in getattr(obj, attr).items():
                    if name in view.allowed_fields:
                        new[name] = val
                    else:
                        forbidden.add(name)
                setattr(obj, attr, new)
        # Now add all the forbidden fields from the model to the forbidden
        # list. They don't need to be removed from the serialised object
        # because they should not have been added in the first place.
        for field in view.requested_field_names:
            if field not in view.allowed_fields:
                forbidden.add(field)
        if not hasattr(obj, 'meta'):
            obj.meta = {}
        obj.meta['forbidden_fields'] = list(forbidden)
    else:
        obj.meta = {
            'errors': [
                {
                    'code': 403,
                    'title': 'Forbidden',
                    'detail': 'No permission to view {}/{}.'.format(
                        obj.type, obj.id
                    )
                }
            ]
        }
    return obj

@callback
def after_get(view, ret):  # pylint:disable=unused-argument, no-self-argument, no-self-use
    """Standard callback throwing 403 (Forbidden) based on information in meta.

    Args:
        ret (jsonapi.Document): object which would have been returned from get().

    Returns:
        jsonapi.Document: the same object if an error has not been raised.

    Raises:
        HTTPForbidden
    """
    obj = ret
    print('*****************************************************')
    print(obj.data['data']['meta'])
    print('*****************************************************')
    errors = []
    try:
        errors = obj.data['data']['meta']['errors']
    except KeyError:
        return ret
    for error in errors:
        if error['code'] == 403:
            raise HTTPForbidden(error['detail'])
    return ret
