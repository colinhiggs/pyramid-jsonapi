from cachetools import cached
from cachetools.keys import hashkey
from dataclasses import dataclass
from functools import partial
from pyramid_jsonapi.permissions import Targets, PermissionTarget
from pyramid_jsonapi.collection_view import CollectionViewBase


@dataclass
class Authoriser:
    view: CollectionViewBase

    def iterate_authorised_items(self, it, errors):
        return filter(partial(self.authorise_item, errors=errors), it)

    def authorise_item(self, item, errors):
        if item is None:
            return True
        perms = self.item_permissions(item)
        if not perms.id and errors is not None:
            view = self.view.view_instance(item.__class__)
            ref = f'{view.collection_name}[{view.item_id(item)}]'
            errors[ref] = 'GET id denied'
            return False
        return True

    def authorised_item(self, item, errors):
        if self.authorise_item(item, errors):
            return item
        return None

    def item_permissions_key(self, item):
        view = self.view.view_instance(item.__class__)
        return (
            view.collection_name,
            str(getattr(item, view.key_column.name))
        )

    @cached(cache={}, key=item_permissions_key)
    def item_permissions(self, item):
        view = self.view.view_instance(item.__class__)
        pf = view.permission_filter('get', Targets.item, 'alter_result')
        return pf(item, PermissionTarget(Targets.item))
