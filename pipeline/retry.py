# retry.py
import logging
import random
import time
from functools import wraps

logger = logging.getLogger(__name__)

# Exceptions that indicate a programming bug, not a transient failure.
# Retrying on these just wastes time and API calls — fail fast instead.
_NON_RETRYABLE = (AttributeError, TypeError, NameError, SyntaxError, ImportError)


def with_retry(max_attempts=5, base_delay=1.0, max_delay=30.0,
               retry_on=None, jitter=1.0, quiet=False):
    """Retries a function with exponential backoff and jitter.

    Non-transient errors (AttributeError, TypeError, …) are re-raised
    immediately without retrying, so a coding bug doesn't look like an
    API hiccup.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except _NON_RETRYABLE:
                    raise
                except Exception as e:
                    last_exc = e
                    if retry_on is not None and not isinstance(e, retry_on):
                        raise
                    if attempt == max_attempts - 1:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    delay += random.uniform(0, jitter)
                    if not quiet:
                        logger.warning(
                            "[retry] %s attempt %d/%d failed (%s), retry in %.2fs",
                            func.__name__, attempt + 1, max_attempts,
                            type(e).__name__, delay,
                        )
                    time.sleep(delay)
            if last_exc is not None:
                raise last_exc
        return wrapper
    return decorator