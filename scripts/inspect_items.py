"""저장된 items_raw.json 을 압축 출력. 추가 요청 없음.

  python scripts/inspect_items.py [--src out/items_raw.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "out" / "items_raw.json"))
    args = ap.parse_args()

    src = Path(args.src)
    if not src.exists():
        print(f"없음: {src}", file=sys.stderr)
        return 1
    d = json.loads(src.read_text(encoding="utf-8"))
    items = d.get("Items") or []

    types: Counter[str] = Counter()
    for it in items:
        for o in it.get("Options") or []:
            types[o["Type"]] += 1

    print(f"TotalCount={d.get('TotalCount')}  Items={len(items)}")
    print(f"Option Type 분포: {dict(types)}\n")

    for i, it in enumerate(items):
        ai = it["AuctionInfo"]
        print(
            f"--- [{i}] {it['Name']}  Q={it['GradeQuality']}  "
            f"UpgradeLevel={ai['UpgradeLevel']}  Lv={it['Level']}"
        )
        print(
            f"    Buy={ai['BuyPrice']}  Bid={ai['BidPrice']}  Start={ai['StartPrice']}  "
            f"BidStart={ai['BidStartPrice']}  BidCount={ai['BidCount']}  "
            f"Trade={ai['TradeAllowCount']}  Competitive={ai['IsCompetitive']}"
        )
        for o in it.get("Options") or []:
            pct = "%" if o["IsValuePercentage"] else ""
            pen = " PENALTY" if o["IsPenalty"] else ""
            trip = f" tripod={o['OptionNameTripod']!r}" if o["OptionNameTripod"] else ""
            print(f"    {o['Type']:<18} {o['OptionName']:<28} {o['Value']}{pct}{pen}{trip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
