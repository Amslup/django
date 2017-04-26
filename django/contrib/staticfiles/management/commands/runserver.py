import warnings

from django.conf import settings
from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.core.management.commands.runserver import \
    Command as RunserverCommand
from django.utils.deprecation import RemovedInDjango30Warning


class Command(RunserverCommand):
    help = "Starts a lightweight Web server for development and also serves static files."

    def __init__(self, stdout=None, stderr=None, no_color=False):
        warnings.warn(
            "django.contrib.staticfiles.runserver.Command is deprecated in favor of"
            "django.contrib.staticfiles.middleware.WhiteNoiseMiddleware and core runserver"
            "django.core.management.commands.runserver.Command for serving static files."
            "Add django.contrib.staticfiles.runserver_nostatic above"
            "django.contrib.staticfiles app in INSTALLED_APPS to"
            "recover the core runserver command",
            RemovedInDjango30Warning,
            stacklevel=2,
        )
        super().__init__(stdout=stdout, stderr=stderr, no_color=no_color)

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            '--nostatic', action="store_false", dest='use_static_handler',
            help='Tells Django to NOT automatically serve static files at STATIC_URL.',
        )
        parser.add_argument(
            '--insecure', action="store_true", dest='insecure_serving',
            help='Allows serving static files even if DEBUG is False.',
        )

    def get_handler(self, *args, **options):
        """
        Return the static files serving handler wrapping the default handler,
        if static files should be served. Otherwise return the default handler.
        """
        handler = super().get_handler(*args, **options)
        use_static_handler = options['use_static_handler']
        insecure_serving = options['insecure_serving']
        if use_static_handler and (settings.DEBUG or insecure_serving):
            return StaticFilesHandler(handler)
        return handler
