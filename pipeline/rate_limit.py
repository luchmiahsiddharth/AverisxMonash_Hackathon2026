"""Small helper for pacing calls made by a pipeline stage."""

import time


class RateLimiter:
    def __init__(self, requests_per_second=1.0):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self.interval = 1.0 / requests_per_second
        self._last_request = 0.0

    def wait(self):
        delay = self.interval - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        self._last_request = time.monotonic()