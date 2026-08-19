"""/auctions/items 요청 바디 생성 + 페이지 수집.

요청 스키마는 /auctions/options 가 알려주지 않아 실측으로 확정했다.
**서버는 미지 필드를 400 없이 조용히 무시한다** (probe_upgrade_filter.py 대조군으로 확인).
따라서 필드명을 틀리면 '필터가 없는 것'처럼 보인다. 이름을 바꾸지 마라.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

from .models import Listing
from .normalize import normalize_response

PAGE_SIZE = 10

# 실측(probe_sort.py): Sort 값은 언더스코어 표기다. 'BUYPRICE'(무언더스코어)는
# 인식되지 않고 헛소리 값과 동일하게 기본 정렬(StartPrice ASC)로 떨어지며,
# 그때는 SortCondition 도 무시된다. 오타가 조용히 다른 정렬로 둔갑하니 주의.
SORT_BUY_PRICE = "BUY_PRICE"
SORT_BIDSTART_PRICE = "BIDSTART_PRICE"
SORT_EXPIREDATE = "EXPIREDATE"
ASC = "ASC"
DESC = "DESC"


def build_payload(
    category_code: int,
    page: int = 1,
    *,
    grade_quality: int | None = None,
    upgrade_level: int | None = None,
    etc_options: list[dict] | None = None,
    item_grade: str = "고대",
    item_tier: int = 4,
    sort: str = SORT_BUY_PRICE,
    sort_condition: str = ASC,
    item_name: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ItemLevelMin": 0,
        "ItemLevelMax": 0,
        "ItemGradeQuality": grade_quality,
        "SkillOptions": [],
        "EtcOptions": etc_options or [],
        "Sort": sort,
        "CategoryCode": category_code,
        "CharacterClass": "",
        "ItemTier": item_tier,
        "ItemGrade": item_grade,
        "ItemName": item_name,
        "PageNo": page,
        "SortCondition": sort_condition,
    }
    if upgrade_level is not None:
        # 실측: 정확일치 필터. 하한이 아니다.
        payload["ItemUpgradeLevel"] = upgrade_level
    if extra:
        payload.update(extra)
    return payload


def collect(
    client,
    category_code: int,
    *,
    max_pages: int = 5,
    on_page: Callable[[int, int, int], None] | None = None,
    **payload_kw: Any,
) -> Iterator[Listing]:
    """페이지를 순회하며 Listing 을 흘려보낸다.

    on_page(page, total_count, got) — 진행률 콜백. QThread 워커에서 시그널로 연결.
    rate limit 은 client 가 처리하므로 여기서 sleep 하지 않는다.
    """
    index = 0
    for page in range(1, max_pages + 1):
        resp = client.search_auctions(
            build_payload(category_code, page, **payload_kw)
        )
        total = (resp or {}).get("TotalCount") or 0
        items = (resp or {}).get("Items") or []
        if on_page:
            on_page(page, total, len(items))
        if not items:
            return
        yield from normalize_response(resp, category_code, index)
        index += len(items)
        if page * PAGE_SIZE >= total:
            return
