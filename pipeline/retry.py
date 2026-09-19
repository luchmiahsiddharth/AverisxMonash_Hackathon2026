import time
import random
from functools import wraps

def with_retry(max_attempts=5, base_delay=1.0):
    """Retries a function with exponential backoff + a bit of randomness (jitter),
    so if two threads get throttled at the same instant they don't retry in lockstep."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == max_attempts - 1:
                        raise
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
        return wrapper
    return decorator