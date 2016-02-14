import datetime
from calendar import timegm
from functools import wraps

from django.contrib.sites.shortcuts import get_current_site
from django.core import urlresolvers
from django.core.paginator import EmptyPage, PageNotAnInteger
from django.http import Http404
from django.template.response import TemplateResponse
from django.utils.http import http_date
from django.contrib.sitemaps import sitemap_time


def x_robots_tag(func):
    @wraps(func)
    def inner(request, *args, **kwargs):
        response = func(request, *args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, noodp, noarchive'
        return response
    return inner


@x_robots_tag
def index(request, sitemaps,
          template_name='sitemap_index.xml', content_type='application/xml',
          sitemap_url_name='django.contrib.sitemaps.views.sitemap'):

    req_protocol = request.scheme
    req_site = get_current_site(request)

    sites = []
    for section, site in sitemaps.items():
        if callable(site):
            site = site()
        protocol = req_protocol if site.protocol is None else site.protocol
        sitemap_url = urlresolvers.reverse(
            sitemap_url_name, kwargs={'section': section})
        absolute_url = '%s://%s%s' % (protocol, req_site.domain, sitemap_url)
        lastmod = sitemap_time(site.get_latest_lastmod())
        sites.append({'location': absolute_url, 'lastmod': lastmod})
        for page in range(2, site.paginator.num_pages + 1):
            sites.append({'location': '%s?p=%s' % (absolute_url, page), 'lastmod': lastmod})

    return TemplateResponse(request, template_name, {'sitemaps': sites},
                            content_type=content_type)


@x_robots_tag
def sitemap(request, sitemaps, section=None,
            template_name='sitemap.xml', content_type='application/xml'):

    req_protocol = request.scheme
    req_site = get_current_site(request)

    if section is not None:
        if section not in sitemaps:
            raise Http404("No sitemap available for section: %r" % section)
        maps = [sitemaps[section]]
    else:
        maps = sitemaps.values()
    page = request.GET.get("p", 1)

    urls = []
    for site in maps:
        try:
            if callable(site):
                site = site()
            urls.extend(site.get_urls(page=page, site=req_site,
                                      protocol=req_protocol))
        except EmptyPage:
            raise Http404("Page %s empty" % page)
        except PageNotAnInteger:
            raise Http404("No page '%s'" % page)
    response = TemplateResponse(request, template_name, {'urlset': urls},
                                content_type=content_type)
    if hasattr(site, 'latest_lastmod'):
        # if latest_lastmod is defined for site, set header so as
        # ConditionalGetMiddleware is able to send 304 NOT MODIFIED
        lastmod = site.latest_lastmod
        response['Last-Modified'] = http_date(
            timegm(
                lastmod.utctimetuple() if isinstance(lastmod, datetime.datetime)
                else lastmod.timetuple()
            )
        )
    return response
