"""수집 워커 (HANDOFF §8.3).

API 호출은 반드시 여기서. 최대 15페이지까지 갈 수 있어 메인 스레드에서 돌리면 창이 언다.
취소는 협조적(cooperative) — 페이지 경계에서 확인한다.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal

from loa.client import LostArkAPIError
from loa.models import Listing
from loa.search import collect


class CollectWorker(QThread):
    progress = Signal(int, int, int)  # 페이지, TotalCount, 지금까지 유효 매물 수
    done = Signal(list)  # list[Listing]
    failed = Signal(str)

    def __init__(self, client, category_code: int, max_pages: int, payload_kw: dict[str, Any]):
        super().__init__()
        self._client = client
        self._category = category_code
        self._max_pages = max_pages
        self._kw = payload_kw
        self._cancelled = False
        self._page = 0
        self._total = 0

    def cancel(self) -> None:
        self._cancelled = True

    def _on_page(self, page: int, total: int, got: int) -> None:
        self._page, self._total = page, total

    def run(self) -> None:
        gathered: list[Listing] = []
        try:
            for listing in collect(
                self._client,
                self._category,
                max_pages=self._max_pages,
                on_page=self._on_page,
                **self._kw,
            ):
                gathered.append(listing)
                # 페이지 단위로만 신호를 쏜다 (10건마다)
                if len(gathered) % 10 == 0:
                    valid = sum(1 for x in gathered if not x.is_biddable_only)
                    self.progress.emit(self._page, self._total, valid)
                    if self._cancelled:
                        break
        except LostArkAPIError as exc:
            self.failed.emit(f"HTTP {exc.status}\n{exc.body[:300]}")
            return
        except Exception as exc:  # 네트워크 등
            self.failed.emit(str(exc))
            return
        self.done.emit(gathered)
