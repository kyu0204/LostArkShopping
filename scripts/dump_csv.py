"""검색 → CSV. 스프레드시트에서 자체 계산 기준을 적용하기 위한 원본 반출.

  python scripts/dump_csv.py --category 200010 --upgrade 2 --pages 5
  python scripts/dump_csv.py --category 200030 --upgrade 3 --with-hp

기본은 힘민지만 표시한다. 체력은 --with-hp 로 켠다
(GradeQuality 해석에는 필요하지만 비교 축으로는 쓰지 않기로 함).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.export import write_csv  # noqa: E402
from loa.models import CATEGORY_NAMES  # noqa: E402
from loa.normalize import sanity_check  # noqa: E402
from loa.search import ASC, DESC, SORT_BUY_PRICE, collect  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", type=int, default=200010,
                    help="200010 목걸이 / 200020 귀걸이 / 200030 반지 / 200040 팔찌")
    ap.add_argument("--upgrade", type=int, default=2, help="연마 단계 정확일치. -1이면 미지정")
    ap.add_argument("--quality", type=int, default=70, help="기본 품질 하한. -1이면 미지정")
    ap.add_argument("--pages", type=int, default=5)
    ap.add_argument("--desc", action="store_true", help="즉구가 내림차순")
    ap.add_argument("--with-hp", action="store_true", help="체력 열 포함")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    part = CATEGORY_NAMES.get(args.category, str(args.category))
    out = Path(args.out) if args.out else ROOT / "out" / (
        f"{part}_{args.upgrade if args.upgrade >= 0 else 'all'}연마.csv"
    )

    def on_page(page: int, total: int, got: int) -> None:
        print(f"  {page}페이지 · TotalCount={total} · {got}건")

    try:
        listings = list(
            collect(
                client,
                args.category,
                max_pages=args.pages,
                on_page=on_page,
                grade_quality=None if args.quality < 0 else args.quality,
                upgrade_level=None if args.upgrade < 0 else args.upgrade,
                sort=SORT_BUY_PRICE,
                sort_condition=DESC if args.desc else ASC,
            )
        )
    except LostArkAPIError as exc:
        print(f"[실패] {exc}", file=sys.stderr)
        return 1

    problems = sanity_check(listings)
    for p in problems[:10]:
        print(f"[경고] {p}", file=sys.stderr)

    # 품질 환산 기준: 하드코딩 테이블이 아니라 이 코호트의 실측 범위
    write_csv(listings, out, with_hp=args.with_hp)

    biddable = sum(1 for ls in listings if ls.is_biddable_only)
    print(f"\n{len(listings)}건 → {out}")
    print(f"  즉구가 없음(입찰 전용) {biddable}건 — 즉구가 열이 빈칸")
    print(f"  요청 {client.request_count}회")
    print(
        "\n힘민지_품질은 이 코호트에서 관측된 min/max 기준 0~100 환산이다. "
        "GradeQuality 와 다른 값이며, 표본이 바뀌면 값도 바뀐다. "
        "확정 비교는 힘민지_실수치로 하라."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
