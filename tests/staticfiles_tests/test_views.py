import posixpath
from urllib.parse import quote

from django.conf import settings
from django.test import ignore_warnings, override_settings
from django.utils.deprecation import RemovedInDjango30Warning

from .cases import StaticFilesTestCase, TestDefaults


@override_settings(ROOT_URLCONF='staticfiles_tests.urls.default')
class TestServeStatic(StaticFilesTestCase):
    """
    Test static asset serving view.
    """
    def _response(self, filepath):
        return self.client.get(quote(posixpath.join(settings.STATIC_URL, filepath)))

    def assertFileContains(self, filepath, text):
        self.assertContains(self._response(filepath), text)

    def assertFileNotFound(self, filepath):
        self.assertEqual(self._response(filepath).status_code, 404)


@ignore_warnings(category=RemovedInDjango30Warning)
@override_settings(DEBUG=False)
class TestServeDisabled(TestServeStatic):
    """
    Test serving static files disabled when DEBUG is False.
    """
    def test_disabled_serving(self):
        self.assertFileNotFound('test.txt')


@ignore_warnings(category=RemovedInDjango30Warning)
@override_settings(DEBUG=True)
class TestServeStaticWithDefaultURL(TestDefaults, TestServeStatic):
    """
    Test static asset serving view with manually configured URLconf.
    """


@ignore_warnings(category=RemovedInDjango30Warning)
@override_settings(DEBUG=True, ROOT_URLCONF='staticfiles_tests.urls.helper')
class TestServeStaticWithURLHelper(TestDefaults, TestServeStatic):
    """
    Test static asset serving view with staticfiles_urlpatterns helper.
    """
