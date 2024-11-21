import inspect
import json
import random
import time
from functools import wraps
from traceback import format_exception

from django.utils.crypto import RANDOM_STRING_CHARS
from django.utils.module_loading import import_string


def is_module_level_function(func):
    if not inspect.isfunction(func) or inspect.isbuiltin(func):
        return False

    if "<locals>" in func.__qualname__:
        return False

    return True


def json_normalize(obj):
    """
    Round-trip encode object as JSON to normalize types.
    """
    return json.loads(json.dumps(obj))


def retry(*, retries=3, backoff_delay=0.1):
    """
    Retry the given code `retries` times, raising the final error.

    `backoff_delay` can be used to add a delay between attempts.
    """

    def wrapper(f):
        @wraps(f)
        def inner_wrapper(*args, **kwargs):
            for attempt in range(1, retries + 1):
                try:
                    return f(*args, **kwargs)
                except KeyboardInterrupt:
                    # Let the user ctrl-C out of the program without a retry
                    raise
                except BaseException:
                    if attempt == retries:
                        raise
                    time.sleep(backoff_delay)

        return inner_wrapper

    return wrapper


def get_module_path(val):
    return f"{val.__module__}.{val.__qualname__}"


def exception_to_dict(exc):
    return {
        "exc_type": get_module_path(type(exc)),
        "exc_args": json_normalize(exc.args),
        "exc_traceback": "".join(format_exception(type(exc), exc, exc.__traceback__)),
    }


def exception_from_dict(exc_data):
    exc_class = import_string(exc_data["exc_type"])

    if not inspect.isclass(exc_class) or not issubclass(exc_class, BaseException):
        raise TypeError(f"{type(exc_class)} is not an exception")

    return exc_class(*exc_data["exc_args"])


def get_random_id():
    """
    Return a random string for use as a task id.

    Whilst 64 characters is the max, just use 32 as a sensible middle-ground.

    This should be much faster than `get_random_string`, since
    it's not cryptographically secure.
    """
    return "".join(random.choices(RANDOM_STRING_CHARS, k=32))
