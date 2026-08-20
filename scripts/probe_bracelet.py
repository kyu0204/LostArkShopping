"""팔찌 검색 축 실측.

  python scripts/probe_bracelet.py

확인할 것
  1. 옵션 수량 축(FirstOption=4) — 고정 효과 수량 / 부여 효과 수량이 실제로 걸리는가
  2. 전투 특성 축(FirstOption=2) — 치명/특화/신속… 이 걸리는가, 수치 범위는 먹는가
  3. '1특성 / 2특성'을 표현할 방법 — 전용 축이 있는가, 없으면 무엇으로 대체하는가

MinValue 는 MaxValue 가 있어야 먹는다 (FINDINGS §6). 대조군을 함께 둔다.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.normalize import normalize_response  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

BRACELET = 200040
AXIS_COUNT = opt.ETC_BRACELET_COUNT  # 4 — 팔찌 옵션 수량
AXIS_COMBAT = 2  # 전투 특성
AXIS_SPECIAL = opt.ETC_BRACELET_SPECIAL  # 5 — 팔찌 특수 효과

SUB_FIXED, SUB_RANDOM = 1, 2  # 고정 효과 수량 / 부여 효과 수량
COMBAT = {15: "치명", 16: "특화", 17: "제압", 18: "신속", 19: "인내", 20: "숙련"}


CAP = 10000  # TotalCount 상한. 이 값이면 '조건이 안 걸렸다'로 읽으면 안 된다.


def run(client, label: str, etc: list[dict], baseline: int | None = None) -> int | None:
    try:
        resp = client.search_auctions(
            build_payload(BRACELET, 1, grade_quality=None, etc_options=etc)
        )
    except LostArkAPIError as exc:
        print(f"  {label:<40} HTTP {exc.status}  {exc.body[:100]}")
        return None
    total = resp.get("TotalCount")
    listings = normalize_response(resp, BRACELET)

    slots = Counter()
    traits = Counter()
    for ls in listings:
        for name, value in ls.bracelet_slots.items():
            slots[f"{name}={int(value)}"] += 1
        traits[len(ls.combat_stats)] += 1

    # TotalCount 만으로 판정하면 안 된다 — 상한(10000)에 걸리면 기준선과 같은 값이 나온다.
    # 반환분이 조건을 만족하는지를 함께 본다.
    mark = ""
    if baseline is not None:
        if total != baseline:
            mark = "  <- 먹힘"
        elif total >= CAP:
            mark = "  <- 상한(10000) · 반환분으로 판단"
        else:
            mark = "  <- 무시됨"
    print(f"  {label:<40} TotalCount={total:<7}{mark}")
    if listings:
        print(f"      수량 분포={dict(slots)}  특성 개수 분포={dict(sorted(traits.items()))}")
    return total


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    print("=== 기준선 ===")
    base = run(client, "조건 없음", [])

    print("\n=== 1. 옵션 수량 축 (FirstOption=4) ===")
    for sub, name in ((SUB_RANDOM, "부여 효과 수량"), (SUB_FIXED, "고정 효과 수량")):
        run(client, f"{name} (수치 미지정)",
            [{"FirstOption": AXIS_COUNT, "SecondOption": sub,
              "MinValue": None, "MaxValue": None}], base)
        for n in (1, 2, 3):
            run(client, f"{name} = {n}",
                [{"FirstOption": AXIS_COUNT, "SecondOption": sub,
                  "MinValue": n, "MaxValue": n}], base)

    print("\n=== 2. 전투 특성 축 (FirstOption=2) ===")
    run(client, "특화 (수치 미지정)",
        [{"FirstOption": AXIS_COMBAT, "SecondOption": 16,
          "MinValue": None, "MaxValue": None}], base)
    for lo, hi in ((60, 200), (80, 200), (100, 200)):
        run(client, f"특화 {lo}~{hi}",
            [{"FirstOption": AXIS_COMBAT, "SecondOption": 16,
              "MinValue": lo, "MaxValue": hi}], base)

    print("\n=== 3. 특성 2개 지정 = 2특성인가 ===")
    run(client, "특화 + 치명",
        [{"FirstOption": AXIS_COMBAT, "SecondOption": 16, "MinValue": None, "MaxValue": None},
         {"FirstOption": AXIS_COMBAT, "SecondOption": 15, "MinValue": None, "MaxValue": None}],
        base)
    run(client, "특화 + 치명 + 신속",
        [{"FirstOption": AXIS_COMBAT, "SecondOption": s, "MinValue": None, "MaxValue": None}
         for s in (16, 15, 18)], base)

    print("\n=== 4. 수량 + 특성 조합 ===")
    run(client, "부여 2 + 특화",
        [{"FirstOption": AXIS_COUNT, "SecondOption": SUB_RANDOM, "MinValue": 2, "MaxValue": 2},
         {"FirstOption": AXIS_COMBAT, "SecondOption": 16, "MinValue": None, "MaxValue": None}],
        base)

    print("\n=== 5. 대조군 (존재하지 않는 축) ===")
    run(client, "FirstOption=99",
        [{"FirstOption": 99, "SecondOption": 1, "MinValue": 1, "MaxValue": 1}], base)

    # ---- 특수 효과 축 ----
    print("\n=== 6. 팔찌 특수 효과 축 (FirstOption=5) ===")
    pool = opt.option_pool(client and payload_cache(client), BRACELET, axis=AXIS_SPECIAL)
    sample = {s["Text"]: s["Value"] for s in pool}
    print(f"  옵션 {len(sample)}개 · EtcValues 보유: "
          f"{sum(1 for s in pool if s.get('EtcValues'))}개")
    for text in ("마법 방어력", "전투 중 생명력 회복량", "최대 생명력"):
        if text not in sample:
            continue
        run(client, f"{text} (수치 미지정)",
            [{"FirstOption": AXIS_SPECIAL, "SecondOption": sample[text],
              "MinValue": None, "MaxValue": None}], base)
        run(client, f"{text} 3000~99999",
            [{"FirstOption": AXIS_SPECIAL, "SecondOption": sample[text],
              "MinValue": 3000, "MaxValue": 99999}], base)

    # ---- 고정 효과는 특성 + 특수 합쳐서 최대 2개인가 ----
    print("\n=== 7. 특성 + 특수 효과 합계 제약 ===")
    magic = sample.get("마법 방어력")
    if magic:
        run(client, "특성1(특화) + 특수1(마법 방어력)",
            [{"FirstOption": AXIS_COMBAT, "SecondOption": 16,
              "MinValue": None, "MaxValue": None},
             {"FirstOption": AXIS_SPECIAL, "SecondOption": magic,
              "MinValue": None, "MaxValue": None}], base)
        run(client, "특성2(특화+치명) + 특수1(마법 방어력)",
            [{"FirstOption": AXIS_COMBAT, "SecondOption": 16,
              "MinValue": None, "MaxValue": None},
             {"FirstOption": AXIS_COMBAT, "SecondOption": 15,
              "MinValue": None, "MaxValue": None},
             {"FirstOption": AXIS_SPECIAL, "SecondOption": magic,
              "MinValue": None, "MaxValue": None}], base)

    # ---- 관측 분포로 확인 ----
    print("\n=== 8. 관측: 특성 + 특수 효과 개수 합 ===")
    try:
        resp = client.search_auctions(build_payload(BRACELET, 1, grade_quality=None))
        combos = Counter()
        traits_max = 0
        for ls in normalize_response(resp, BRACELET):
            combos[(len(ls.combat_stats), len(ls.bracelet_special))] += 1
            for v in ls.combat_stats.values():
                traits_max = max(traits_max, int(v))
        print(f"  (특성수, 특수수) 분포: {dict(sorted(combos.items()))}")
        print(f"  관측된 전투 특성 최대 수치: {traits_max}")
    except LostArkAPIError as exc:
        print(f"  HTTP {exc.status}")
    return 0


_payload = None


def payload_cache(client):
    global _payload
    if _payload is None:
        _payload = opt.fetch_options(client)
    return _payload


if __name__ == "__main__":
    raise SystemExit(main())
