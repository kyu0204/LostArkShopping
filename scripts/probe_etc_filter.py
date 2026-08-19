"""EtcOptions 필터가 실제로 먹는지 건건이 대조한다.

  python scripts/probe_etc_filter.py

증상: 옵션을 선택하고 수집했는데 해당 옵션이 없는 매물이 섞여 나온다.

검사 방법: 요청에 실은 (옵션, 최소수치)를 반환된 매물 전부와 대조해
  - 그 옵션 자체가 없는 매물 수
  - 있지만 최소수치 미만인 매물 수
를 센다. 0이어야 정상.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from loa import options as opt  # noqa: E402
from loa.client import LostArkAPIError, LostArkClient  # noqa: E402
from loa.models import Listing  # noqa: E402
from loa.normalize import normalize_response  # noqa: E402
from loa.search import build_payload  # noqa: E402
from scripts._env import ensure_api_key  # noqa: E402

NECK, EAR, RING = 200010, 200020, 200030
POLISH_AXIS = opt.ETC_POLISH


def find_sub(payload: dict, category: int, text: str) -> dict:
    for sub in opt.option_pool(payload, category):
        if sub.get("Text") == text:
            return sub
    raise KeyError(f"{text} 없음")


def check(client, payload, label: str, category: int, upgrade: int, specs: list[tuple[dict, str | None]]):
    """specs: [(EtcSub, 등급라벨 또는 None)]"""
    etc = []
    wanted: list[tuple[str, float | None]] = []
    for sub, display in specs:
        value = None
        number = None
        if display is not None:
            for ev in sub.get("EtcValues") or []:
                if ev.get("DisplayValue") == display:
                    value = ev.get("Value")
                    number = opt.etc_value_number(ev)
                    break
        etc.append(
            {
                "FirstOption": POLISH_AXIS,
                "SecondOption": sub.get("Value"),
                "MinValue": value,
                "MaxValue": None,
            }
        )
        wanted.append((opt.option_key(sub), number))

    body = build_payload(
        category, 1, grade_quality=70, upgrade_level=upgrade, etc_options=etc
    )
    try:
        resp = client.search_auctions(body)
    except LostArkAPIError as exc:
        print(f"\n[{label}] HTTP {exc.status} — {exc.body[:200]}")
        return

    listings: list[Listing] = normalize_response(resp, category)
    total = resp.get("TotalCount")
    missing: list[str] = []
    below: list[str] = []
    for ls in listings:
        for key, minimum in wanted:
            got = ls.upgrade_value(key)
            if got is None:
                missing.append(f"{key} 없음 ({sorted(ls.upgrades)})")
            elif minimum is not None and got < minimum:
                below.append(f"{key} {got} < {minimum}")

    print(f"\n[{label}]")
    print(f"  요청 EtcOptions: {etc}")
    print(f"  TotalCount={total}  반환={len(listings)}건")
    print(f"  옵션 누락 {len(missing)}건 · 최소수치 미달 {len(below)}건")
    for m in missing[:4]:
        print(f"     누락: {m}")
    for b in below[:4]:
        print(f"     미달: {b}")


def main() -> int:
    key = ensure_api_key()
    if not key:
        return 1
    client = LostArkClient(api_key=key)
    payload = opt.fetch_options(client)

    jujupi = find_sub(payload, NECK, "적에게 주는 피해 증가")
    chupi = find_sub(payload, NECK, "추가 피해")
    nakin = find_sub(payload, NECK, "낙인력")
    maxhp = find_sub(payload, NECK, "최대 생명력")

    # 1) 옵션 1개, 수치 미지정
    check(client, payload, "적주피만 (수치 미지정) · 3연마", NECK, 3, [(jujupi, None)])

    # 2) 옵션 1개 + 등급별 최소수치
    for disp in ("0.55%", "1.20%", "2.00%"):
        check(client, payload, f"적주피 최소 {disp} · 3연마", NECK, 3, [(jujupi, disp)])

    # 3) 옵션 2개
    check(client, payload, "적주피 + 추피 (수치 미지정) · 3연마", NECK, 3,
          [(jujupi, None), (chupi, None)])
    check(client, payload, "적주피 1.20% + 추피 1.60% · 3연마", NECK, 3,
          [(jujupi, "1.20%"), (chupi, "1.60%")])

    # 4) 옵션 3개
    check(client, payload, "적주피 + 추피 + 낙인력 · 3연마", NECK, 3,
          [(jujupi, None), (chupi, None), (nakin, None)])

    # 5) 공통(단순 수치) 옵션 — 전용 옵션과 다르게 동작하는지
    check(client, payload, "최대 생명력만 · 3연마", NECK, 3, [(maxhp, None)])
    check(client, payload, "최대 생명력 최소 3250 · 3연마", NECK, 3, [(maxhp, "3250")])

    # 6) 연마 단계보다 옵션을 많이 지정 (하한선 규칙이 막아야 하는 상황)
    check(client, payload, "옵션 3개인데 2연마 (있을 수 없는 조합)", NECK, 2,
          [(jujupi, None), (chupi, None), (nakin, None)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
