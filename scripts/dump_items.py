"""2단계 준비: /auctions/items 응답 원문 덤프.

  python scripts/dump_items.py [--category 200010] [--quality 70] [--page 1]

파서를 쓰기 전에 실제 응답 구조를 눈으로 확인하는 것이 목적.
요청 바디 스키마는 /auctions/options 가 알려주지 않으므로, 여기서 실측한다.
요청 1건만 보낸다 (rate limit 절약).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", type=int, default=200010, help="200010 목걸이")
    ap.add_argument("--quality", type=int, default=70, help="기본 품질 하한. -1이면 미지정")
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--upgrade", type=int, default=None, help="연마 단계 정확일치 (0~3)")
    ap.add_argument("--out", default=str(ROOT / "out" / "items_raw.json"))
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    quality = None if args.quality < 0 else args.quality
    payload = build_payload(
        args.category, args.page, grade_quality=quality, upgrade_level=args.upgrade
    )

    print("=== 요청 바디 ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        resp = client.search_auctions(payload)
    except LostArkAPIError as exc:
        print(f"\n[실패] {exc}", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(resp, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 원본 저장: {out} ===")

    print("\n=== 응답 스키마 ===")
    for line in opt.describe(resp, max_depth=8):
        print(line)

    items = (resp or {}).get("Items") or []
    print(f"\nTotalCount={resp.get('TotalCount')}  PageNo={resp.get('PageNo')} "
          f"PageSize={resp.get('PageSize')}  Items={len(items)}")

    if items:
        print("\n=== Items[0] 원문 ===")
        print(json.dumps(items[0], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
