from __future__ import unicode_literals

import datetime
from xml.dom import minidom

from django.contrib.sites.models import Site
from django.contrib.syndication import views
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.test.utils import requires_tz_support
from django.utils import timezone
from django.utils.feedgenerator import rfc2822_date, rfc3339_date

from .models import Entry

try:
    import pytz
except ImportError:
    pytz = None

TZ = timezone.get_default_timezone()


class FeedTestCase(TestCase):
    fixtures = ['feeddata.json']

    def setUp(self):
        # Django cannot deal with very old dates when pytz isn't installed.
        if pytz is None:
            old_entry = Entry.objects.get(pk=1)
            old_entry.updated = datetime.datetime(1980, 1, 1, 12, 30)
            old_entry.published = datetime.datetime(1986, 9, 25, 20, 15, 00)
            old_entry.save()

    def assertChildNodes(self, elem, expected):
        actual = set(n.nodeName for n in elem.childNodes)
        expected = set(expected)
        self.assertEqual(actual, expected)

    def assertChildNodeContent(self, elem, expected):
        for k, v in expected.items():
            self.assertEqual(
                elem.getElementsByTagName(k)[0].firstChild.wholeText, v)

    def assertCategories(self, elem, expected):
        self.assertEqual(set(i.firstChild.wholeText for i in elem.childNodes if i.nodeName == 'category'), set(expected))

######################################
# Feed view
######################################


@override_settings(ROOT_URLCONF='syndication_tests.urls')
class SyndicationFeedTest(FeedTestCase):
    """
    Tests for the high-level syndication feed framework.
    """
    @classmethod
    def setUpClass(cls):
        super(SyndicationFeedTest, cls).setUpClass()
        # This cleanup is necessary because contrib.sites cache
        # makes tests interfere with each other, see #11505
        Site.objects.clear_cache()

    def test_rss2_feed(self):
        """
        Test the structure and content of feeds generated by Rss201rev2Feed.
        """
        response = self.client.get('/syndication/rss2/')
        doc = minidom.parseString(response.content)

        # Making sure there's only 1 `rss` element and that the correct
        # RSS version was specified.
        feed_elem = doc.getElementsByTagName('rss')
        self.assertEqual(len(feed_elem), 1)
        feed = feed_elem[0]
        self.assertEqual(feed.getAttribute('version'), '2.0')

        # Making sure there's only one `channel` element w/in the
        # `rss` element.
        chan_elem = feed.getElementsByTagName('channel')
        self.assertEqual(len(chan_elem), 1)
        chan = chan_elem[0]

        # Find the last build date
        d = Entry.objects.latest('published').published
        last_build_date = rfc2822_date(timezone.make_aware(d, TZ))

        self.assertChildNodes(chan, ['title', 'link', 'description', 'language', 'lastBuildDate', 'item', 'atom:link', 'ttl', 'copyright', 'category'])
        self.assertChildNodeContent(chan, {
            'title': 'My blog',
            'description': 'A more thorough description of my blog.',
            'link': 'http://example.com/blog/',
            'language': 'en',
            'lastBuildDate': last_build_date,
            'ttl': '600',
            'copyright': 'Copyright (c) 2007, Sally Smith',
        })
        self.assertCategories(chan, ['python', 'django'])

        # Ensure the content of the channel is correct
        self.assertChildNodeContent(chan, {
            'title': 'My blog',
            'link': 'http://example.com/blog/',
        })

        # Check feed_url is passed
        self.assertEqual(
            chan.getElementsByTagName('atom:link')[0].getAttribute('href'),
            'http://example.com/syndication/rss2/'
        )

        # Find the pubdate of the first feed item
        d = Entry.objects.get(pk=1).published
        pub_date = rfc2822_date(timezone.make_aware(d, TZ))

        items = chan.getElementsByTagName('item')
        self.assertEqual(len(items), Entry.objects.count())
        self.assertChildNodeContent(items[0], {
            'title': 'My first entry',
            'description': 'Overridden description: My first entry',
            'link': 'http://example.com/blog/1/',
            'guid': 'http://example.com/blog/1/',
            'pubDate': pub_date,
            'author': 'test@example.com (Sally Smith)',
        })
        self.assertCategories(items[0], ['python', 'testing'])
        for item in items:
            self.assertChildNodes(item, ['title', 'link', 'description', 'guid', 'category', 'pubDate', 'author'])
            # Assert that <guid> does not have any 'isPermaLink' attribute
            self.assertIsNone(item.getElementsByTagName(
                'guid')[0].attributes.get('isPermaLink'))

    def test_rss2_feed_guid_permalink_false(self):
        """
        Test if the 'isPermaLink' attribute of <guid> element of an item
        in the RSS feed is 'false'.
        """
        response = self.client.get(
            '/syndication/rss2/guid_ispermalink_false/')
        doc = minidom.parseString(response.content)
        chan = doc.getElementsByTagName(
            'rss')[0].getElementsByTagName('channel')[0]
        items = chan.getElementsByTagName('item')
        for item in items:
            self.assertEqual(
                item.getElementsByTagName('guid')[0].attributes.get(
                    'isPermaLink').value, "false")

    def test_rss2_feed_guid_permalink_true(self):
        """
        Test if the 'isPermaLink' attribute of <guid> element of an item
        in the RSS feed is 'true'.
        """
        response = self.client.get(
            '/syndication/rss2/guid_ispermalink_true/')
        doc = minidom.parseString(response.content)
        chan = doc.getElementsByTagName(
            'rss')[0].getElementsByTagName('channel')[0]
        items = chan.getElementsByTagName('item')
        for item in items:
            self.assertEqual(
                item.getElementsByTagName('guid')[0].attributes.get(
                    'isPermaLink').value, "true")

    def test_rss091_feed(self):
        """
        Test the structure and content of feeds generated by RssUserland091Feed.
        """
        response = self.client.get('/syndication/rss091/')
        doc = minidom.parseString(response.content)

        # Making sure there's only 1 `rss` element and that the correct
        # RSS version was specified.
        feed_elem = doc.getElementsByTagName('rss')
        self.assertEqual(len(feed_elem), 1)
        feed = feed_elem[0]
        self.assertEqual(feed.getAttribute('version'), '0.91')

        # Making sure there's only one `channel` element w/in the
        # `rss` element.
        chan_elem = feed.getElementsByTagName('channel')
        self.assertEqual(len(chan_elem), 1)
        chan = chan_elem[0]
        self.assertChildNodes(chan, ['title', 'link', 'description', 'language', 'lastBuildDate', 'item', 'atom:link', 'ttl', 'copyright', 'category'])

        # Ensure the content of the channel is correct
        self.assertChildNodeContent(chan, {
            'title': 'My blog',
            'link': 'http://example.com/blog/',
        })
        self.assertCategories(chan, ['python', 'django'])

        # Check feed_url is passed
        self.assertEqual(
            chan.getElementsByTagName('atom:link')[0].getAttribute('href'),
            'http://example.com/syndication/rss091/'
        )

        items = chan.getElementsByTagName('item')
        self.assertEqual(len(items), Entry.objects.count())
        self.assertChildNodeContent(items[0], {
            'title': 'My first entry',
            'description': 'Overridden description: My first entry',
            'link': 'http://example.com/blog/1/',
        })
        for item in items:
            self.assertChildNodes(item, ['title', 'link', 'description'])
            self.assertCategories(item, [])

    def test_atom_feed(self):
        """
        Test the structure and content of feeds generated by Atom1Feed.
        """
        response = self.client.get('/syndication/atom/')
        feed = minidom.parseString(response.content).firstChild

        self.assertEqual(feed.nodeName, 'feed')
        self.assertEqual(feed.getAttribute('xmlns'), 'http://www.w3.org/2005/Atom')
        self.assertChildNodes(feed, ['title', 'subtitle', 'link', 'id', 'updated', 'entry', 'rights', 'category', 'author'])
        for link in feed.getElementsByTagName('link'):
            if link.getAttribute('rel') == 'self':
                self.assertEqual(link.getAttribute('href'), 'http://example.com/syndication/atom/')

        entries = feed.getElementsByTagName('entry')
        self.assertEqual(len(entries), Entry.objects.count())
        for entry in entries:
            self.assertChildNodes(entry, [
                'title',
                'link',
                'id',
                'summary',
                'category',
                'updated',
                'published',
                'rights',
                'author',
            ])
            summary = entry.getElementsByTagName('summary')[0]
            self.assertEqual(summary.getAttribute('type'), 'html')

    def test_atom_feed_published_and_updated_elements(self):
        """
        Test that the published and updated elements are not
        the same and now adhere to RFC 4287.
        """
        response = self.client.get('/syndication/atom/')
        feed = minidom.parseString(response.content).firstChild
        entries = feed.getElementsByTagName('entry')

        published = entries[0].getElementsByTagName('published')[0].firstChild.wholeText
        updated = entries[0].getElementsByTagName('updated')[0].firstChild.wholeText

        self.assertNotEqual(published, updated)

    def test_latest_post_date(self):
        """
        Test that both the published and updated dates are
        considered when determining the latest post date.
        """
        # this feed has a `published` element with the latest date
        response = self.client.get('/syndication/atom/')
        feed = minidom.parseString(response.content).firstChild
        updated = feed.getElementsByTagName('updated')[0].firstChild.wholeText

        d = Entry.objects.latest('published').published
        latest_published = rfc3339_date(timezone.make_aware(d, TZ))

        self.assertEqual(updated, latest_published)

        # this feed has an `updated` element with the latest date
        response = self.client.get('/syndication/latest/')
        feed = minidom.parseString(response.content).firstChild
        updated = feed.getElementsByTagName('updated')[0].firstChild.wholeText

        d = Entry.objects.exclude(pk=5).latest('updated').updated
        latest_updated = rfc3339_date(timezone.make_aware(d, TZ))

        self.assertEqual(updated, latest_updated)

    def test_custom_feed_generator(self):
        response = self.client.get('/syndication/custom/')
        feed = minidom.parseString(response.content).firstChild

        self.assertEqual(feed.nodeName, 'feed')
        self.assertEqual(feed.getAttribute('django'), 'rocks')
        self.assertChildNodes(feed, ['title', 'subtitle', 'link', 'id', 'updated', 'entry', 'spam', 'rights', 'category', 'author'])

        entries = feed.getElementsByTagName('entry')
        self.assertEqual(len(entries), Entry.objects.count())
        for entry in entries:
            self.assertEqual(entry.getAttribute('bacon'), 'yum')
            self.assertChildNodes(entry, [
                'title',
                'link',
                'id',
                'summary',
                'ministry',
                'rights',
                'author',
                'updated',
                'published',
                'category',
            ])
            summary = entry.getElementsByTagName('summary')[0]
            self.assertEqual(summary.getAttribute('type'), 'html')

    def test_title_escaping(self):
        """
        Tests that titles are escaped correctly in RSS feeds.
        """
        response = self.client.get('/syndication/rss2/')
        doc = minidom.parseString(response.content)
        for item in doc.getElementsByTagName('item'):
            link = item.getElementsByTagName('link')[0]
            if link.firstChild.wholeText == 'http://example.com/blog/4/':
                title = item.getElementsByTagName('title')[0]
                self.assertEqual(title.firstChild.wholeText, 'A &amp; B &lt; C &gt; D')

    def test_naive_datetime_conversion(self):
        """
        Test that datetimes are correctly converted to the local time zone.
        """
        # Naive date times passed in get converted to the local time zone, so
        # check the received zone offset against the local offset.
        response = self.client.get('/syndication/naive-dates/')
        doc = minidom.parseString(response.content)
        updated = doc.getElementsByTagName('updated')[0].firstChild.wholeText

        d = Entry.objects.latest('published').published
        latest = rfc3339_date(timezone.make_aware(d, TZ))

        self.assertEqual(updated, latest)

    def test_aware_datetime_conversion(self):
        """
        Test that datetimes with timezones don't get trodden on.
        """
        response = self.client.get('/syndication/aware-dates/')
        doc = minidom.parseString(response.content)
        published = doc.getElementsByTagName('published')[0].firstChild.wholeText
        self.assertEqual(published[-6:], '+00:42')

    @requires_tz_support
    def test_feed_last_modified_time_naive_date(self):
        """
        Tests the Last-Modified header with naive publication dates.
        """
        response = self.client.get('/syndication/naive-dates/')
        self.assertEqual(response['Last-Modified'], 'Tue, 26 Mar 2013 01:00:00 GMT')

    def test_feed_last_modified_time(self):
        """
        Tests the Last-Modified header with aware publication dates.
        """
        response = self.client.get('/syndication/aware-dates/')
        self.assertEqual(response['Last-Modified'], 'Mon, 25 Mar 2013 19:18:00 GMT')

        # No last-modified when feed has no item_pubdate
        response = self.client.get('/syndication/no_pubdate/')
        self.assertFalse(response.has_header('Last-Modified'))

    def test_feed_url(self):
        """
        Test that the feed_url can be overridden.
        """
        response = self.client.get('/syndication/feedurl/')
        doc = minidom.parseString(response.content)
        for link in doc.getElementsByTagName('link'):
            if link.getAttribute('rel') == 'self':
                self.assertEqual(link.getAttribute('href'), 'http://example.com/customfeedurl/')

    def test_secure_urls(self):
        """
        Test URLs are prefixed with https:// when feed is requested over HTTPS.
        """
        response = self.client.get('/syndication/rss2/', **{
            'wsgi.url_scheme': 'https',
        })
        doc = minidom.parseString(response.content)
        chan = doc.getElementsByTagName('channel')[0]
        self.assertEqual(
            chan.getElementsByTagName('link')[0].firstChild.wholeText[0:5],
            'https'
        )
        atom_link = chan.getElementsByTagName('atom:link')[0]
        self.assertEqual(atom_link.getAttribute('href')[0:5], 'https')
        for link in doc.getElementsByTagName('link'):
            if link.getAttribute('rel') == 'self':
                self.assertEqual(link.getAttribute('href')[0:5], 'https')

    def test_item_link_error(self):
        """
        Test that an ImproperlyConfigured is raised if no link could be found
        for the item(s).
        """
        self.assertRaises(ImproperlyConfigured,
                          self.client.get,
                          '/syndication/articles/')

    def test_template_feed(self):
        """
        Test that the item title and description can be overridden with
        templates.
        """
        response = self.client.get('/syndication/template/')
        doc = minidom.parseString(response.content)
        feed = doc.getElementsByTagName('rss')[0]
        chan = feed.getElementsByTagName('channel')[0]
        items = chan.getElementsByTagName('item')

        self.assertChildNodeContent(items[0], {
            'title': 'Title in your templates: My first entry\n',
            'description': 'Description in your templates: My first entry\n',
            'link': 'http://example.com/blog/1/',
        })

    def test_template_context_feed(self):
        """
        Test that custom context data can be passed to templates for title
        and description.
        """
        response = self.client.get('/syndication/template_context/')
        doc = minidom.parseString(response.content)
        feed = doc.getElementsByTagName('rss')[0]
        chan = feed.getElementsByTagName('channel')[0]
        items = chan.getElementsByTagName('item')

        self.assertChildNodeContent(items[0], {
            'title': 'My first entry (foo is bar)\n',
            'description': 'My first entry (foo is bar)\n',
        })

    def test_add_domain(self):
        """
        Test add_domain() prefixes domains onto the correct URLs.
        """
        self.assertEqual(
            views.add_domain('example.com', '/foo/?arg=value'),
            'http://example.com/foo/?arg=value'
        )
        self.assertEqual(
            views.add_domain('example.com', '/foo/?arg=value', True),
            'https://example.com/foo/?arg=value'
        )
        self.assertEqual(
            views.add_domain('example.com', 'http://djangoproject.com/doc/'),
            'http://djangoproject.com/doc/'
        )
        self.assertEqual(
            views.add_domain('example.com', 'https://djangoproject.com/doc/'),
            'https://djangoproject.com/doc/'
        )
        self.assertEqual(
            views.add_domain('example.com', 'mailto:uhoh@djangoproject.com'),
            'mailto:uhoh@djangoproject.com'
        )
        self.assertEqual(
            views.add_domain('example.com', '//example.com/foo/?arg=value'),
            'http://example.com/foo/?arg=value'
        )
