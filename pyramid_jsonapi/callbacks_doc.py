# pylint: skip-file


def after_serialise_object(view_instance, obj):
    """Called after a resource object is serialised, before it is returned.

    Use this callback to alter objects as they are serialised: perhaps merging
    information from other data sources, perhaps removing restricted information
    or denying access (raise an appropriate exception).

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        obj (dict): serialised object.

    Returns:
        dict: serialised resource object.
    """


def after_serialise_identifier(view_instance, identifier):
    """Called after a resource identifier is serialised, before it is returned.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        identifier (dict): serialised identifier.

    Returns:
        dict: serialised resource identifier.
    """


def after_get(view_instance, document):
    """Called just before view_instance.get() returns.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        document (dict): JSON-API top level document.

    Returns:
        dict: altered JSON-API top level document.
    """


def before_patch(view_instance, partial_object):
    """Called before a patch is applied.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        partial_object (dict): JSON-API patch object.

    Returns:
        dict: altered patch object.
    """


def before_delete(view_instance, db_item):
    """Called before an object is deleted.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        db_item: item returned by sqlalchemy query.
    """


def after_collection_get(view_instance, document):
    """Called just before view_instance.collection_get() returns.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        document (dict): JSON-API top level document.

    Returns:
        dict: altered JSON-API top level document.
    """


def before_collection_post(view_instance, obj):
    """Called before enacting view_instance.collection_post().

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        obj (dict): JSON-API object to be created.
    """


def after_related_get(view_instance, document):
    """Called before view_instance.related_get() returns.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        document (dict): JSON-API top level document.

    Returns:
        dict: altered JSON-API top level document.
    """


def after_relationships_get(view_instance, document):
    """Called before view_instance.relationships_get() returns.

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        document (dict): JSON-API top level document.

    Returns:
        dict: altered JSON-API top level document.
    """


def before_relationships_post(view_instance, data):
    """Called before enacting view_instance.relationships_post().

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        data (dict or list): resource identifier or a list of them.
    """


def before_relationships_patch(view_instance, data):
    """Called before enacting view_instance.relationships_patch().

    Args:
        view_instance (pyramid_jsonapi.CollectionViewBase): the current view
            instance.

        data (dict or list): resource identifier or a list of them.
    """


def before_relationships_delete(view_instance, parent_db_item):
    """
    """
