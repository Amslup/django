from __future__ import unicode_literals

import importlib
import os
import sys

from django.apps import apps
from django.utils import datetime_safe, six, timezone
from django.utils.six.moves import input

from .loader import MIGRATIONS_MODULE_NAME


class MigrationQuestioner(object):
    """
    Gives the autodetector responses to questions it might have.
    This base class has a built-in noninteractive mode, but the
    interactive subclass is what the command-line arguments will use.
    """

    def __init__(self, defaults=None, specified_apps=None, dry_run=None):
        self.defaults = defaults or {}
        self.specified_apps = specified_apps or set()
        self.dry_run = dry_run

    def ask_initial(self, app_label):
        "Should we create an initial migration for the app?"
        # If it was specified on the command line, definitely true
        if app_label in self.specified_apps:
            return True
        # Otherwise, we look to see if it has a migrations module
        # without any Python files in it, apart from __init__.py.
        # Apps from the new app template will have these; the python
        # file check will ensure we skip South ones.
        try:
            app_config = apps.get_app_config(app_label)
        except LookupError:         # It's a fake app.
            return self.defaults.get("ask_initial", False)
        migrations_import_path = "%s.%s" % (app_config.name, MIGRATIONS_MODULE_NAME)
        try:
            migrations_module = importlib.import_module(migrations_import_path)
        except ImportError:
            return self.defaults.get("ask_initial", False)
        else:
            if hasattr(migrations_module, "__file__"):
                filenames = os.listdir(os.path.dirname(migrations_module.__file__))
            elif hasattr(migrations_module, "__path__"):
                if len(migrations_module.__path__) > 1:
                    return False
                filenames = os.listdir(list(migrations_module.__path__)[0])
            return not any(x.endswith(".py") for x in filenames if x != "__init__.py")

    def ask_not_null_addition(self, field_name, model_name):
        "Adding a NOT NULL field to a model"
        # None means quit
        return None

    def ask_rename(self, model_name, old_name, new_name, field_instance):
        "Was this field really renamed?"
        return self.defaults.get("ask_rename", False)

    def ask_rename_model(self, old_model_state, new_model_state):
        "Was this model really renamed?"
        return self.defaults.get("ask_rename_model", False)

    def ask_merge(self, app_label):
        "Do you really want to merge these migrations?"
        return self.defaults.get("ask_merge", False)


class InteractiveMigrationQuestioner(MigrationQuestioner):

    def _boolean_input(self, question, default=None):
        result = input("%s " % question)
        if not result and default is not None:
            return default
        while len(result) < 1 or result[0].lower() not in "yn":
            result = input("Please answer yes or no: ")
        return result[0].lower() == "y"

    def _choice_input(self, question, choices):
        print(question)
        for i, choice in enumerate(choices):
            print(" %s) %s" % (i + 1, choice))
        result = input("Select an option: ")
        while True:
            try:
                value = int(result)
                if 0 < value <= len(choices):
                    return value
            except ValueError:
                pass
            result = input("Please select a valid option: ")

    def ask_not_null_addition(self, field_name, model_name):
        "Adding a NOT NULL field to a model"
        if not self.dry_run:
            choice = self._choice_input(
                "You are trying to add a non-nullable field '%s' to %s without a default;\n" % (field_name, model_name) +
                "we can't do that (the database needs something to populate existing rows).\n" +
                "Please select a fix:",
                [
                    "Provide a one-off default now (will be set on all existing rows)",
                    "Quit, and let me add a default in models.py",
                ]
            )
            if choice == 2:
                sys.exit(3)
            else:
                print("Please enter the default value now, as valid Python")
                print("The datetime and django.utils.timezone modules are "
                      "available, so you can do e.g. timezone.now()")
                while True:
                    if six.PY3:
                        # Six does not correctly abstract over the fact that
                        # py3 input returns a unicode string, while py2 raw_input
                        # returns a bytestring.
                        code = input(">>> ")
                    else:
                        code = input(">>> ").decode(sys.stdin.encoding)
                    if not code:
                        print("Please enter some code, or 'exit' (with no quotes) to exit.")
                    elif code == "exit":
                        sys.exit(1)
                    else:
                        try:
                            return eval(code, {}, {"datetime": datetime_safe, "timezone": timezone})
                        except (SyntaxError, NameError) as e:
                            print("Invalid input: %s" % e)
        return None

    def ask_rename(self, model_name, old_name, new_name, field_instance):
        "Was this field really renamed?"
        return self._boolean_input("Did you rename %s.%s to %s.%s (a %s)? [y/N]" % (model_name, old_name, model_name, new_name, field_instance.__class__.__name__), False)

    def ask_rename_model(self, old_model_state, new_model_state):
        "Was this model really renamed?"
        return self._boolean_input("Did you rename the %s.%s model to %s? [y/N]" % (old_model_state.app_label, old_model_state.name, new_model_state.name), False)

    def ask_merge(self, app_label):
        return self._boolean_input(
            "\nMerging will only work if the operations printed above do not conflict\n" +
            "with each other (working on different fields or models)\n" +
            "Do you want to merge these migration branches? [y/N]",
            False,
        )
