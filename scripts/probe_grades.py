"""연마 옵션의 고대 등급값(하/중/상)을 관측으로 확정한다.

  python scripts/probe_grades.py [--pages 3]

왜 필요한가:
  /auctions/options 의 EtcValues 는 아이템 등급 4단계 × 하/중/상 12개가 섞여 있고,
  고대에 해당하는 3개의 **인덱스가 옵션마다 다르다** (적주피 [4,9,11] / 공퍼 [3,9,11] /
  공격력+ [8,10,11] / 최대마나 [2,6,9]). 인덱스 규칙으로는 못 뽑는다.

어떻게:
  ItemGrade='고대' 로 고정하면 옵션당 값이 3개로 좁혀진다. 그 3개를 실제 매물에서 관측한다.
  BUY_PRICE ASC 만 보면 저가 매물이라 상급이 안 잡히므로 DESC 도 함께 훑는다.

산출물: data/upgrade_grades.json — 옵션 키별 [하, 중, 상]. 3개 미만이면 미완으로 표시.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import quality as q  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.models import CATEGORY_NAMES, Listing  # noqa: E402
from loa.search import ASC, DESC, SORT_BUY_PRICE, collect  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

CATEGORIES = [200010, 200020, 200030]
POLISH = [1, 2, 3]
GRADES_PATH = ROOT / "data" / "upgrade_grades.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--quality", type=int, default=70)
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    listings: list[Listing] = []
    for cat in CATEGORIES:
        for polish in POLISH:
            for cond in (ASC, DESC):
                try:
                    got = list(
                        collect(
                            client,
                            cat,
                            max_pages=args.pages,
                            grade_quality=args.quality,
                            upgrade_level=polish,
                            sort=SORT_BUY_PRICE,
                            sort_condition=cond,
                        )
                    )
                except LostArkAPIError as exc:
                    print(f"  [실패] {CATEGORY_NAMES[cat]} {polish}연마 {cond} — {exc.status}")
                    continue
                listings.extend(got)
                print(f"  {CATEGORY_NAMES[cat]} {polish}연마 {cond:<4} → {len(got)}건")

    print(f"\n총 {len(listings)}건 · 요청 {client.request_count}회")

    observed = q.derive_upgrade_grades(listings)
    # 기존 관측이 있으면 합친다 (이전 수집분을 버리지 않는다)
    merged = q.merge_upgrade_grades(q.load_upgrade_grades(GRADES_PATH), observed)
    q.save_upgrade_grades(merged, GRADES_PATH)

    complete = sum(1 for v in merged.values() if len(v) == 3)
    print(f"\n옵션 {len(merged)}개 중 3등급 확보 {complete}개 → {GRADES_PATH}")
    for k, v in merged.items():
        mark = "" if len(v) == 3 else "   ⚠ 미완"
        labels = " / ".join(
            f"{lab} {val}" for lab, val in zip(q.GRADE_LABELS, v)
        ) if len(v) == 3 else str(v)
        print(f"  {k:<34} {labels}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
