"""체력 범위의 하한을 직접 조회해 확정한다.

  python scripts/probe_hp_range.py

EtcOptions 의 '장신구 기본 효과'(FirstOption=1) 축에 체력(SecondOption=6)이 있다.
MinValue/MaxValue 로 체력 구간을 직접 지정해 매물이 존재하는지 본다.
(MinValue 는 MaxValue 가 있어야 먹는다 — FINDINGS §6)

격자 적합이 내놓은 하한과, 더 아래 구간의 실재 여부를 대조한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.normalize import normalize_response  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

HP_SUB = 6  # '체력'
CASES = [
    # 부위, 3연마 기준: (격자 적합 하한, 사용자 제시 하한, 공통 상한)
    (200010, "목걸이", 3754, 3323, 4103),
    (200020, "귀걸이", 2682, 2374, 2931),
    (200030, "반지", 2146, 1900, 2345),
]


def probe(client, cat: int, lo: int, hi: int, label: str) -> None:
    etc = [{
        "FirstOption": opt.ETC_BASE_STAT,
        "SecondOption": HP_SUB,
        "MinValue": lo,
        "MaxValue": hi,
    }]
    try:
        resp = client.search_auctions(
            build_payload(cat, 1, grade_quality=None, upgrade_level=3, etc_options=etc)
        )
    except LostArkAPIError as exc:
        print(f"    {label:<26} HTTP {exc.status}")
        return
    total = resp.get("TotalCount")
    hps = sorted({ls.stat_hp for ls in normalize_response(resp, cat)})
    print(f"    {label:<26} TotalCount={total:<6} 반환 체력={hps[:6]}")


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)

    print("먼저 이 축에서 MinValue/MaxValue 가 먹는지 확인 (목걸이 3연마)")
    probe(client, 200010, None, None, "조건 없음 (기준선)")
    probe(client, 200010, 4000, 4103, "체력 4000~4103")

    for cat, name, fit_lo, user_lo, hi in CASES:
        print(f"\n=== {name} 3연마 ===")
        probe(client, cat, fit_lo, hi, f"격자적합 {fit_lo}~{hi}")
        probe(client, cat, user_lo, fit_lo - 1, f"그 아래 {user_lo}~{fit_lo - 1}")
        probe(client, cat, user_lo, hi, f"제시범위 {user_lo}~{hi}")
        probe(client, cat, user_lo - 400, user_lo - 1,
              f"더 아래 {user_lo - 400}~{user_lo - 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
