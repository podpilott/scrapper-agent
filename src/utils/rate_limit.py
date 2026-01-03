"""Rate limiting utilities."""

import asyncio
import time
from collections import deque


class RateLimiter:
    """Token bucket rate limiter for controlling request frequency."""

    def __init__(self, requests_per_minute: int = 10):
        """Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute.
        """
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self._timestamps: deque[float] = deque(maxlen=requests_per_minute)

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        now = time.monotonic()

        # Remove timestamps older than 1 minute
        while self._timestamps and now - self._timestamps[0] > 60:
            self._timestamps.popleft()

        # If at capacity, wait for oldest to expire
        if len(self._timestamps) >= self.requests_per_minute:
            sleep_time = 60 - (now - self._timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

        # Also enforce minimum interval between requests
        if self._timestamps:
            elapsed = now - self._timestamps[-1]
            if elapsed < self.min_interval:
                await asyncio.sleep(self.min_interval - elapsed)

        self._timestamps.append(time.monotonic())

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.acquire()
        return True
