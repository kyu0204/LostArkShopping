"""비교 엔진을 실데이터로 돌려 본다 (HANDOFF §6).

  python scripts/compare_demo.py --category 200010 --upgrade 2 --pages 8
  python scripts/compare_demo.py --category 200030 --upgrade 3 --threshold 10

임계치가 결과를 크게 흔든다. 빡빡하면 쌍이 안 나오고 느슨하면 오염된다 (§6.3).
--sweep 으로 임계치별 쌍 개수를 훑어 감을 잡는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import compare, quality as q  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.models import CATEGORY_NAMES  # noqa: E402
from loa.search import ASC, SORT_BUY_PRICE, collect  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", type=int, default=200010)
    ap.add_argument("--upgrade", type=int, default=2)
    ap.add_argument("--quality", type=int, default=70)
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--threshold", type=float, default=compare.DEFAULT_THRESHOLD)
    ap.add_argument("--sweep", action="store_true", help="임계치별 쌍 개수 훑기")
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    part = CATEGORY_NAMES.get(args.category, str(args.category))
    print(f"수집: 고대 · T4 · {part} · {args.upgrade}연마 · 품질 {args.quality}+ "
          f"· {args.pages}페이지")
    try:
        listings = list(
            collect(
                client, args.category, max_pages=args.pages,
                grade_quality=None if args.quality < 0 else args.quality,
                upgrade_level=None if args.upgrade < 0 else args.upgrade,
                sort=SORT_BUY_PRICE, sort_condition=ASC,
            )
        )
    except LostArkAPIError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    grades = q.merge_upgrade_grades(
        q.load_upgrade_grades(), q.derive_upgrade_grades(listings)
    )
    priced = [x for x in listings if x.buy_price]
    print(f"{len(listings)}건 · 즉구가 있는 매물 {len(priced)}건 "
          f"· 가격 {min(x.buy_price for x in priced):,}~"
          f"{max(x.buy_price for x in priced):,}\n")

    if args.sweep:
        print("=== 임계치별 통제된 쌍 ===")
        rows = [(*compare.axes_for(x, grades), x) for x in priced]
        keys = compare.major_keys(rows)
        for th in (0, 1, 2, 3, 5, 8, 12, 20, 40, 100):
            pairs = compare.find_pairs(rows, keys, float(th))
            trans = compare.estimate_transitions(pairs)
            ok = sum(1 for t in trans if t.enough)
            print(f"  임계치 {th:>4} → 쌍 {len(pairs):>4}개 · 전이 {len(trans):>3}종 "
                  f"· 추정 가능 {ok}종")
        print()

    print("=== 갈리지 않은 전체 (대조군) ===")
    print(compare.analyze(listings, grades, args.threshold).describe())

    print("\n=== 구매자 무리별 (§6.6 오염 제거) ===")
    reports = compare.analyze_by_role(listings, grades, args.threshold)
    for rep in reports:
        print(rep.describe())
        print()

    report = max(reports, key=lambda r: len(r.transitions))
    print(f"=== 근거 쌍 펼치기 — {report.role} (§6.5) ===")
    for t in sorted(report.transitions, key=lambda x: -x.n)[:3]:
        print(f"\n{t.label}  {t.n}쌍")
        for p in sorted(t.pairs, key=lambda x: x.price_delta)[:6]:
            print(
                f"   {p.lower.buy_price:>10,} → {p.upper.buy_price:>10,}  "
                f"= {p.price_delta:+10,}   (연속값 차 {p.continuous_gap:.1f})"
            )

    print("\n주의: BUY_PRICE ASC 로 앞쪽만 봤다. 여기 수치는 '시세'가 아니라")
    print("      하한선 기준 상대가다 (§6.7).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
