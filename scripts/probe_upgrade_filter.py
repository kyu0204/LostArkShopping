"""§10 항목3 판정: API에 연마 단계 직접 필터가 있는가.

  python scripts/probe_upgrade_filter.py

전략:
  1) 알려지지 않은 필드명 후보를 요청 바디에 넣어본다.
     - 400 이 나면 = 서버가 스키마를 검증한다 → 그 이름은 없음
     - 200 인데 TotalCount 가 baseline 과 같으면 = 조용히 무시됨 → 없음
     - 200 이고 TotalCount 가 줄고 UpgradeLevel 분포가 좁아지면 = 먹힘
  2) EtcOptions(FirstOption=7 연마 효과)로 우회 필터가 되는지 확인

요청 1건당 결과를 즉시 출력한다. rate limit 은 client 가 알아서 막는다.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.search import build_payload as _bp  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

NECK = 200010


def build_payload(category, page, quality, etc_options=None, extra=None):
    return _bp(category, page, grade_quality=quality, etc_options=etc_options, extra=extra)


def run(client: LostArkClient, label: str, payload: dict) -> dict | None:
    print(f"\n{'=' * 70}\n[{label}]")
    base = build_payload(NECK, 1, 70)
    diff = {k: v for k, v in payload.items() if k not in base or base[k] != v}
    print(f"  변경분: {json.dumps(diff, ensure_ascii=False)}")
    try:
        resp = client.search_auctions(payload)
    except LostArkAPIError as exc:
        print(f"  → HTTP {exc.status}")
        print(f"     {exc.body[:400]}")
        return None

    items = (resp or {}).get("Items") or []
    lv = Counter(it["AuctionInfo"]["UpgradeLevel"] for it in items)
    types: Counter[str] = Counter()
    for it in items:
        for o in it.get("Options") or []:
            types[o["Type"]] += 1
    print(f"  → TotalCount={resp.get('TotalCount')}  Items={len(items)}")
    print(f"     UpgradeLevel 분포={dict(sorted(lv.items()))}")
    print(f"     Option Type={dict(types)}")
    return resp


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    base = build_payload(NECK, 1, 70)
    baseline = run(client, "baseline (필터 없음)", dict(base))
    if baseline is None:
        return 1
    base_total = baseline.get("TotalCount")

    # --- 1) 필드명 후보 ---
    candidates = [
        ("ItemUpgradeLevel", {"ItemUpgradeLevel": 2}),
        ("UpgradeLevel", {"UpgradeLevel": 2}),
        ("ItemUpgradeLevelMin/Max", {"ItemUpgradeLevelMin": 2, "ItemUpgradeLevelMax": 2}),
        ("UpgradeLevelMin/Max", {"UpgradeLevelMin": 2, "UpgradeLevelMax": 2}),
        ("존재하지않는필드(대조군)", {"ZZZ_NoSuchField": 12345}),
    ]
    results: dict[str, int | None] = {}
    for label, extra in candidates:
        p = build_payload(NECK, 1, 70, extra=extra)
        r = run(client, f"후보: {label}", p)
        results[label] = r.get("TotalCount") if r else None

    # --- 2) EtcOptions 우회 ---
    # FirstOption=7 (연마 효과), SecondOption=42 (적에게 주는 피해 증가, 목걸이 전용)
    etc_one = [{"FirstOption": 7, "SecondOption": 42, "MinValue": None, "MaxValue": None}]
    r_one = run(client, "EtcOptions 1개 (연마7 / 적주피42)",
                build_payload(NECK, 1, 70, etc_options=etc_one))

    # 2개 지정 → 2연마 이상만 남는지
    etc_two = etc_one + [{"FirstOption": 7, "SecondOption": 41, "MinValue": None, "MaxValue": None}]
    r_two = run(client, "EtcOptions 2개 (적주피42 + 추피41)",
                build_payload(NECK, 1, 70, etc_options=etc_two))

    # --- 요약 ---
    print(f"\n{'=' * 70}\n=== 판정 ===")
    print(f"baseline TotalCount = {base_total}")
    for label, total in results.items():
        if total is None:
            verdict = "요청 거부(400) → 스키마 검증됨"
        elif total == base_total:
            verdict = "무시됨 → 필터 아님"
        else:
            verdict = f"TotalCount 변화 {base_total} → {total} · 먹힘 가능성"
        print(f"  {label:<28} {verdict}")
    for label, r in (("EtcOptions 1개", r_one), ("EtcOptions 2개", r_two)):
        if r:
            print(f"  {label:<28} TotalCount={r.get('TotalCount')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
