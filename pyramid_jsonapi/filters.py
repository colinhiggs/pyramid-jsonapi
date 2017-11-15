"""Classes and methods for handling filter operators."""

import re
from sqlalchemy.dialects.postgresql import JSONB


class FilterRegistry:
    """Registry of allowed filter operators.

    Attributes:
        data (dict): data store for filter op information.
    """

    def __init__(self):
        self.data = {}
        self.register_standard_filters()

    def register_standard_filters(self):
        """Register standard supported filter operators."""
        for comparator_name in (
                '__eq__',
                '__ne__',
                'startswith',
                'endswith',
                'contains',
                '__lt__',
                '__gt__',
                '__le__',
                '__ge__'
        ):
            self.register(comparator_name)
        # Transform '%' to '*' for like and ilike
        for comparator_name in (
                'like',
                'ilike'
        ):
            self.register(
                comparator_name,
                value_transform=lambda val: re.sub(r'\*', '%', val)
            )
        # JSONB specific operators
        for comparator_name in (
                'contains',
                'contained_by',
                'has_all',
                'has_any',
                'has_key'
        ):
            self.register(
                comparator_name,
                column_type=JSONB
            )

    def register(
            self,
            comparator_name,
            filter_name=None,
            value_transform=lambda val: val,
            column_type='__ALL__'
    ):
        """ Register a new filter operator.

        Args:
            comparator_name (str): name of sqlalchemy comparator method.
            filter_name(str): name of filter param in URL. Defaults to
                comparator_name with any occurrences of '__' removed (so '__eq__'
                defaults to 'eq', for example).
            value_transform (func): function taking the filter value as the only
                argument and returning a transformed value. Defaults to a
                function returning an unmodified value.
            column_type (class): type (class object, not name) for which this
                operator is to be registered. Defaults to '__ALL__' (the string)
                which makes the operator valid for all column types.
        """
        try:
            registry = self.data[column_type]
        except KeyError:
            registry = self.data[column_type] = {}
        registry[filter_name or comparator_name.replace('__', '')] = {
            'comparator_name': comparator_name,
            'value_transform': value_transform
        }

    def get_filter(self, column_type, filter_name):
        """Get dictionary of filter information.

        Args:
            column_type (class): type (class object, not name) of a Column.
            filter_name(str): name of filter param in URL.

        Returns:
            dict: information dictionary for filter. Type specific entry if it
                exists, entry from '__ALL__' if it does not.

        Raises:
            KeyError: if filter_name is not in the type specific or ALL sections.
        """
        try:
            return self.data[column_type][filter_name]
        except KeyError:
            return self.data['__ALL__'][filter_name]

    def valid_filter_names(self, column_types=None):
        """Return set of supported filter operator names."""
        ops = set()
        column_types = set(column_types or {k for k in self.data})
        column_types.add('__ALL__')
        for ctype in column_types:
            ops |= self.data[ctype].keys()
        return ops
