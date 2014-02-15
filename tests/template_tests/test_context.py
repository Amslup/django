# coding: utf-8

from unittest import TestCase

from django.template import Context, RequestContext, Variable, VariableDoesNotExist
from django.template.context import RenderContext
from django.test.client import RequestFactory
from django.test.utils import override_settings


class ContextTests(TestCase):
    def test_context(self):
        c = Context({"a": 1, "b": "xyzzy"})
        self.assertEqual(c["a"], 1)
        self.assertEqual(c.push(), {})
        c["a"] = 2
        self.assertEqual(c["a"], 2)
        self.assertEqual(c.get("a"), 2)
        self.assertEqual(c.pop(), {"a": 2})
        self.assertEqual(c["a"], 1)
        self.assertEqual(c.get("foo", 42), 42)

        with c.push():
            c['a'] = 2
            self.assertEqual(c['a'], 2)
        self.assertEqual(c['a'], 1)

        with c.push(a=3):
            self.assertEqual(c['a'], 3)
        self.assertEqual(c['a'], 1)

    def test_resolve_on_context_method(self):
        # Regression test for #17778
        empty_context = Context()
        self.assertRaises(VariableDoesNotExist,
                Variable('no_such_variable').resolve, empty_context)
        self.assertRaises(VariableDoesNotExist,
                Variable('new').resolve, empty_context)
        self.assertEqual(Variable('new').resolve(Context({'new': 'foo'})), 'foo')

    def test_render_context(self):
        test_context = RenderContext({'fruit': 'papaya'})

        # Test that push() limits access to the topmost dict
        test_context.push()

        test_context['vegetable'] = 'artichoke'
        self.assertEqual(list(test_context), ['vegetable'])

        self.assertNotIn('fruit', test_context)
        with self.assertRaises(KeyError):
            test_context['fruit']
        self.assertIsNone(test_context.get('fruit'))

    def test_context_comparable(self):
        test_data = {'x': 'y', 'v': 'z', 'd': {'o': object, 'a': 'b'}}

        self.assertEquals(Context(test_data), Context(test_data))
