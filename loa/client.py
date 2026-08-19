"""로스트아크 개발자 API 클라이언트.

제약 (HANDOFF §2):
  - Rate limit 100 req/min (키당)  → 클라이언트 측에서 슬라이딩 윈도우로 강제
  - 페이지당 10건
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any

import requests

BASE_URL = "https://developer-lostark.game.onstove.com"

# 안전 마진. 공식 한도 100/min 이지만 여유를 둔다.
DEFAULT_RATE_LIMIT = 90
RATE_WINDOW_SEC = 60.0


class LostArkAPIError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"{status} {url}\n{body[:2000]}")
        self.status = status
        self.body = body
        self.url = url


class RateLimiter:
    """슬라이딩 윈도우 방식 요청 제한기. 스레드 안전."""

    def __init__(self, max_calls: int = DEFAULT_RATE_LIMIT, window: float = RATE_WINDOW_SEC):
        self.max_calls = max_calls
        self.window = window
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.window:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = self.window - (now - self._calls[0]) + 0.01
            time.sleep(wait)


class LostArkClient:
    """엔드포인트 두 개만 감싼다: GET /auctions/options, POST /auctions/items."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        min_interval: float = 0.35,
        timeout: float = 20.0,
        max_retries: int = 3,
    ):
        key = api_key or os.environ.get("LOSTARK_API_KEY", "")
        if not key:
            raise ValueError(
                "API 키 없음. .env 에 LOSTARK_API_KEY=... 를 넣어라 (.env.example 참고)."
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_interval = min_interval  # 요청 간 최소 간격
        self._last_call = 0.0
        self._limiter = RateLimiter(rate_limit)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "accept": "application/json",
                "authorization": f"bearer {key}",
                "content-Type": "application/json",
            }
        )
        # 진단용 카운터
        self.request_count = 0

    # ---- 내부 ----

    def _throttle(self) -> None:
        self._limiter.acquire()
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            self.request_count += 1
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as exc:  # 네트워크 계층 실패
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 5))
                time.sleep(min(retry_after, 60))
                continue
            if resp.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                last_exc = LostArkAPIError(resp.status_code, resp.text, url)
                continue
            if resp.status_code >= 400:
                raise LostArkAPIError(resp.status_code, resp.text, url)
            if not resp.content:
                return None
            return resp.json()

        raise last_exc or LostArkAPIError(0, "재시도 모두 실패", url)

    # ---- 공개 API ----

    def get_auction_options(self) -> dict:
        """GET /auctions/options — 카테고리/등급/EtcOptions 목록 및 값 범위."""
        return self._request("GET", "/auctions/options")

    def search_auctions(self, payload: dict) -> dict:
        """POST /auctions/items — 경매장 매물 검색. payload는 호출자가 완성해 넘긴다."""
        return self._request("POST", "/auctions/items", json=payload)
