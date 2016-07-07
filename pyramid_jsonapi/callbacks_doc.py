def after_serialise_identifier(view_instance, identifier):
    '''Called after a resource identifier is serialised, before it is returned.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase):

        identifier (dict): serialised identifier.

    Returns:
        dict: serialised identifier.
    '''
