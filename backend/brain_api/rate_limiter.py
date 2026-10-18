"""In-memory sliding window rate limiter for /api/chat.

Per ARCHITECTURE.md Section 14:
- Allows CHAT_RATE_LIMIT_PER_MIN requests per client IP.
- Reads first hop of X-Forwarded-For when present, else socket address.
- In-memory sliding window of 60 seconds.
- Excess requests get 429 RATE_LIMITED.
"""

from collections import deque
import threading
import time
from typing import Dict
from fastapi import Request

from brain_api.exceptions import RateLimitedException
from brain_core.config import get_settings


class ChatRateLimiter:
    """Sliding-window rate limiter keyed by client IP."""

    def __init__(self) -> None:
        self._requests: Dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check_rate_limit(self, request: Request) -> None:
        """Check if request exceeds rate limit, raising RateLimitedException if so."""
        cfg = get_settings()
        limit = cfg.CHAT_RATE_LIMIT_PER_MIN

        # Extract client IP: first hop of X-Forwarded-For if present, else socket address
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        elif request.client and request.client.host:
            client_ip = request.client.host
        else:
            client_ip = "unknown"

        now = time.time()
        window_start = now - 60.0

        with self._lock:
            if client_ip not in self._requests:
                self._requests[client_ip] = deque()

            q = self._requests[client_ip]

            # Prune requests outside 60s sliding window
            while q and q[0] <= window_start:
                q.popleft()

            if len(q) >= limit:
                raise RateLimitedException(
                    f"Rate limit exceeded: maximum {limit} chat requests per minute allowed."
                )

            q.append(now)


rate_limiter = ChatRateLimiter()
