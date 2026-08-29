"""Resilience primitives: circuit breaker, concurrency limiter, retries.

All are usable from sync and async code paths; the breaker/limiter hold no
event-loop-bound state (AsyncRateLimiter lazily builds its semaphore inside
a running loop so sync tests can still construct the object).
"""

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """closed -> open after `failure_threshold` consecutive failures;
    open -> half-open after `reset_timeout` seconds; a success in half-open
    closes it, a failure reopens it."""

    def __init__(self, failure_threshold: int = 10, reset_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = "closed"
        self.failures = 0
        self.opened_at: float | None = None

    def allow(self) -> bool:
        if self.state == "open":
            if (
                self.opened_at is not None
                and time.monotonic() - self.opened_at >= self.reset_timeout
            ):
                self.state = "half-open"
                return True
            return False
        return True

    def check(self) -> None:
        if not self.allow():
            raise CircuitOpenError("circuit is open")

    def record_success(self) -> None:
        self.failures = 0
        self.state = "closed"
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == "half-open" or self.failures >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.monotonic()

    def call(self, fn: Callable[[], T]) -> T:
        """Sync convenience wrapper."""
        self.check()
        try:
            result = fn()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    async def acall(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Async convenience wrapper."""
        self.check()
        try:
            result = await fn()
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


class AsyncRateLimiter:
    """Bounded-concurrency gate around an asyncio semaphore."""

    def __init__(self, max_concurrency: int):
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.max_concurrency = max_concurrency
        self._semaphore: asyncio.Semaphore | None = None
        self._loop_id: int | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if self._semaphore is None or self._loop_id != loop_id:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
            self._loop_id = loop_id
        return self._semaphore

    async def __aenter__(self) -> "AsyncRateLimiter":
        await self._get_semaphore().acquire()
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._get_semaphore().release()

    def in_flight_capacity(self) -> int:
        return self.max_concurrency


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    attempts: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except retry_on as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            delay = max(0.0, base_delay * (2 ** attempt) + random.uniform(-jitter, jitter))
            await asyncio.sleep(delay)
    raise last_error  # pragma: no cover - unreachable


def retry_with_backoff_sync(
    fn: Callable[[], T],
    attempts: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except retry_on as exc:
            last_error = exc
            if attempt == attempts - 1:
                raise
            delay = max(0.0, base_delay * (2 ** attempt) + random.uniform(-jitter, jitter))
            time.sleep(delay)
    raise last_error  # pragma: no cover - unreachable
