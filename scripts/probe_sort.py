"""정렬 동작 실측 (§5.3).

관측: Sort=BUYPRICE / SortCondition=ASC 인데 반환 순서가 BuyPrice 오름차순이 아니고,
ASC 와 DESC 결과가 동일했다. 무엇이 실제 정렬 키인지, SortCondition 이 먹기는 하는지
확인한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

NECK = 200010


def show(client, label: str, **kw) -> None:
    try:
        resp = client.search_auctions(build_payload(NECK, 1, **kw))
    except LostArkAPIError as exc:
        print(f"{label:<34} HTTP {exc.status}  {exc.body[:120]}")
        return
    items = (resp or {}).get("Items") or []
    buy = [it["AuctionInfo"]["BuyPrice"] for it in items]
    start = [it["AuctionInfo"]["StartPrice"] for it in items]
    print(f"\n[{label}]  TotalCount={resp.get('TotalCount')}")
    print(f"  Buy   {buy}")
    print(f"  Start {start}")
    # None(즉구 없음)은 정렬 판정에서 빼고 본다
    b = [v for v in buy if v is not None]
    s = [v for v in start if v is not None]
    print(
        f"  Buy 오름차순? {b == sorted(b)} / 내림차순? {b == sorted(b, reverse=True)}"
        f"   None {buy.count(None)}건"
    )
    print(f"  Start 오름차순? {s == sorted(s)}")


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    common = dict(grade_quality=70, upgrade_level=2)
    # 헛소리 값 = 기준선. 이것과 같으면 그 Sort 값은 인식되지 않은 것이다.
    show(client, "Sort=NONSENSE (기준선)", sort="NONSENSE", sort_condition="ASC", **common)

    for sort in ("BUY_PRICE", "BIDSTART_PRICE", "ITEM_QUALITY", "ITEM_LEVEL", "EXPIREDATE"):
        for cond in ("ASC", "DESC"):
            show(client, f"Sort={sort} {cond}", sort=sort, sort_condition=cond, **common)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
