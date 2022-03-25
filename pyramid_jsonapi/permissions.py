'''Implement classes representing permissions'''
# Standard library imports.
from enum import (
    Enum,
)
from dataclasses import (
    dataclass,
    field,
)
from functools import (
    lru_cache,
)
from typing import (
    FrozenSet,
    Any,
)


__all__ = (
    'Permission',
    'PermissionTarget',
    'Targets',
    'TemplateMissmatch',
)


class TemplateMissmatch(Exception):
    """
    Signal a missmatch in templates.
    """


class PermissionDenied(Exception):
    """
    Internal exception for permission denied.
    """


class Targets(Enum):
    """
    Possible PermissionTarget types.
    """
    collection = 1
    item = 2
    relationship = 3


@dataclass(eq=True, frozen=True)
class PermissionTarget:
    type: Targets
    name: str = None


@dataclass(eq=True, frozen=True)
class PermissionBase:
    """
    Base class for Permission. We define a separate base class so that
    Permission can use it as the type of its template attribute.
    """
    template: Any = None
    attributes: FrozenSet[str] = None
    relationships: FrozenSet[str] = None
    id: bool = None


@dataclass(eq=True, frozen=True)
class Permission(PermissionBase):
    """
    Represent all possible permissions.

    Attributes:
        template: a Template object representing possible attributes and
            relationships.
        attributes: a frozenset of allowed attributes.
        relationships: a frozenset of allowed relationships.
        id: a boolean representing whether or not operations involving the
            resource identifier are allowed (like existence or viewing, adding
            and deleting from relationships).
    """
    template: PermissionBase = field(repr=False, default=None)

    @staticmethod
    def _caclulate_attr_val(attr, curval, template_val, id_):
        if curval is None:
            # defaults
            if id_:
                return template_val
            else:
                return frozenset()
        elif curval is True:
            return template_val
        elif curval is False:
            return frozenset()
        else:
            return curval

    def __post_init__(self):
        if self.id is None:
            if self.template is None:
                raise TemplateMissmatch("An id must be supplied if template is None.")
            object.__setattr__(self, 'id', self.template.id)

        for attr in ('attributes', 'relationships'):
            curval = getattr(self, attr)
            if curval in (None, True, False) and self.template is None:
                raise TemplateMissmatch(f"{attr} must be supplied if template is None")
            template_val = getattr(self.template, attr, frozenset())
            object.__setattr__(
                self, attr,
                self._caclulate_attr_val(attr, curval, template_val, self.id)
            )
            if self.template is not None:
                remainder = getattr(self, attr) - template_val
                if remainder:
                    raise KeyError(f'Template does not have {attr} {remainder}')

    def __or__(self, other):
        if self.__class__ is not other.__class__:
            return NotImplemented
        if self.template != other.template:
            raise TemplateMissmatch("Templates must match for union/or.")
        return self.__class__(
            self.template,
            attributes=self.attributes | other.attributes,
            relationships=self.relationships | other.relationships,
            id=self.id | other.id,
        )

    def __and__(self, other):
        if self.__class__ is not other.__class__:
            return NotImplemented
        if self.template != other.template:
            raise TemplateMissmatch("Templates must match for intersect/and.")
        return self.__class__(
            self.template,
            attributes=self.attributes & other.attributes,
            relationships=self.relationships & other.relationships,
            id=self.id & other.id,
        )

    def __sub__(self, other):
        if self.__class__ is not other.__class__:
            return NotImplemented
        if self.template != other.template:
            raise TemplateMissmatch("Templates must match for minus.")
        if self.id != other.id:
            raise ValueError("Ids must match for minus.")
        return self.__class__(
            self.template,
            attributes=self.attributes - other.attributes,
            relationships=self.relationships - other.relationships,
            id=self.id,
        )

    @classmethod
    def from_pfilter(cls, template, value):
        """
        Construct a Permission object from the return value of a permission filter.
        """
        if isinstance(value, bool):
            return cls(template, id=value)
        elif isinstance(value, Permission):
            return value
        else:
            raise ValueError(
                f"Don't know how to construct a Permission from a {type(value)}"
            )

    @classmethod
    @lru_cache
    def from_template_cached(cls, template):
        """
        New instance from template with default atts and rels. Cached.
        """
        return cls(template)

    @classmethod
    def template_from_view(cls, view):
        return cls(
            None,
            frozenset(view.all_attributes),
            frozenset(view.relationships),
            True,
        )

    @classmethod
    def from_view(cls, view, attributes=None, relationships=None):
        """
        New instance using a view (instance or class) to get the template.
        """
        return cls(view.permission_template, attributes, relationships)

    @classmethod
    def subtractive(cls, template, attributes=set(), relationships=set()):
        """
        New instance by subtracting attributes and relationships from template.
        """
        return cls(
            template,
            attributes=template.attributes - attributes,
            relationships=template.relationships - relationships,
        )

    @classmethod
    def from_view_subtractive(cls, view, attributes=set(), relationships=set()):
        """
        New instance using view and subtracting atts and rels from full set.
        """
        return cls.subtractive(view.permission_template, attributes, relationships)
