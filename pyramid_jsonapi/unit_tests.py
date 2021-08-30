# Standard library imports.
from dataclasses import (
    dataclass,
)
from typing import (
    FrozenSet,
)
import unittest

# Third party imports.

# App imports.
# from pyramid_jsonapi.collection_view import (
#     CollectionViewBase,
# )
from pyramid_jsonapi.permissions import (
    Permission,
    TemplateMissmatch,
)


@dataclass
class TestView:

    all_attributes: FrozenSet[str]
    relationships: FrozenSet[str]


class Permissions(unittest.TestCase):

    def setUp(self):
        self.t = Permission(None, {'a1', 'a2', 'a3'}, {'r1', 'r2', 'r3'}, True)

    def test_template_from_view(self):
        v = TestView({'a1', 'a2', 'a3'}, {'r1', 'r2', 'r3'})  # pylint:disable=too-many-function-args
        t = Permission.template_from_view(v)
        self.assertEqual(t, self.t)

    def test_create_no_template(self):
        with self.assertRaises(TemplateMissmatch) as cm:
            Permission(None, {}, {})
            self.assertTrue(cm.exception.startswith("An id"))
        with self.assertRaises(TemplateMissmatch) as cm:
            Permission(None, None, {}, True)
            self.assertTrue(cm.exception.startswith("attributes"))
        with self.assertRaises(TemplateMissmatch) as cm:
            Permission(None, {}, None, True)
            self.assertTrue(cm.exception.startswith("relationships"))

    def test_create_empty(self):
        p = Permission(self.t)
        self.assertEqual(p.attributes, self.t.attributes)
        self.assertEqual(p.relationships, self.t.relationships)

    def test_create_with_attributes(self):
        p = Permission(self.t, attributes={'a1'})
        self.assertEqual(p.attributes, {'a1'})
        self.assertEqual(p.relationships, self.t.relationships)

    def test_create_with_rels(self):
        p = Permission(self.t, relationships={'r1'})
        self.assertEqual(p.attributes, self.t.attributes)
        self.assertEqual(p.relationships, {'r1'})

    def test_create_with_false_id(self):
        p = Permission(self.t, id=False)
        self.assertEqual(p.attributes, set())
        self.assertEqual(p.relationships, set())
        p = Permission(self.t, id=False, attributes={'a1'})
        self.assertEqual(p.attributes, {'a1'})

    def test_create_subtractive(self):
        self.assertEqual(
            Permission.subtractive(self.t, {'a3'}, {'r3'}),
            Permission(self.t, {'a1', 'a2'}, {'r1', 'r2'})
        )

    def test_create_with_bool_attributes(self):
        self.assertEqual(
            self.t.attributes, Permission(self.t, True, True).attributes
        )
        self.assertEqual(
            Permission(self.t, set(), set()),
            Permission(self.t, False, False)
        )

    def test_create_with_incorrect_atts(self):
        with self.assertRaises(KeyError):
            Permission(self.t, attributes={'bad'})

    def test_create_with_incorrect_rels(self):
        with self.assertRaises(KeyError):
            Permission(self.t, relationships={'bad'})

    def test_op_or(self):
        p1 = Permission(self.t, {'a1'}, {'r1'}, True)
        p2 = Permission(self.t, {'a2'}, {'r2'}, False)
        por = p1 | p2
        self.assertEqual(por, Permission(self.t, {'a1', 'a2'}, {'r1', 'r2'}, True))
        with self.assertRaises(TypeError) as cm:
            p1 | list()
        with self.assertRaises(TemplateMissmatch) as cm:
            p1 | Permission(p2)

    def test_op_and(self):
        p1 = Permission(self.t, {'a1', 'a2'}, {'r1', 'r2'}, True)
        p2 = Permission(self.t, {'a2'}, {'r2'}, False)
        pand = p1 & p2
        self.assertEqual(pand, Permission(self.t, {'a2'}, {'r2'}, False))
        with self.assertRaises(TypeError) as cm:
            p1 & list()
        with self.assertRaises(TemplateMissmatch) as cm:
            p1 & Permission(p2)

    def test_op_sub(self):
        p1 = Permission(self.t, {'a1', 'a2'}, {'r1', 'r2'}, True)
        p2 = Permission(self.t, {'a2'}, {'r2'}, True)
        psub = p1 - p2
        self.assertEqual(psub, Permission(self.t, {'a1'}, {'r1'}, True))
        with self.assertRaises(TypeError) as cm:
            p1 - list()
        with self.assertRaises(TemplateMissmatch) as cm:
            p1 - Permission(p2)
        with self.assertRaises(ValueError) as cm:
            p1 - Permission(self.t, {'a2'}, {'r2'}, False)
