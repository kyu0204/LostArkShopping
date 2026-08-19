"""1단계: /auctions/options 응답을 통째로 덤프한다.

  python scripts/dump_options.py [--force] [--out out/auction_options.json]

원본 JSON 전량을 파일로 쓰고, 스키마 요약을 stdout에 출력한다.
파서는 아직 쓰지 않는다 — 구조 확인이 목적.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkClient  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="캐시 무시하고 재요청")
    ap.add_argument("--out", default=str(ROOT / "out" / "auction_options.json"))
    args = ap.parse_args()

    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    payload = opt.fetch_options(client, force=args.force)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    text = json.dumps(payload, ensure_ascii=False)
    print(f"=== 원본 저장: {out}  ({len(text):,} chars) ===\n")
    print("=== 스키마 요약 ===")
    for line in opt.describe(payload):
        print(line)

    # 최상위 키별 크기 감각
    print("\n=== 최상위 키 ===")
    if isinstance(payload, dict):
        for k, v in payload.items():
            kind = type(v).__name__
            size = f"len={len(v)}" if isinstance(v, (list, dict, str)) else str(v)
            print(f"{k}: {kind} {size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
