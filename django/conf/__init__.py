"""
Settings and configuration for Django.

Values will be read from the module specified by the DJANGO_SETTINGS_MODULE environment
variable, and then from django.conf.global_settings; see the global settings file for
a list of all possible variables.
"""

import logging
import os
import time     # Needed for Windows
import types
import warnings
import itertools

from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.functional import LazyObject, empty
from django.utils import importlib, six
from django.utils.module_loading import import_by_path


class BaseSettings(object):
    """
    Common logic for settings whether set by a module or by the user.
    """

    def __setattr__(self, name, value):
        if name in ("MEDIA_URL", "STATIC_URL") and value and not value.endswith('/'):
            raise ImproperlyConfigured("If set, %s must end with a slash" % name)
        elif name == "ALLOWED_INCLUDE_ROOTS" and isinstance(value, six.string_types):
            raise ValueError("The ALLOWED_INCLUDE_ROOTS setting must be set "
                             "to a tuple, not a string.")
        object.__setattr__(self, name, value)


class BaseSettingsCollector(object):
    """
    Common logic for collecting settings from a module or modules.
    """

    tuple_settings = ("INSTALLED_APPS", "TEMPLATE_DIRS")

    def collect_settings_from_modules(self, modules):
        return itertools.chain(*map(self.collect_settings_from_module, modules))

    def collect_settings_from_module(self, module):
        collected_settings = [(module, setting, self.normalize_setting(module, setting)) for
                              setting in dir(module) if setting == setting.upper()]

        return collected_settings

    def normalize_setting(self, module, setting):
        # Settings that should be converted into tuples if they're mistakenly entered
        # as strings.

        setting_value = getattr(module, setting)
        if setting in self.tuple_settings and \
                isinstance(setting_value, six.string_types):
            warnings.warn("The %s setting must be a tuple. Please fix your "
                          "settings, as auto-correction is now deprecated." % setting,
                          DeprecationWarning, stacklevel=2)
            return (setting_value,)  # In case the user forgot the comma.

        return setting_value

    def collect(self, sources):
        return []


class SettingsCollector(BaseSettingsCollector):
    """
    The default implementation for collecting settings from a module or modules.
    """

    def collect(self, sources):
        return self.collect_settings_from_modules(sources)


class BaseSettingsSourcesLoader(object):
    def load(self):
        raise ImproperlyConfigured(self.get_error_message())

    def get_error_message(self, *args, **kwargs):
        return "SettingsSourcesLoader is not implemented."


class SettingsSourcesLoader(BaseSettingsSourcesLoader):
    """
    The default implementation for loading settings from sources.
    Loads the global settings and the module specified in the DJANGO_SETTINGS_MODULE environment variable.
    """

    ENVIRONMENT_VARIABLE = "DJANGO_SETTINGS_MODULE"

    def load(self):
        if not self.ENVIRONMENT_VARIABLE:
            raise KeyError

        source = self._import_module(os.environ[self.ENVIRONMENT_VARIABLE])

        return [global_settings, source]

    def _import_module(self, module):
        try:
            return importlib.import_module(module)
        except ImportError as e:
            raise ImportError("Could not import settings '%s' (Is it on sys.path?): %s" % (module, e))

    def get_error_message(self, setting_name, *args, **kwargs):
        desc = ("setting %s" % setting_name) if setting_name else "settings"

        return """Requested %s, but settings are not configured.
        You must either define the environment variable %s
        or call settings.configure() before accessing settings.""" % (
            desc, LazySettings._settings_sources_loader.ENVIRONMENT_VARIABLE)


class Settings(BaseSettings):
    def __init__(self, settings_sources, settings_collector=SettingsCollector):
        # Support old behavior for backwards compatibility but warn for a pending deprecation.
        if isinstance(settings_sources, six.string_types):
            warnings.warn(
                "Loading a setting module by supplying a string is deprecated."
                "Use the SettingsSourcesLoader class instead.",
                PendingDeprecationWarning,
                stacklevel=1)

            module = settings_sources
            try:
                settings_sources = [global_settings, importlib.import_module(module)]
            except ImportError as e:
                raise ImportError("Could not import settings '%s' (Is it on sys.path?): %s" % (module, e))

        # Store the settings module in case someone later cares
        if len(settings_sources) == 2 and isinstance(settings_sources[1], types.ModuleType):
            self.SETTINGS_MODULE = settings_sources[1].__name__  # Again, done for backwards compatibility.

        self.SETTINGS_SOURCES = settings_sources

        collector = settings_collector()
        collected_settings = collector.collect(settings_sources)

        self.set_settings(collected_settings)

        if not self.SECRET_KEY:
            raise ImproperlyConfigured("The SECRET_KEY setting must not be empty.")

        if hasattr(time, 'tzset') and self.TIME_ZONE:
            # When we can, attempt to validate the timezone. If we can't find
            # this file, no check happens and it's harmless.
            zoneinfo_root = '/usr/share/zoneinfo'
            if (os.path.exists(zoneinfo_root) and not
            os.path.exists(os.path.join(zoneinfo_root, *(self.TIME_ZONE.split('/'))))):
                raise ValueError("Incorrect timezone setting: %s" % self.TIME_ZONE)
                # Move the time zone info into os.environ. See ticket #2315 for why
            # we don't do this unconditionally (breaks Windows).
            os.environ['TZ'] = self.TIME_ZONE
            time.tzset()

    def set_settings(self, collected_settings):
        map(lambda setting: self.set_setting(*setting), collected_settings)

    def set_setting(self, source, setting, setting_value):
        setattr(self, setting, setting_value)


class UserSettingsHolder(BaseSettings):
    """
    Holder for user configured settings.
    """
    # SETTINGS_MODULE doesn't make much sense in the manually configured
    # (standalone) case.
    SETTINGS_MODULE = None

    def __init__(self, default_settings):
        """
        Requests for configuration variables not in this class are satisfied
        from the module specified in default_settings (if possible).
        """
        self.__dict__['_deleted'] = set()
        self.default_settings = default_settings

    def __getattr__(self, name):
        if name in self._deleted:
            raise AttributeError
        return getattr(self.default_settings, name)

    def __setattr__(self, name, value):
        self._deleted.discard(name)
        return super(UserSettingsHolder, self).__setattr__(name, value)

    def __delattr__(self, name):
        self._deleted.add(name)
        return super(UserSettingsHolder, self).__delattr__(name)

    def __dir__(self):
        return list(self.__dict__) + dir(self.default_settings)


class LazySettings(LazyObject):
    """
    A lazy proxy for either global Django settings or a custom settings object.
    The user can manually configure settings prior to using them. Otherwise,
    Django uses the settings module pointed to by DJANGO_SETTINGS_MODULE.
    """

    def __init__(self, settings_class=Settings, settings_sources_loader=SettingsSourcesLoader):
        super(LazySettings, self).__init__()

        if not issubclass(settings_class, BaseSettings):
            raise TypeError('A settings class must inherit from BaseSettings')

        if not issubclass(settings_sources_loader, BaseSettingsSourcesLoader):
            raise TypeError('A settings class must inherit from BaseSettings')

        LazySettings._settings_class = settings_class  # Done to avoid infinite recursion when using self._settings_class
        LazySettings._settings_sources_loader = settings_sources_loader

    def _setup(self, name=None):
        """
        Load the settings module pointed to by the environment variable. This
        is used the first time we need any settings at all, if the user has not
        previously configured the settings manually.
        """
        sources_loader = LazySettings._settings_sources_loader()

        try:
            settings_sources = sources_loader.load()

            if not settings_sources:  # If it's set but is an empty string.
                raise KeyError
        except KeyError:
            raise ImproperlyConfigured(sources_loader.get_error_message(name))

        self._wrapped = LazySettings._settings_class(settings_sources)
        self._configure_logging()

    def __getattr__(self, name):
        if self._wrapped is empty:
            self._setup(name)
        return getattr(self._wrapped, name)

    def _configure_logging(self):
        """
        Setup logging from LOGGING_CONFIG and LOGGING settings.
        """
        try:
            # Route warnings through python logging
            logging.captureWarnings(True)
            # Allow DeprecationWarnings through the warnings filters
            warnings.simplefilter("default", DeprecationWarning)
        except AttributeError:
            # No captureWarnings on Python 2.6, DeprecationWarnings are on anyway
            pass

        if self.LOGGING_CONFIG:
            from django.utils.log import DEFAULT_LOGGING
            # First find the logging configuration function ...
            logging_config_func = import_by_path(self.LOGGING_CONFIG)

            logging_config_func(DEFAULT_LOGGING)

            # ... then invoke it with the logging settings
            if self.LOGGING:
                logging_config_func(self.LOGGING)

    def configure(self, default_settings=global_settings, **options):
        """
        Called to manually configure the settings. The 'default_settings'
        parameter sets where to retrieve any unspecified values from (its
        argument must support attribute access (__getattr__)).
        """
        if self._wrapped is not empty:
            raise RuntimeError('Settings already configured.')
        holder = UserSettingsHolder(default_settings)
        for name, value in options.items():
            setattr(holder, name, value)
        self._wrapped = holder
        self._configure_logging()

    @property
    def configured(self):
        """
        Returns True if the settings have already been configured.
        """
        return self._wrapped is not empty


settings = LazySettings()
