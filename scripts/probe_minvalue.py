"""MinValue/MaxValue 가 어떤 형태여야 먹는지 좁힌다.

  python scripts/probe_minvalue.py

앞선 probe_etc_filter.py 결과:
  SecondOption(옵션 지정)은 정확히 먹는다.
  MinValue 는 값과 무관하게 TotalCount 가 고정 → 무시되고 있다.

서버는 미지 필드를 400 없이 버리므로, TotalCount 가 기준선과 같으면 '안 먹은 것'이다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.normalize import normalize_response  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

NECK = 200010
JUJUPI = 42  # 적에게 주는 피해 증가 (고대: 0.55 / 1.20 / 2.00 → Value 55/120/200)
CRIT = 15  # 전투 특성 '치명'


def run(client, label: str, etc: list[dict], baseline: int | None = None) -> int | None:
    body = build_payload(NECK, 1, grade_quality=70, upgrade_level=3, etc_options=etc)
    try:
        resp = client.search_auctions(body)
    except LostArkAPIError as exc:
        print(f"  {label:<44} HTTP {exc.status}  {exc.body[:120]}")
        return None
    total = resp.get("TotalCount")
    listings = normalize_response(resp, NECK)
    vals = sorted({ls.upgrade_value("적에게 주는 피해 증가%") for ls in listings} - {None})
    mark = ""
    if baseline is not None:
        mark = "  ← 무시됨" if total == baseline else "  ← 먹힘"
    print(f"  {label:<44} TotalCount={total:<6} 반환값={vals}{mark}")
    return total


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)
    axis = opt.ETC_POLISH

    print("기준선 (옵션만 지정, 수치 조건 없음)")
    base = run(client, "MinValue/MaxValue = null", [
        {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": None, "MaxValue": None}
    ])
    print(f"\n=== 형태 실험 (기준선 {base}) ===")

    variants: list[tuple[str, dict]] = [
        # 값 스케일 — EtcValues 의 Value(100배 정수)
        ("MinValue=200 (상), MaxValue=null",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": None}),
        ("MinValue=200, MaxValue=200 (정확일치)",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": 200}),
        ("MinValue=200, MaxValue=99999",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": 99999}),
        ("MinValue=0, MaxValue=55 (하만)",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 0, "MaxValue": 55}),
        # 실수치 스케일
        ("MinValue=2 (실수치 2.0)",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 2, "MaxValue": None}),
        # 키 자체를 뺀 경우 (기준선과 같아야 정상)
        ("MinValue/MaxValue 키 없음",
         {"FirstOption": axis, "SecondOption": JUJUPI}),
        # 다른 철자 후보
        ("Min/Max",
         {"FirstOption": axis, "SecondOption": JUJUPI, "Min": 200, "Max": 99999}),
        ("MinValue2/MaxValue2 (대조군 · 무조건 무시돼야 함)",
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue2": 200, "MaxValue2": 99999}),
        # 문자열
        ('MinValue="200" (문자열)',
         {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": "200", "MaxValue": None}),
        # ThirdOption 이라는 필드가 있는지
        ("ThirdOption=200",
         {"FirstOption": axis, "SecondOption": JUJUPI, "ThirdOption": 200,
          "MinValue": None, "MaxValue": None}),
    ]
    for label, etc in variants:
        run(client, label, [etc], base)

    # 다른 축(전투 특성)에서는 MinValue 가 먹는지 — 축의 문제인지 구분
    print("\n=== 다른 축: 전투 특성(FirstOption=2) '치명' ===")
    cbase = run(client, "치명, 수치 조건 없음", [
        {"FirstOption": 2, "SecondOption": CRIT, "MinValue": None, "MaxValue": None}
    ])
    run(client, "치명 MinValue=80", [
        {"FirstOption": 2, "SecondOption": CRIT, "MinValue": 80, "MaxValue": None}
    ], cbase)
    run(client, "치명 MinValue=80, MaxValue=200", [
        {"FirstOption": 2, "SecondOption": CRIT, "MinValue": 80, "MaxValue": 200}
    ], cbase)

    # 같은 옵션을 두 번 실으면? (등급 범위를 두 항목으로 표현하는 형태인지)
    print("\n=== 같은 옵션 2회 ===")
    run(client, "적주피 × 2 (동일)", [
        {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": None},
        {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": None},
    ], base)

    print("\n원본 요청 예시:")
    print(json.dumps(
        build_payload(NECK, 1, grade_quality=70, upgrade_level=3, etc_options=[
            {"FirstOption": axis, "SecondOption": JUJUPI, "MinValue": 200, "MaxValue": 200}
        ]), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
