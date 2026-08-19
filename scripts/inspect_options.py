"""덤프된 /auctions/options 중 장신구/팔찌 관련 부분만 사람이 읽게 출력.

  python scripts/inspect_options.py

SkillOptions(보석 571건)는 이 도구 범위 밖이라 건너뛴다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "out" / "auction_options.json"


def main() -> int:
    if not SRC.exists():
        print(f"없음: {SRC} — 먼저 scripts/dump_options.py 실행", file=sys.stderr)
        return 1
    d = json.loads(SRC.read_text(encoding="utf-8"))

    print("=== ItemGrades ===")
    print(d["ItemGrades"])
    print("\n=== ItemTiers ===")
    print(d["ItemTiers"])
    print("\n=== ItemGradeQualities ===")
    print(d["ItemGradeQualities"])
    print(f"\n=== MaxItemLevel === {d['MaxItemLevel']}")

    print("\n=== Categories (부위 코드) ===")
    for cat in d["Categories"]:
        print(f"[{cat['Code']}] {cat['CodeName']}")
        for sub in cat.get("Subs") or []:
            print(f"    {sub['Code']:>7}  {sub['CodeName']}")

    print("\n=== EtcOptions (연마/각인 등 옵션 축) ===")
    for e in d["EtcOptions"]:
        print(f"\n[Value={e['Value']}] {e['Text']}  Tiers={e.get('Tiers')}")
        subs = e.get("EtcSubs") or []
        print(f"  EtcSubs: {len(subs)}건")
        for s in subs:
            bits = [f"Value={s['Value']}", f"Text={s['Text']!r}"]
            if s.get("Class"):
                bits.append(f"Class={s['Class']!r}")
            if s.get("Categorys"):
                bits.append(f"Categorys={s['Categorys']}")
            if s.get("Tiers"):
                bits.append(f"Tiers={s['Tiers']}")
            ev = s.get("EtcValues")
            if ev:
                bits.append(f"EtcValues({len(ev)})={ev}")
            print("    " + "  ".join(bits))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
