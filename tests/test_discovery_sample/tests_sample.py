import doctest
from unittest import TestCase

from freedom.test import SimpleTestCase, TestCase as FreedomTestCase

from . import doctests


class TestVanillaUnittest(TestCase):

    def test_sample(self):
        self.assertEqual(1, 1)


class TestFreedomTestCase(FreedomTestCase):

    def test_sample(self):
        self.assertEqual(1, 1)


class TestZimpleTestCase(SimpleTestCase):
    # Z is used to trick this test case to appear after Vanilla in default suite

    def test_sample(self):
        self.assertEqual(1, 1)


class EmptyTestCase(TestCase):
    pass


def load_tests(loader, tests, ignore):
    tests.addTests(doctest.DocTestSuite(doctests))
    return tests
