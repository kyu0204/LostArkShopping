"""매물 아이콘 로더.

찾는 순서
  1. 이름으로 된 로컬 파일 — assets/ 우선, 없으면 저장소 루트
       '도래한 결전의 목걸이'  →  도래한_결전의_목걸이.png
  2. 응답의 `Icon` 필드(cdn-lostark 주소)를 받아 assets/cache/ 에 저장한 것

2번이 팔찌처럼 로컬 에셋이 없는 부위를 메운다. 아이콘 주소를 추측하지 않고
경매장 응답이 준 값을 그대로 쓰므로 아이템이 바뀌어도 따라간다.

내려받기는 별도 스레드에서 한다. 그리기 도중에 네트워크를 타면 창이 언다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap

ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = (ROOT / "assets", ROOT)
CACHE_DIR = ROOT / "assets" / "cache"

_cache: dict[tuple[str, str], QPixmap | None] = {}


def _named_file(name: str) -> Path | None:
    filename = f"{name.replace(' ', '_')}.png"
    for folder in SEARCH_DIRS:
        path = folder / filename
        if path.exists():
            return path
    return None


def _cache_file(url: str) -> Path:
    """URL 당 한 파일. 이름에 한글·공백이 섞이지 않게 해시를 쓴다."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    suffix = Path(url).suffix or ".png"
    return CACHE_DIR / f"{digest}{suffix}"


def icon_for(name: str, url: str = "") -> QPixmap | None:
    """이름 → 로컬 에셋, 없으면 내려받아 둔 CDN 아이콘. 아직 없으면 None."""
    key = (name or "", url or "")
    if key in _cache:
        return _cache[key]

    path = _named_file(name) if name else None
    if path is None and url:
        cached = _cache_file(url)
        path = cached if cached.exists() else None

    pixmap: QPixmap | None = None
    if path is not None:
        loaded = QPixmap(str(path))
        if not loaded.isNull():
            pixmap = loaded
    _cache[key] = pixmap
    return pixmap


def pending_downloads(listings) -> list[tuple[str, str]]:
    """아직 로컬에도 캐시에도 없는 (이름, URL) 목록."""
    out: dict[str, str] = {}
    for ls in listings:
        url = getattr(ls, "icon_url", "")
        if not url or _named_file(ls.name) is not None:
            continue
        if _cache_file(url).exists():
            continue
        out[url] = ls.name
    return [(name, url) for url, name in out.items()]


def missing_names(listings) -> list[str]:
    """이름 에셋도 없고 URL 도 없는 매물. 비어 있어야 정상."""
    return sorted(
        {
            ls.name
            for ls in listings
            if ls.name and _named_file(ls.name) is None and not getattr(ls, "icon_url", "")
        }
    )


class IconFetcher(QThread):
    """CDN 아이콘을 받아 디스크에 캐시한다. 받은 만큼 신호를 보낸다."""

    fetched = Signal(int)  # 이번에 새로 받은 개수

    def __init__(self, jobs: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self._jobs = jobs

    def run(self) -> None:
        if not self._jobs:
            return
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        session = requests.Session()
        got = 0
        for _name, url in self._jobs:
            target = _cache_file(url)
            if target.exists():
                continue
            try:
                resp = session.get(url, timeout=10)
                if resp.status_code == 200 and resp.content:
                    target.write_bytes(resp.content)
                    got += 1
            except requests.RequestException:
                continue  # 아이콘이 없다고 검색 결과를 버릴 이유는 없다
        if got:
            _cache.clear()  # 새로 받은 것이 반영되도록 메모리 캐시를 비운다
        self.fetched.emit(got)
