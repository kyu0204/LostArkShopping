"""/auctions/options 취득 + 로컬 캐시 (TTL 24h).

HANDOFF §2: 옵션 목록 하드코딩 금지. 반드시 런타임 취득.
이 모듈은 응답 구조를 **가정하지 않는다.** 원본 dict를 그대로 보관하고,
탐색용 헬퍼만 제공한다. 구조 확정 전까지 파싱 로직을 넣지 마라.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

CACHE_TTL_SEC = 24 * 3600
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "auction_options_cache.json"


def load_cached(path: Path = DEFAULT_CACHE_PATH, ttl: int = CACHE_TTL_SEC) -> dict | None:
    """유효한 캐시가 있으면 원본 응답을 반환, 없거나 만료면 None."""
    if not path.exists():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if time.time() - blob.get("fetched_at", 0) > ttl:
        return None
    return blob.get("payload")


def save_cache(payload: dict, path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {"fetched_at": time.time(), "payload": payload}
    path.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch_options(client, path: Path = DEFAULT_CACHE_PATH, force: bool = False) -> dict:
    """캐시 우선. force=True면 무조건 재요청."""
    if not force:
        cached = load_cached(path)
        if cached is not None:
            return cached
    payload = client.get_auction_options()
    save_cache(payload, path)
    return payload


# ---- EtcOptions 축 (실측한 Value 값) ----

ETC_BASE_STAT = 1  # 장신구 기본 효과 (체력 / 힘·민첩·지능)
ETC_BRACELET_COUNT = 4  # 팔찌 옵션 수량
ETC_BRACELET_SPECIAL = 5  # 팔찌 특수 효과
ETC_POLISH = 7  # 연마 효과


def _axis(payload: dict, value: int) -> dict | None:
    for e in payload.get("EtcOptions") or []:
        if e.get("Value") == value:
            return e
    return None


def is_exclusive(sub: dict) -> bool:
    """부위 전용 옵션인가.

    Categorys 가 지정된 옵션이 그 부위의 특수 옵션이다 — 적주피·추피·치적·치피·
    공퍼·아공강 같은 실제 가치를 가르는 축이 전부 여기 들어간다.
    Categorys 가 없는 공통 옵션은 공격력+·최대생명력 같은 단순 수치 계열이다.
    """
    return bool(sub.get("Categorys"))


def option_pool(
    payload: dict, category_code: int, axis: int = ETC_POLISH, tier: int = 4
) -> list[dict]:
    """부위에 실제로 붙을 수 있는 옵션만 골라 준다.

    EtcSubs[].Categorys 가 부위 제한을 이미 들고 있다 (예: 적주피는 목걸이 전용).
    Categorys 가 없으면 전 부위 공통. 하드코딩 없이 이걸 그대로 쓴다 (HANDOFF §2).

    정렬: 부위 전용(특수) 먼저, 공통(단순 수치) 나중. 그 안에서는 이름순.
    """
    node = _axis(payload, axis)
    if not node:
        return []
    parent_tiers = node.get("Tiers") or []
    out: list[dict] = []
    for sub in node.get("EtcSubs") or []:
        cats = sub.get("Categorys")
        if cats and category_code not in cats:
            continue
        tiers = sub.get("Tiers") or parent_tiers
        if tiers and tier not in tiers:
            continue
        out.append(sub)
    return sorted(out, key=lambda s: (not is_exclusive(s), s.get("Text", "")))


def exclusive_option_keys(
    payload: dict, category_code: int, axis: int = ETC_POLISH, tier: int = 4
) -> set[str]:
    """해당 부위의 특수 옵션 키 집합. 표시 순서를 정하는 데 쓴다."""
    return {
        option_key(sub)
        for sub in option_pool(payload, category_code, axis, tier)
        if is_exclusive(sub)
    }


def etc_value_number(ev: dict) -> float | None:
    """EtcValues 항목의 DisplayValue('0.55%', '195')를 실제 수치로.

    Value 필드는 100배 정수 스케일이라 매물 응답의 Value(0.55)와 직접 비교되지 않는다.
    """
    text = (ev.get("DisplayValue") or "").strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def option_key(sub: dict) -> str:
    """EtcSubs 항목 → 매물 정규화에 쓰는 옵션 키.

    폼(Text='공격력 %')과 매물(OptionName='공격력', IsValuePercentage=True)의
    표기가 달라서 맞춰줘야 한다. 접미 ' %' / ' +' 를 떼고 %여부만 붙인다.
    """
    text = (sub.get("Text") or "").strip()
    for suffix in (" %", " +"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    values = sub.get("EtcValues") or []
    pct = bool(values and values[0].get("IsPercentage"))
    return f"{text}%" if pct else text


BRACELET_RANGES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "bracelet_ranges.json"
)
_bracelet_ranges: dict | None = None


def bracelet_ranges(path: Path = BRACELET_RANGES_PATH) -> dict:
    """옵션별 관측 범위와 필터 가능 여부 (probe_bracelet_ranges.py 산출).

    이 두 축은 EtcSubs 에 EtcValues 가 없어 API 가 값 목록을 주지 않는다.
    그래서 관측표가 없으면 폼에서 범위를 알 수 없다.
    """
    global _bracelet_ranges
    if _bracelet_ranges is None:
        try:
            _bracelet_ranges = json.loads(path.read_text(encoding="utf-8")).get("options", {})
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            _bracelet_ranges = {}
    return _bracelet_ranges


OFFICIAL_RANGES_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "bracelet_official_ranges.json"
)
_official: dict | None = None


def official_range(name: str, grade: str = "고대") -> dict | None:
    """공식 확률표의 수치 범위. API 가 값을 안 주는 옵션을 화면에 알리는 용도다.

    이 범위로는 필터할 수 없다 — 응답에 구분 가능한 숫자가 없기 때문이다.
    """
    global _official
    if _official is None:
        try:
            _official = json.loads(
                OFFICIAL_RANGES_PATH.read_text(encoding="utf-8")
            ).get("options", {})
        except (json.JSONDecodeError, OSError, FileNotFoundError):
            _official = {}
    return (_official.get(name) or {}).get(grade)


def sort_bracelet_pool(pool: list[dict]) -> list[dict]:
    """T4 고대에 없는 옵션은 빼고, 범위 지정 가능한 것을 앞으로 보낸다.

    26개 중 16개는 T4 고대 매물이 0건이다 (T3 시절 옵션). 목록에 두면 헛돌게 된다.
    """
    info = bracelet_ranges()
    out = []
    for sub in pool:
        meta = info.get(sub.get("Text", ""))
        if meta is not None and not meta.get("exists", True):
            continue
        out.append(sub)
    return sorted(
        out,
        key=lambda s: (
            not (info.get(s.get("Text", ""), {}).get("rangeable")),
            s.get("Text", ""),
        ),
    )


def quality_steps(payload: dict) -> list[int]:
    """ItemGradeQualities — 품질 하한 필터로 쓸 수 있는 값들."""
    return list(payload.get("ItemGradeQualities") or [])


def accessory_categories(payload: dict) -> list[tuple[int, str]]:
    """장신구 하위 부위 (코드, 이름)."""
    for cat in payload.get("Categories") or []:
        if cat.get("Code") == 200000:
            return [(s["Code"], s["CodeName"]) for s in cat.get("Subs") or []]
    return []


# ---- 구조 탐색 헬퍼 (파싱 아님) ----


def describe(node: Any, prefix: str = "", max_depth: int = 6, _depth: int = 0) -> list[str]:
    """응답 스키마를 사람이 읽을 수 있게 요약. 리스트는 첫 원소만 대표로 펼친다."""
    lines: list[str] = []
    if _depth > max_depth:
        lines.append(f"{prefix}: ...(깊이 제한)")
        return lines
    if isinstance(node, dict):
        for k, v in node.items():
            child = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                lines.extend(describe(v, child, max_depth, _depth + 1))
            else:
                lines.append(f"{child}: {type(v).__name__} = {_short(v)}")
    elif isinstance(node, list):
        lines.append(f"{prefix}[]: list(len={len(node)})")
        if node:
            lines.extend(describe(node[0], f"{prefix}[0]", max_depth, _depth + 1))
    else:
        lines.append(f"{prefix}: {type(node).__name__} = {_short(node)}")
    return lines


def _short(v: Any, limit: int = 60) -> str:
    s = str(v)
    return s if len(s) <= limit else s[:limit] + "…"
