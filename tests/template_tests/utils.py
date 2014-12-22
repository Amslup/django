# coding: utf-8

from __future__ import unicode_literals

import functools

from django import template
from django.template import Library
from django.template.base import Context
from django.template.engine import Engine
from django.template.loader import get_template
from django.test.utils import override_settings
from django.utils import translation
from django.utils.encoding import python_2_unicode_compatible
from django.utils.safestring import mark_safe


def render(template_name, context=None):
    if context is None:
        context = {}

    t = get_template(template_name)
    with translation.override(context.get('LANGUAGE_CODE', 'en-us')):
        return t.render(Context(context))


def setup(templates, *args):
    """
    Runs test method multiple times in the following order:

    TEMPLATE_DEBUG      CACHED      TEMPLATE_STRING_IF_INVALID
    --------------      ------      --------------------------
    False               False
    False               True
    False               False       INVALID
    False               True        INVALID
    True                False
    True                True
    """

    for arg in args:
        templates.update(arg)

    # numerous tests make use of an inclusion tag
    # add this in here for simplicity
    templates["inclusion.html"] = "{{ result }}"

    def decorator(func):
        @register_test_tags
        @override_settings(TEMPLATE_LOADERS=[
            ('django.template.loaders.cached.Loader', [
                ('django.template.loaders.locmem.Loader', templates),
            ]),
        ])
        @functools.wraps(func)
        def inner(self):
            loader = Engine.get_default().template_loaders[0]

            func(self)
            func(self)
            loader.reset()

            with override_settings(TEMPLATE_STRING_IF_INVALID='INVALID'):
                func(self)
                func(self)
                loader.reset()

            with override_settings(TEMPLATE_DEBUG=True):
                func(self)
                func(self)
                loader.reset()
        return inner
    return decorator


# Custom template tag for tests

register = Library()


class EchoNode(template.Node):
    def __init__(self, contents):
        self.contents = contents

    def render(self, context):
        return ' '.join(self.contents)


@register.tag
def echo(parser, token):
    return EchoNode(token.contents.split()[1:])
register.tag('other_echo', echo)


@register.filter
def upper(value):
    return value.upper()


def register_test_tags(func):
    @functools.wraps(func)
    def inner(self):
        template.libraries['testtags'] = register
        func(self)
        del template.libraries['testtags']
    return inner


# Helper objects

class SomeException(Exception):
    silent_variable_failure = True


class SomeOtherException(Exception):
    pass


class ShouldNotExecuteException(Exception):
    pass


class SomeClass:
    def __init__(self):
        self.otherclass = OtherClass()

    def method(self):
        return 'SomeClass.method'

    def method2(self, o):
        return o

    def method3(self):
        raise SomeException

    def method4(self):
        raise SomeOtherException

    def method5(self):
        raise TypeError

    def __getitem__(self, key):
        if key == 'silent_fail_key':
            raise SomeException
        elif key == 'noisy_fail_key':
            raise SomeOtherException
        raise KeyError

    @property
    def silent_fail_attribute(self):
        raise SomeException

    @property
    def noisy_fail_attribute(self):
        raise SomeOtherException

    @property
    def attribute_error_attribute(self):
        raise AttributeError


class OtherClass:
    def method(self):
        return 'OtherClass.method'


class TestObj(object):
    def is_true(self):
        return True

    def is_false(self):
        return False

    def is_bad(self):
        raise ShouldNotExecuteException()


class SilentGetItemClass(object):
    def __getitem__(self, key):
        raise SomeException


class SilentAttrClass(object):
    def b(self):
        raise SomeException
    b = property(b)


@python_2_unicode_compatible
class UTF8Class:
    "Class whose __str__ returns non-ASCII data on Python 2"
    def __str__(self):
        return 'ŠĐĆŽćžšđ'


# These two classes are used to test auto-escaping of unicode output.
@python_2_unicode_compatible
class UnsafeClass:
    def __str__(self):
        return 'you & me'


@python_2_unicode_compatible
class SafeClass:
    def __str__(self):
        return mark_safe('you &gt; me')
